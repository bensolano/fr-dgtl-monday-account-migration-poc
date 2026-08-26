import logging
from typing import Any

logger = logging.getLogger(__name__)


class OrchestratorEngine:
    """
    Builds a Directed Acyclic Graph (DAG) for execution from a classified inventory.
    Respects the strict Monday.com dependency order:
    Workspace -> Board -> Group -> Column -> Item
    """

    def __init__(self):
        """Initializes the OrchestratorEngine."""
        self.stage_order = ["workspaces", "boards", "groups", "columns", "items"]

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
