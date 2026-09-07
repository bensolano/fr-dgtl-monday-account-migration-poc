import logging
from typing import Any

from src.domain.interfaces import StateInterface
from src.infrastructure.monday.client import MondayClient

logger = logging.getLogger(__name__)


class ExecutionService:
    """
    Executes actual GraphQL mutations against the destination Monday.com account.
    """

    def __init__(
        self, client: MondayClient, state_manager: StateInterface, job_id: str
    ):
        """
        Initializes the ExecutionService.

        Args:
            client: The configured Monday.com API client for the destination account.
            state_manager: The state manager interface for tracking idempotency mappings.
            job_id: The ID of the current migration job.
        """
        self.client = client
        self.state_manager = state_manager
        self.job_id = job_id

    async def _sync_complexity(self, response: dict[str, Any]) -> None:
        """Helper to extract complexity metadata and sync the StateManager token bucket."""
        meta = response.get("_meta_complexity")
        if meta:
            after = meta.get("after", 0)
            reset_in = meta.get("reset_in_x_seconds", 60)
            await self.state_manager.sync_budget(self.job_id, after, reset_in)

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
        await self._sync_complexity(response)
        dest_id = str(response["data"]["create_workspace"]["id"])
        await self.state_manager.set_dest_id(
            self.job_id, "workspace", source_id, dest_id
        )
        return dest_id

    async def create_board(self, source_id: str, payload: dict[str, Any]) -> str:
        name = payload.get("name", f"Migrated Board {source_id}")
        board_kind = payload.get("board_kind", "public")

        # Map workspace if available
        dest_ws_id = None
        source_ws_id = (
            payload.get("workspace", {}).get("id") if payload.get("workspace") else None
        )
        if source_ws_id:
            dest_ws_id = await self.state_manager.get_dest_id(
                self.job_id, "workspace", str(source_ws_id)
            )

        query = """
        mutation($name: String!, $kind: BoardKind!, $workspaceId: ID) {
            create_board(board_name: $name, board_kind: $kind, workspace_id: $workspaceId) {
                id
            }
        }
        """
        variables = {"name": name, "kind": board_kind}
        if dest_ws_id:
            variables["workspaceId"] = dest_ws_id

        response = await self.client.execute_query(
            query=query,
            variables=variables,
            idempotency_key=f"board_{source_id}",
            distributed=True,
        )
        await self._sync_complexity(response)
        dest_id = str(response["data"]["create_board"]["id"])
        await self.state_manager.set_dest_id(self.job_id, "board", source_id, dest_id)
        return dest_id

    async def create_group(self, source_id: str, payload: dict[str, Any]) -> str:
        title = payload.get("title", f"Group {source_id}")
        source_board_id = str(payload.get("parent_board_id"))

        dest_board_id = await self.state_manager.get_dest_id(
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
        await self._sync_complexity(response)
        dest_id = str(response["data"]["create_group"]["id"])
        await self.state_manager.set_dest_id(self.job_id, "group", source_id, dest_id)
        return dest_id

    async def create_column(self, source_id: str, payload: dict[str, Any]) -> str:
        title = payload.get("title", f"Column {source_id}")
        col_type = payload.get("type", "text")
        source_board_id = str(payload.get("parent_board_id"))

        dest_board_id = await self.state_manager.get_dest_id(
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
        await self._sync_complexity(response)
        dest_id = str(response["data"]["create_column"]["id"])
        await self.state_manager.set_dest_id(self.job_id, "column", source_id, dest_id)
        return dest_id

    async def create_item(self, source_id: str, payload: dict[str, Any]) -> str:
        name = payload.get("name", f"Item {source_id}")
        source_board_id = str(payload.get("parent_board_id"))

        # In the discovery engine, items have a nested group dict: 'group': {'id': '...'}
        source_group_id = payload.get("group", {}).get("id")

        dest_board_id = await self.state_manager.get_dest_id(
            self.job_id, "board", source_board_id
        )
        if not dest_board_id:
            raise ValueError(
                f"Cannot create item. Destination board ID not found for source board {source_board_id}"
            )

        variables = {"boardId": dest_board_id, "itemName": name}

        # Map column values
        source_column_values = payload.get("column_values", [])
        mapped_column_values = {}
        for col in source_column_values:
            col_type = col.get("type")
            # Skip read-only columns (removed person columns from skip list to allow mapping)
            if col_type in [
                "subtasks",
                "formula",
                "creation_log",
                "last_updated",
                "board_relation",
                "lookup",
                "name",
            ]:
                continue

            raw_value = col.get("value")
            if raw_value is None and col_type not in ["person", "multiple-person"]:
                continue

            # Find the new column ID
            source_col_scoped_id = f"{source_board_id}_{col['id']}"
            dest_col_id = await self.state_manager.get_dest_id(
                self.job_id, "column", source_col_scoped_id
            )

            if dest_col_id:
                if col_type in ["person", "multiple-person"]:
                    # Monday API returns names in 'text' (e.g. "Jane Doe, John Smith")
                    names = [
                        n.strip() for n in col.get("text", "").split(",") if n.strip()
                    ]
                    persons_and_teams = []
                    for name_str in names:
                        dest_user_id = await self.state_manager.get_dest_id(
                            self.job_id, "user_name", name_str
                        )
                        if dest_user_id:
                            persons_and_teams.append(
                                {"id": int(dest_user_id), "kind": "person"}
                            )
                    if persons_and_teams:
                        mapped_column_values[dest_col_id] = {
                            "personsAndTeams": persons_and_teams
                        }
                else:
                    try:
                        import json

                        # 'value' from discovery is a JSON string. Parse it into a dictionary
                        # so that it doesn't get double-encoded when we pass $columnValues
                        mapped_column_values[dest_col_id] = json.loads(raw_value)
                    except Exception as e:  # noqa: BLE001
                        logger.debug(
                            f"Failed to parse column value for {source_col_scoped_id}: {e}"
                        )

        # If group is present and mapped, create the item inside the group
        query = """
        mutation($boardId: ID!, $groupId: String, $itemName: String!, $columnValues: JSON) {
            create_item(board_id: $boardId, group_id: $groupId, item_name: $itemName, column_values: $columnValues) {
                id
            }
        }
        """
        if source_group_id:
            scoped_group_id = f"{source_board_id}_{source_group_id}"
            dest_group_id = await self.state_manager.get_dest_id(
                self.job_id, "group", scoped_group_id
            )
            if dest_group_id:
                variables["groupId"] = dest_group_id

        if mapped_column_values:
            import json

            variables["columnValues"] = json.dumps(mapped_column_values)

        response = await self.client.execute_query(
            query=query,
            variables=variables,
            idempotency_key=f"item_{source_id}",
            distributed=True,
        )
        await self._sync_complexity(response)
        dest_id = str(response["data"]["create_item"]["id"])
        await self.state_manager.set_dest_id(self.job_id, "item", source_id, dest_id)
        return dest_id
