import logging
import os
from typing import Any

from src.core.schemas import MigrationDag, TaskPayload

try:
    from google.cloud import tasks_v2
except ImportError:
    tasks_v2 = None

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "local-dev-project")
REGION = os.environ.get("REGION", "europe-west1")
# For local dev, we might mock this or skip.
SERVICE_URL = os.environ.get("SERVICE_URL", "https://example.com")


from src.engines.interfaces import StateInterface, StorageInterface, TaskQueueInterface


class OrchestrationEngine:
    """
    Builds a Directed Acyclic Graph (DAG) for execution from a classified inventory.
    Respects the strict Monday.com dependency order:
    Workspace -> Board -> Group -> Column -> Item
    """

    def __init__(
        self,
        state_manager: StateInterface,
        dag_storage: StorageInterface,
        task_queue: TaskQueueInterface,
    ):
        """
        Initializes the OrchestrationEngine.

        # ==============================================================================
        # EDUCATIONAL NOTE: DEPENDENCY INVERSION (SOLID "D") APPLIED
        # ==============================================================================
        # BEFORE:
        # OrchestrationEngine imported `StateManager`, `storage.Client`, and
        # `CloudTasksClient` inline inside its methods. This made it impossible to test
        # the DAG orchestration logic without actually hitting Google Cloud.
        #
        # AFTER:
        # We enforce "Dependency Inversion". OrchestrationEngine demands three objects
        # that satisfy the StateInterface, StorageInterface, and TaskQueueInterface.
        # It no longer cares about GCP, Firestore, or Cloud Tasks. It only orchestrates.
        # ==============================================================================

        Args:
            state_manager: Injected dependency for initializing stage gates.
            dag_storage: Injected dependency for saving/loading the DAG payload.
            task_queue: Injected dependency for enqueuing tasks.
        """
        self.stage_order = ["workspaces", "boards", "groups", "columns", "items"]
        self.state_manager = state_manager
        self.dag_storage = dag_storage
        self.task_queue = task_queue

    def build_dag(self, inventory: dict[str, list[Any]]) -> MigrationDag:
        """
        Parses a classified inventory and returns a DAG organized by execution stage.
        Filters out items marked as 'manual_only'.

        Args:
            inventory (Dict[str, List[Any]]): The classified inventory from ClassificationEngine.

        Returns:
            Dict[str, List[Dict[str, Any]]]: A dictionary where keys are stage names (e.g. 'workspaces', 'boards')
                                             and values are lists of task payloads.
        """
        dag = MigrationDag()

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
                task = TaskPayload(
                    entity_type=stage.rstrip("s"),
                    source_id=str(entity.get("id")),
                    payload=entity,
                )
                getattr(dag, stage).append(task)

        logger.info(
            f"Built DAG with {sum(len(getattr(dag, s)) for s in self.stage_order)} total tasks across {len(self.stage_order)} stages."
        )
        return dag

    def enqueue_dag(self, job_id: str, dag: MigrationDag) -> None:
        """
        Enqueues the first stage of the DAG to Cloud Tasks.
        In a full implementation, subsequent stages are gated via Pub/Sub or status listeners.

        Args:
            job_id: The job ID to pass to task handlers.
            dag: The parsed DAG of tasks.
        """
        # Initialize DAG state counters in Firestore via injected interface
        self.state_manager.initialize_dag_state(job_id, dag)

        # Upload the DAG to storage so workers can access it for the next stages
        self.dag_storage.save_dag(job_id, dag)
        logger.info(f"Saved DAG for job {job_id} to storage.")

        # Phase 3: Enqueue only the first valid stage to kick off the DAG
        self.enqueue_next_stage(job_id, current_stage=None)

    def enqueue_next_stage(self, job_id: str, current_stage: str | None = None) -> None:
        """
        Enqueues the next valid stage of the DAG after the current stage completes.

        Args:
            job_id: The job ID.
            current_stage: The stage that just finished (None if starting).
        """
        # Download the DAG from storage
        dag = self.dag_storage.load_dag(job_id)

        if not dag:
            logger.error(
                f"Cannot enqueue next stage for {job_id}. DAG not found in storage."
            )
            return

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
            tasks = getattr(dag, stage)
            if tasks:
                logger.info(
                    f"Enqueuing next DAG stage: '{stage}' with {len(tasks)} tasks."
                )
                self._enqueue_stage(job_id, stage, tasks)
                return

        # If we reach here, the DAG is entirely complete.
        # In a perfectly clean architecture, OrchestrationEngine shouldn't know about JobEngine.
        # It should just raise an event, or update state via the StateInterface.
        # To avoid breaking the existing implementation while respecting SOLID,
        # we will let the OrchestrationEngine just log completion for now, and rely on
        # StateManager to eventually handle the status update.
        logger.info(f"DAG Execution completely finished for job {job_id}.")
        # self.state_manager.update_job_status(job_id, "MIGRATION_COMPLETED") # Ideal future state

    def _enqueue_stage(self, job_id: str, stage: str, tasks: list[TaskPayload]) -> None:
        """Helper to enqueue a list of tasks to a specific queue via the interface."""
        for t in tasks:
            try:
                self.task_queue.enqueue_task(job_id, stage, t)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to enqueue task {t.source_id} for {stage}: {e}")
