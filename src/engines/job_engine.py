import datetime
import logging
import os

from google.cloud import firestore, secretmanager, storage

from src.core.monday_client import MondayClient
from src.engines.classification_engine import ClassificationEngine
from src.engines.discovery_engine import DiscoveryEngine
from src.engines.report_engine import ReportEngine

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "local-dev-project")
REPORTS_BUCKET = os.environ.get("REPORTS_BUCKET", "local-dev-reports-bucket")

try:
    db = firestore.Client(project=PROJECT_ID)
    storage_client = storage.Client(project=PROJECT_ID)
    secret_client = secretmanager.SecretManagerServiceClient()
except Exception as e:  # noqa: BLE001
    logger.warning(f"Failed to initialize GCP clients (ensure ADC is set): {e}")
    db = None
    storage_client = None
    secret_client = None


def set_job_status(
    job_id: str, status: str, report_path: str | None = None, error: str | None = None
):
    """Helper to update Firestore job status"""
    if not db:
        logger.warning(f"No Firestore client. Would update job {job_id} to {status}")
        return
    doc_ref = db.collection("jobs").document(job_id)
    update_data = {"status": status, "updated_at": datetime.datetime.now(datetime.UTC)}
    if report_path:
        update_data["report_path"] = report_path
    if error:
        update_data["error"] = error
    doc_ref.set(update_data, merge=True)


def get_job(job_id: str):
    """Helper to retrieve Firestore job status"""
    if not db:
        return None
    doc = db.collection("jobs").document(job_id).get()
    if doc.exists:
        return doc.to_dict()
    return None


async def execute_discovery_job(job_id: str):
    """
    Core execution logic for a migration discovery job.
    Designed to be run as a standalone Cloud Run Job (or locally in the CLI).
    Reads the API key from Secret Manager, processes the account, and saves the result to GCS.
    """
    logger.info(f"Starting discovery job execution for {job_id}")
    set_job_status(job_id, "RUNNING")

    try:
        # 1. Fetch API Key from Secret Manager
        if not secret_client:
            raise RuntimeError("Secret Manager client is not initialized.")

        secret_name = (
            f"projects/{PROJECT_ID}/secrets/job-{job_id}-source-key/versions/latest"
        )
        response = secret_client.access_secret_version(request={"name": secret_name})
        source_api_key = response.payload.data.decode("UTF-8")

        # 2. Discovery
        client = MondayClient(api_key=source_api_key)
        discovery_engine = DiscoveryEngine(client=client)

        local_inventory_path = f"/tmp/{job_id}_inventory.json"
        inventory = await discovery_engine.discover_full_account(
            output_path=local_inventory_path
        )

        # 3. Classification
        classification_engine = ClassificationEngine()
        classified_inventory = classification_engine.process_inventory(inventory)

        # 4. Report Generation
        report_generator = ReportEngine()
        report_md = report_generator.generate_markdown_report(classified_inventory)
        local_report_path = f"/tmp/{job_id}_report.md"
        report_generator.save_report(report_md, file_path=local_report_path)

        # Save classified inventory locally for upload
        import json

        local_classified_path = f"/tmp/{job_id}_classified_inventory.json"
        with open(local_classified_path, "w", encoding="utf-8") as f:  # noqa: ASYNC230
            json.dump(classified_inventory, f, indent=2)

        # 5. Upload to Cloud Storage
        report_gcs_path = None
        if storage_client:
            bucket = storage_client.bucket(REPORTS_BUCKET)

            # Upload Report
            report_blob_name = f"reports/{job_id}/pre_migration_report.md"
            report_blob = bucket.blob(report_blob_name)
            report_blob.upload_from_filename(local_report_path)
            report_gcs_path = report_blob_name
            logger.info(
                f"Uploaded report to GCS: gs://{REPORTS_BUCKET}/{report_blob_name}"
            )

            # Upload Classified Inventory
            inventory_blob_name = f"reports/{job_id}/inventory.json"
            inventory_blob = bucket.blob(inventory_blob_name)
            inventory_blob.upload_from_filename(local_classified_path)
            logger.info(
                f"Uploaded inventory to GCS: gs://{REPORTS_BUCKET}/{inventory_blob_name}"
            )

        set_job_status(job_id, "COMPLETED", report_path=report_gcs_path)
        logger.info(f"Discovery job {job_id} completed successfully.")

    except Exception as e:  # noqa: BLE001
        logger.error(f"Discovery job {job_id} failed: {e}")
        set_job_status(job_id, "FAILED", error=str(e))
