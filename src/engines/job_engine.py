import datetime
import json
import logging
import os
from collections.abc import Callable
from typing import Any

from google.cloud import firestore, secretmanager, storage

from src.engines.interfaces import (
    ClassifierInterface,
    DiscovererInterface,
    ReporterInterface,
    StateInterface,
)

logger = logging.getLogger(__name__)


class JobEngine:
    """
    Manages job state and executes the core discovery/classification workflow.
    """

    def __init__(
        self,
        classifier: ClassifierInterface,
        reporter: ReporterInterface,
        discovery_factory: Callable[[str], DiscovererInterface],
        state_manager: StateInterface | None = None,
        project_id: str | None = None,
        reports_bucket: str | None = None,
    ):
        """
        Initializes the JobEngine with necessary dependencies and GCP clients.

        # ==============================================================================
        # EDUCATIONAL NOTE: DEPENDENCY INVERSION (SOLID "D")
        # ==============================================================================
        # BEFORE:
        # We had no dependencies injected. JobEngine imported the concrete
        # ClassificationEngine directly and instantiated it inline. This violated DIP
        # because the high-level JobEngine depended on a low-level concrete implementation.
        #
        # POOR MAN's DI (The "or" pattern):
        # We could have done `self.classifier = classifier or ClassificationEngine()`.
        # But this STILL requires JobEngine to import `ClassificationEngine` as the fallback,
        # meaning they are still tightly coupled.
        #
        # AFTER (True Dependency Injection):
        # We inject the Interfaces (Protocols). JobEngine has ZERO imports of concrete
        # engines now. It is completely decoupled. If we want to unit test JobEngine,
        # we pass in dummy objects that match the Protocol.
        #
        # THE FACTORY PATTERN (discovery_factory):
        # We can't inject an instantiated DiscoveryEngine because it requires an API key
        # that we only fetch dynamically during the job execution.
        # Instead, we inject a Factory (`Callable[[str], DiscovererInterface]`). JobEngine
        # knows: "If I pass a string (API key) to this factory function, I get a Discoverer."
        # ==============================================================================

        Args:
            classifier: An injected instance satisfying the ClassifierInterface.
            reporter: An injected instance satisfying the ReporterInterface.
            discovery_factory: A function that takes an API key and returns a Discoverer.
            state_manager: An injected instance satisfying the StateInterface.
            project_id: The GCP project ID. Defaults to env var PROJECT_ID.
            reports_bucket: The GCS bucket for reports. Defaults to env var REPORTS_BUCKET.
        """
        self.classifier = classifier
        self.reporter = reporter
        self.discovery_factory = discovery_factory
        self.state_manager = state_manager

        self.project_id = project_id or os.environ.get(
            "PROJECT_ID", "local-dev-project"
        )
        self.reports_bucket = reports_bucket or os.environ.get(
            "REPORTS_BUCKET", "local-dev-reports-bucket"
        )

        # Lazy load clients to prevent multiprocessing/forking issues
        self._db = None
        self._storage_client = None
        self._secret_client = None

    @property
    def db(self):
        if self._db is None:
            try:
                self._db = firestore.Client(project=self.project_id)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to initialize Firestore client: {e}")
        return self._db

    @property
    def storage_client(self):
        if self._storage_client is None:
            try:
                self._storage_client = storage.Client(project=self.project_id)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to initialize Storage client: {e}")
        return self._storage_client

    @property
    def secret_client(self):
        if self._secret_client is None:
            try:
                self._secret_client = secretmanager.SecretManagerServiceClient()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to initialize Secret Manager client: {e}")
        return self._secret_client

    def has_firestore(self) -> bool:
        """Checks if Firestore is initialized."""
        return self.db is not None

    def set_job_status(
        self,
        job_id: str,
        status: str,
        report_path: str | None = None,
        error: str | None = None,
    ) -> None:
        """
        Updates the Firestore job status.

        Args:
            job_id: The unique identifier of the job.
            status: The new status string.
            report_path: Optional GCS path to the generated report.
            error: Optional error message if the job failed.
        """
        if not self.db:
            logger.warning(
                f"No Firestore client. Would update job {job_id} to {status}"
            )
            return

        doc_ref = self.db.collection("jobs").document(job_id)
        update_data = {
            "status": status,
            "updated_at": datetime.datetime.now(datetime.UTC),
        }

        # Ensure JobDocument required fields are present if we are initializing a PENDING job
        if status == "PENDING":
            update_data["job_id"] = job_id
            update_data["operator_email"] = "system@local"
            update_data["source_account"] = {"secret_ref": f"job-{job_id}-source-key"}
            update_data["dest_account"] = {"secret_ref": "pending"}

        if report_path:
            update_data["report_path"] = report_path
        if error:
            update_data["error"] = error

        doc_ref.set(update_data, merge=True)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """
        Retrieves Firestore job status.

        Args:
            job_id: The unique identifier of the job.

        Returns:
            The job document dictionary, or None if it doesn't exist.
        """
        if self.state_manager:
            # Prefer using the injected StateInterface if provided to align with DIP
            job = self.state_manager.get_job(job_id)
            return job.model_dump() if job else None

        if not self.db:
            return None

        doc = self.db.collection("jobs").document(job_id).get()
        if doc.exists:
            return doc.to_dict()
        return None

    def cancel_job(self, job_id: str) -> None:
        """Cancels a pending or running job."""
        self.set_job_status(job_id, "CANCELLED")

    def delete_job(self, job_id: str) -> None:
        """
        Deletes the job document and all its subcollections from Firestore.
        NOTE: GCP artifacts (secrets, GCS) should be deleted by the router.
        """
        if not self.db:
            logger.warning(f"No Firestore client. Cannot delete job {job_id}")
            return

        job_ref = self.db.collection("jobs").document(job_id)

        # In a real production app, you would also recursively delete subcollections
        # (e.g. inventory, dag_state, dead_letters).
        # For this prototype, deleting the root document prevents it from loading.
        job_ref.delete()
        logger.info(f"Deleted job {job_id} from Firestore.")

    async def execute_discovery_job(self, job_id: str) -> None:
        """
        Core execution logic for a migration discovery job.
        Reads the API key from Secret Manager, processes the account, and saves the result to GCS.

        Args:
            job_id: The unique identifier of the job.

        Raises:
            RuntimeError: If dependencies like SecretManager fail to initialize.
        """
        logger.info(f"Starting discovery job execution for {job_id}")
        self.set_job_status(job_id, "RUNNING")

        try:
            # 1. Fetch API Key from Secret Manager
            if not self.secret_client:
                raise RuntimeError("Secret Manager client is not initialized.")

            secret_name = f"projects/{self.project_id}/secrets/job-{job_id}-source-key/versions/latest"
            response = self.secret_client.access_secret_version(
                request={"name": secret_name}
            )
            source_api_key = response.payload.data.decode("UTF-8")

            # 2. Discovery
            # ==============================================================================
            # EDUCATIONAL NOTE: USING THE INJECTED FACTORY
            # ==============================================================================
            # BEFORE:
            # client = MondayClient(api_key=source_api_key)
            # discovery_engine = DiscoveryEngine(client=client)
            #
            # AFTER:
            # We don't care how the Discoverer is built or what client it uses.
            # We just pass the required runtime data to the factory and get an instance back.
            # ==============================================================================
            discoverer = self.discovery_factory(source_api_key)

            local_inventory_path = f"/tmp/{job_id}_inventory.json"
            inventory = await discoverer.discover_full_account(
                output_path=local_inventory_path
            )

            # 3. Classification
            # ==============================================================================
            # EDUCATIONAL NOTE: USING INJECTED PROTOCOLS
            # ==============================================================================
            # BEFORE:
            # classification_engine = ClassificationEngine()
            # classified_inventory = classification_engine.process_inventory(inventory)
            #
            # AFTER:
            # We just use the `self.classifier` injected at construction.
            # ==============================================================================
            classified_inventory = self.classifier.process_inventory(inventory)

            # 4. Report Generation
            report_md = self.reporter.generate_markdown_report(classified_inventory)
            local_report_path = f"/tmp/{job_id}_report.md"
            self.reporter.save_report(report_md, file_path=local_report_path)

            # Save classified inventory locally for upload
            local_classified_path = f"/tmp/{job_id}_classified_inventory.json"
            with open(local_classified_path, "w", encoding="utf-8") as f:  # noqa: ASYNC230
                json.dump(classified_inventory, f, indent=2)

            # 5. Upload to Cloud Storage
            report_gcs_path = None
            if self.storage_client:
                bucket = self.storage_client.bucket(self.reports_bucket)

                # Upload Report
                report_blob_name = f"reports/{job_id}/pre_migration_report.md"
                report_blob = bucket.blob(report_blob_name)
                report_blob.upload_from_filename(local_report_path)
                report_gcs_path = report_blob_name
                logger.info(
                    f"Uploaded report to GCS: gs://{self.reports_bucket}/{report_blob_name}"
                )

                # Upload Classified Inventory
                inventory_blob_name = f"reports/{job_id}/inventory.json"
                inventory_blob = bucket.blob(inventory_blob_name)
                inventory_blob.upload_from_filename(local_classified_path)
                logger.info(
                    f"Uploaded inventory to GCS: gs://{self.reports_bucket}/{inventory_blob_name}"
                )

            self.set_job_status(job_id, "COMPLETED", report_path=report_gcs_path)
            logger.info(f"Discovery job {job_id} completed successfully.")

        except Exception as e:  # noqa: BLE001
            logger.error(f"Discovery job {job_id} failed: {e}")
            self.set_job_status(job_id, "FAILED", error=str(e))
