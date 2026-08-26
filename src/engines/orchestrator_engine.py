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

        # Phase 3: Enqueue only the first valid stage to kick off the DAG
        for stage in self.stage_order:
            tasks = dag.get(stage, [])
            if tasks:
                logger.info(
                    f"Kicking off DAG for job {job_id} by enqueueing {len(tasks)} tasks to stage '{stage}'."
                )
                self._enqueue_stage(job_id, stage, tasks)
                break  # Only start the first non-empty stage to enforce DAG dependency order

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
