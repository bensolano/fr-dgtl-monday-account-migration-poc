import json
import logging
import os
from typing import Any

try:
    from google.cloud import tasks_v2
except ImportError:
    tasks_v2 = None

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "local-dev-project")
REGION = os.environ.get("REGION", "europe-west1")
# For local dev, we might mock this or skip.
SERVICE_URL = os.environ.get("SERVICE_URL", "https://example.com")


class OrchestratorEngine:
    """
    Builds a Directed Acyclic Graph (DAG) for execution from a classified inventory.
    Respects the strict Monday.com dependency order:
    Workspace -> Board -> Group -> Column -> Item
    """

    def __init__(self, project_id: str = PROJECT_ID, region: str = REGION):
        """Initializes the OrchestratorEngine."""
        self.project_id = project_id
        self.region = region
        self.stage_order = ["workspaces", "boards", "groups", "columns", "items"]
        try:
            self.tasks_client = tasks_v2.CloudTasksClient() if tasks_v2 else None
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not init Cloud Tasks client: {e}")
            self.tasks_client = None

    def build_dag(
        self, inventory: dict[str, list[Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Parses a classified inventory and returns a DAG organized by execution stage.
        Filters out items marked as 'manual_only'.

        Args:
            inventory (Dict[str, List[Any]]): The classified inventory from ClassificationEngine.

        Returns:
            Dict[str, List[Dict[str, Any]]]: A dictionary where keys are stage names (e.g. 'workspaces', 'boards')
                                             and values are lists of task payloads.
        """
        dag = {stage: [] for stage in self.stage_order}

        for stage in self.stage_order:
            entities = inventory.get(stage, [])
            for entity in entities:
                # Skip entities that cannot be created via API
                if entity.get("classification") == "manual_only":
                    logger.debug(
                        f"Skipping {stage} ID {entity.get('id')} due to 'manual_only' classification."
                    )
                    continue

                # Build standard task payload
                task = {
                    "entity_type": stage.rstrip("s"),  # e.g. workspaces -> workspace
                    "source_id": str(entity.get("id")),
                    "payload": entity,
                }
                dag[stage].append(task)

        logger.info(
            f"Built DAG with {sum(len(tasks) for tasks in dag.values())} total tasks across {len(self.stage_order)} stages."
        )
        return dag

    def enqueue_dag(self, job_id: str, dag: dict[str, list[dict[str, Any]]]) -> None:
        """
        Enqueues the first stage of the DAG to Cloud Tasks.
        In a full implementation, subsequent stages are gated via Pub/Sub or status listeners.

        Args:
            job_id: The job ID to pass to task handlers.
            dag: The parsed DAG of tasks.
        """
        if not self.tasks_client:
            logger.warning("Cloud Tasks client not available. Cannot enqueue tasks.")
            return

        # Initialize DAG state counters in Firestore
        from src.core.state import StateManager

        state_manager = StateManager(self.project_id)
        state_manager.initialize_dag_state(job_id, dag)

        # Upload the DAG to GCS so workers can access it for the next stages
        from google.cloud import storage

        storage_client = storage.Client(project=self.project_id)
        bucket_name = os.environ.get("REPORTS_BUCKET", "local-dev-reports-bucket")
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(f"reports/{job_id}/dag.json")
        blob.upload_from_string(json.dumps(dag), content_type="application/json")
        logger.info(f"Saved DAG for job {job_id} to GCS.")

        # Phase 3: Enqueue only the first valid stage to kick off the DAG
        self.enqueue_next_stage(job_id, current_stage=None)

    def enqueue_next_stage(self, job_id: str, current_stage: str | None = None) -> None:
        """
        Enqueues the next valid stage of the DAG after the current stage completes.

        Args:
            job_id: The job ID.
            current_stage: The stage that just finished (None if starting).
        """
        if not self.tasks_client:
            return

        # Download the DAG from GCS
        from google.cloud import storage

        storage_client = storage.Client(project=self.project_id)
        bucket_name = os.environ.get("REPORTS_BUCKET", "local-dev-reports-bucket")
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(f"reports/{job_id}/dag.json")

        if not blob.exists():
            logger.error(
                f"Cannot enqueue next stage for {job_id}. DAG not found in GCS."
            )
            return

        dag = json.loads(blob.download_as_string())

        # Find the next stage in the order
        start_idx = 0
        if current_stage:
            try:
                start_idx = self.stage_order.index(current_stage) + 1
            except ValueError:
                logger.error(f"Unknown stage {current_stage} completed.")
                return

        for i in range(start_idx, len(self.stage_order)):
            stage = self.stage_order[i]
            tasks = dag.get(stage, [])
            if tasks:
                logger.info(
                    f"Enqueuing next DAG stage: '{stage}' with {len(tasks)} tasks."
                )
                self._enqueue_stage(job_id, stage, tasks)
                return

        # If we reach here, the DAG is entirely complete.
        from src.engines.job_engine import set_job_status

        set_job_status(job_id, "MIGRATION_COMPLETED")
        logger.info(f"DAG Execution completely finished for job {job_id}.")

    def _enqueue_stage(
        self, job_id: str, stage: str, tasks: list[dict[str, Any]]
    ) -> None:
        """Helper to enqueue a list of tasks to a specific Cloud Tasks queue."""
        if not self.tasks_client:
            return

        queue_name = f"migration-{stage}"
        parent = self.tasks_client.queue_path(self.project_id, self.region, queue_name)

        for t in tasks:
            # Construct the HTTP POST task targeting our own API (the worker)
            payload_bytes = json.dumps({"job_id": job_id, "task": t}).encode("utf-8")

            task_def = {
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": f"{SERVICE_URL}/api/v1/worker/{stage}",
                    "headers": {"Content-type": "application/json"},
                    "body": payload_bytes,
                }
            }

            try:
                self.tasks_client.create_task(
                    request={"parent": parent, "task": task_def}
                )
            except Exception as e:  # noqa: BLE001
                logger.error(
                    f"Failed to enqueue task {t['source_id']} for {stage}: {e}"
                )
