import logging
import os

from google.cloud import firestore

from src.core.schemas import JobDocument, MigrationDag

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

    def get_job(self, job_id: str) -> JobDocument | None:
        """
        Retrieves the state of a migration job.

        Args:
            job_id (str): The unique identifier of the job.

        Returns:
            Optional[JobDocument]: The job document if it exists, else None.
        """
        if not self.db:
            return None
        doc = self.db.collection("jobs").document(job_id).get()
        if doc.exists:
            return JobDocument.model_validate(doc.to_dict())
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

    def consume_budget(
        self, job_id: str, required_tokens: int = 50000
    ) -> tuple[bool, int]:
        """
        Proactively checks if the global token bucket has enough tokens.
        If sufficient, deducts them transactionally and returns (True, 0).
        If insufficient, returns (False, seconds_until_reset), signaling the worker to yield.

        Args:
            job_id: The job context.
            required_tokens: Expected complexity of the next operation.

        Returns:
            tuple[bool, int]: (True, 0) if safe to proceed, (False, seconds_until_reset) if rate limited.
        """
        import datetime

        if not self.db:
            return True, 0  # Allow pass-through for local dev without Firestore

        bucket_ref = (
            self.db.collection("jobs")
            .document(job_id)
            .collection("state")
            .document("complexity_bucket")
        )

        @firestore.transactional
        def update_in_transaction(transaction, ref):
            snapshot = ref.get(transaction=transaction)

            # Default to full budget if not initialized
            current_tokens = 5000000
            last_reset = datetime.datetime.now(datetime.UTC)

            if snapshot.exists:
                data = snapshot.to_dict()
                current_tokens = data.get("remaining_tokens", 5000000)
                # We store naive datetimes in Firestore, so we need to handle them carefully
                last_reset_val = data.get("last_reset")
                if last_reset_val:
                    # Firestore handles the parsing usually, but just in case
                    if isinstance(last_reset_val, str):
                        last_reset = datetime.datetime.fromisoformat(last_reset_val)
                    else:
                        last_reset = last_reset_val

                # If more than 60 seconds have passed since last reset, refill the bucket
                elapsed = (
                    datetime.datetime.now(datetime.UTC) - last_reset
                ).total_seconds()
                if elapsed > 60:
                    current_tokens = 5000000
                    last_reset = datetime.datetime.now(datetime.UTC)

            if current_tokens >= required_tokens:
                # Deduct and allow
                transaction.set(
                    ref,
                    {
                        "remaining_tokens": current_tokens - required_tokens,
                        "last_reset": last_reset,
                    },
                )
                return True, 0
            else:
                # Reject, calculate how many seconds until the 60s window expires
                elapsed = (
                    datetime.datetime.now(datetime.UTC) - last_reset
                ).total_seconds()
                retry_in = max(1, int(60 - elapsed))
                return False, retry_in

        return update_in_transaction(self.db.transaction(), bucket_ref)

    def sync_budget(
        self, job_id: str, actual_remaining: int, reset_in_seconds: int
    ) -> None:
        """
        Reactively syncs the token bucket with the exact numbers returned by Monday API.

        Args:
            job_id: The job context.
            actual_remaining: The exact remaining complexity points.
            reset_in_seconds: The exact seconds until the next refill.
        """
        import datetime

        if not self.db:
            return

        bucket_ref = (
            self.db.collection("jobs")
            .document(job_id)
            .collection("state")
            .document("complexity_bucket")
        )

        # Calculate when this specific budget will expire
        last_reset = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            seconds=(60 - reset_in_seconds)
        )

        bucket_ref.set({"remaining_tokens": actual_remaining, "last_reset": last_reset})

    def initialize_dag_state(self, job_id: str, dag: MigrationDag) -> None:
        """
        Initializes the tracking state for a DAG execution to support stage gating.

        Args:
            job_id: The job context.
            dag: The parsed DAG of tasks.
        """
        if not self.db:
            return

        batch = self.db.batch()
        for stage in ["workspaces", "boards", "groups", "columns", "items"]:
            tasks = getattr(dag, stage)
            if not tasks:
                continue
            stage_ref = (
                self.db.collection("jobs")
                .document(job_id)
                .collection("dag_state")
                .document(stage)
            )
            batch.set(
                stage_ref,
                {"total_tasks": len(tasks), "completed_tasks": 0, "status": "pending"},
            )
        batch.commit()

    def mark_task_complete(self, job_id: str, stage: str) -> bool:
        """
        Increments the completion counter for a stage and returns True if the stage is fully complete.

        Args:
            job_id: The job context.
            stage: The stage that completed a task (e.g. 'workspaces').

        Returns:
            bool: True if this task completion finished the entire stage.
        """
        if not self.db:
            return False

        stage_ref = (
            self.db.collection("jobs")
            .document(job_id)
            .collection("dag_state")
            .document(stage)
        )

        @firestore.transactional
        def update_and_check(transaction, ref):
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                return False

            data = snapshot.to_dict()
            completed = data.get("completed_tasks", 0) + 1
            total = data.get("total_tasks", 1)

            updates = {"completed_tasks": completed}
            is_done = False

            if completed >= total:
                updates["status"] = "completed"
                is_done = True

            transaction.update(ref, updates)
            return is_done

        return update_and_check(self.db.transaction(), stage_ref)
