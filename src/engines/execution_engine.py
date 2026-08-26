import logging
from typing import Any

from src.core.monday_client import MondayClient
from src.core.state import StateManager

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Executes actual GraphQL mutations against the destination Monday.com account.
    """

    def __init__(self, client: MondayClient, state_manager: StateManager, job_id: str):
        """
        Initializes the ExecutionEngine.

        Args:
            client: The configured Monday.com API client for the destination account.
            state_manager: The state manager for tracking idempotency mappings.
            job_id: The ID of the current migration job.
        """
        self.client = client
        self.state_manager = state_manager
        self.job_id = job_id

    def _sync_complexity(self, response: dict[str, Any]) -> None:
        """Helper to extract complexity metadata and sync the StateManager token bucket."""
        meta = response.get("_meta_complexity")
        if meta:
            after = meta.get("after", 0)
            reset_in = meta.get("reset_in_x_seconds", 60)
            self.state_manager.sync_budget(self.job_id, after, reset_in)

    async def execute(
        self, entity_type: str, source_id: str, payload: dict[str, Any]
    ) -> str:
        """
        Routes the execution based on entity_type and executes the corresponding mutation.

        Args:
            entity_type: The type of the entity (workspace, board, group, column, item).
            source_id: The ID of the entity in the source account.
            payload: The dictionary representing the source entity data.

        Returns:
            str: The destination ID of the newly created entity.
        """
        match entity_type:
            case "workspace":
                return await self.create_workspace(source_id, payload)
            case "board":
                return await self.create_board(source_id, payload)
            case "group":
                return await self.create_group(source_id, payload)
            case "column":
                return await self.create_column(source_id, payload)
            case "item":
                return await self.create_item(source_id, payload)
            case _:
                raise ValueError(
                    f"Unsupported entity_type for execution: {entity_type}"
                )

    async def create_workspace(self, source_id: str, payload: dict[str, Any]) -> str:
        name = payload.get("name", f"Migrated Workspace {source_id}")
        # Monday API requires 'open' or 'closed' for workspace kind. Defaults to 'open'.
        kind = "open"

        query = """
        mutation($name: String!, $kind: WorkspaceKind!) {
            create_workspace(name: $name, kind: $kind) {
                id
            }
        }
        """
        variables = {"name": name, "kind": kind}

        response = await self.client.execute_query(
            query=query,
            variables=variables,
            idempotency_key=f"workspace_{source_id}",
            distributed=True,
        )
        self._sync_complexity(response)
        dest_id = str(response["data"]["create_workspace"]["id"])
        self.state_manager.set_dest_id(self.job_id, "workspace", source_id, dest_id)
        return dest_id

    async def create_board(self, source_id: str, payload: dict[str, Any]) -> str:
        name = payload.get("name", f"Migrated Board {source_id}")
        board_kind = payload.get("board_kind", "public")

        # If payload had a workspace_id, we would map it:
        # source_ws_id = payload.get("workspace_id")
        # dest_ws_id = self.state_manager.get_dest_id(self.job_id, "workspace", source_ws_id)

        query = """
        mutation($name: String!, $kind: BoardKind!) {
            create_board(board_name: $name, board_kind: $kind) {
                id
            }
        }
        """
        variables = {"name": name, "kind": board_kind}

        response = await self.client.execute_query(
            query=query,
            variables=variables,
            idempotency_key=f"board_{source_id}",
            distributed=True,
        )
        self._sync_complexity(response)
        dest_id = str(response["data"]["create_board"]["id"])
        self.state_manager.set_dest_id(self.job_id, "board", source_id, dest_id)
        return dest_id

    async def create_group(self, source_id: str, payload: dict[str, Any]) -> str:
        title = payload.get("title", f"Group {source_id}")
        source_board_id = str(payload.get("parent_board_id"))

        dest_board_id = self.state_manager.get_dest_id(
            self.job_id, "board", source_board_id
        )
        if not dest_board_id:
            raise ValueError(
                f"Cannot create group. Destination board ID not found for source board {source_board_id}"
            )

        query = """
        mutation($boardId: ID!, $groupName: String!) {
            create_group(board_id: $boardId, group_name: $groupName) {
                id
            }
        }
        """
        variables = {"boardId": dest_board_id, "groupName": title}

        response = await self.client.execute_query(
            query=query,
            variables=variables,
            idempotency_key=f"group_{source_id}",
            distributed=True,
        )
        self._sync_complexity(response)
        dest_id = str(response["data"]["create_group"]["id"])
        self.state_manager.set_dest_id(self.job_id, "group", source_id, dest_id)
        return dest_id

    async def create_column(self, source_id: str, payload: dict[str, Any]) -> str:
        title = payload.get("title", f"Column {source_id}")
        col_type = payload.get("type", "text")
        source_board_id = str(payload.get("parent_board_id"))

        dest_board_id = self.state_manager.get_dest_id(
            self.job_id, "board", source_board_id
        )
        if not dest_board_id:
            raise ValueError(
                f"Cannot create column. Destination board ID not found for source board {source_board_id}"
            )

        # Simplification: many complex column types require specific settings/creation flows.
        # This acts as the baseline mapping.
        query = """
        mutation($boardId: ID!, $title: String!, $columnType: ColumnType!) {
            create_column(board_id: $boardId, title: $title, column_type: $columnType) {
                id
            }
        }
        """
        variables = {"boardId": dest_board_id, "title": title, "columnType": col_type}

        response = await self.client.execute_query(
            query=query,
            variables=variables,
            idempotency_key=f"column_{source_id}",
            distributed=True,
        )
        self._sync_complexity(response)
        dest_id = str(response["data"]["create_column"]["id"])
        self.state_manager.set_dest_id(self.job_id, "column", source_id, dest_id)
        return dest_id

    async def create_item(self, source_id: str, payload: dict[str, Any]) -> str:
        name = payload.get("name", f"Item {source_id}")
        source_board_id = str(payload.get("parent_board_id"))

        # In the discovery engine, items have a nested group dict: 'group': {'id': '...'}
        source_group_id = payload.get("group", {}).get("id")

        dest_board_id = self.state_manager.get_dest_id(
            self.job_id, "board", source_board_id
        )
        if not dest_board_id:
            raise ValueError(
                f"Cannot create item. Destination board ID not found for source board {source_board_id}"
            )

        variables = {"boardId": dest_board_id, "itemName": name}

        # If group is present and mapped, create the item inside the group
        query = """
        mutation($boardId: ID!, $groupId: String, $itemName: String!) {
            create_item(board_id: $boardId, group_id: $groupId, item_name: $itemName) {
                id
            }
        }
        """
        if source_group_id:
            dest_group_id = self.state_manager.get_dest_id(
                self.job_id, "group", source_group_id
            )
            if dest_group_id:
                variables["groupId"] = dest_group_id

        response = await self.client.execute_query(
            query=query,
            variables=variables,
            idempotency_key=f"item_{source_id}",
            distributed=True,
        )
        self._sync_complexity(response)
        dest_id = str(response["data"]["create_item"]["id"])
        self.state_manager.set_dest_id(self.job_id, "item", source_id, dest_id)
        return dest_id
