import logging
import os
from typing import Any

from google.cloud import firestore

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "local-dev-project")


class StateManager:
    """
    Manages job state and idempotency mappings in Firestore.
    """

    def __init__(self, project_id: str = PROJECT_ID):
        """
        Initializes the StateManager with a Firestore client.

        Args:
            project_id (str): The GCP project ID for Firestore.
        """
        self.project_id = project_id
        try:
            self.db = firestore.Client(project=project_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"Failed to initialize Firestore client in StateManager: {e}"
            )
            self.db = None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """
        Retrieves the state of a migration job.

        Args:
            job_id (str): The unique identifier of the job.

        Returns:
            Optional[Dict[str, Any]]: The job document dict if it exists, else None.
        """
        if not self.db:
            return None
        doc = self.db.collection("jobs").document(job_id).get()
        if doc.exists:
            return doc.to_dict()
        return None

    def get_dest_id(self, job_id: str, entity_type: str, source_id: str) -> str | None:
        """
        Retrieves the destination ID for a given source ID to ensure idempotency.

        Args:
            job_id (str): The current job ID.
            entity_type (str): The type of entity (e.g., 'workspace', 'board', 'item').
            source_id (str): The ID of the entity in the source account.

        Returns:
            Optional[str]: The destination ID if the entity has already been created, else None.
        """
        if not self.db:
            return None

        doc_ref = (
            self.db.collection("jobs")
            .document(job_id)
            .collection("id_map")
            .document(f"{entity_type}_{source_id}")
        )
        doc = doc_ref.get()

        if doc.exists:
            data = doc.to_dict()
            return data.get("dest_id")
        return None

    def set_dest_id(
        self, job_id: str, entity_type: str, source_id: str, dest_id: str
    ) -> None:
        """
        Stores the destination ID mapped to the source ID for future idempotency checks.

        Args:
            job_id (str): The current job ID.
            entity_type (str): The type of entity (e.g., 'workspace', 'board', 'item').
            source_id (str): The ID of the entity in the source account.
            dest_id (str): The ID of the entity created in the destination account.
        """
        if not self.db:
            logger.warning(
                f"No Firestore client. Would map {entity_type} {source_id} -> {dest_id} for job {job_id}"
            )
            return

        doc_ref = (
            self.db.collection("jobs")
            .document(job_id)
            .collection("id_map")
            .document(f"{entity_type}_{source_id}")
        )
        doc_ref.set(
            {
                "source_id": source_id,
                "dest_id": dest_id,
                "entity_type": entity_type,
                "created_at": firestore.SERVER_TIMESTAMP,
            }
        )
