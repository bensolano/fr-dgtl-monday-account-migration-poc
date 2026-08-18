import json
import logging
from typing import Any

from src.monday_client import MondayClient

logger = logging.getLogger(__name__)


class DiscoveryEngine:
    def __init__(self, client: MondayClient):
        """
        Initializes the DiscoveryEngine.

        Args:
            client (MondayClient): The initialized Monday.com API client.
        """
        self.client = client

    async def get_workspaces(self) -> list[dict[str, Any]]:
        """
        Fetch all workspaces in the account.

        Returns:
            list[dict[str, Any]]: A list of dictionaries, each representing a workspace.
        """
        query = """
        query {
          workspaces {
            id
            name
            state
          }
        }
        """
        response = await self.client.execute_query(query)
        return response.get("data", {}).get("workspaces", [])

    async def get_boards(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch all boards, handling pagination."""
        query_first = """
        query ($workspaceId: [String!]) {
          boards(workspace_ids: $workspaceId, limit: 500) {
            id
            name
            type
            board_kind
          }
        }
        """
        # The boards query doesn't strictly support cursor pagination the same way items do
        # based on standard Monday API, but standard limit/page is often used.
        # For simplicity and given the 500 limit, we assume this is often sufficient,
        # but in a production setup, we'd use page/limit for boards if cursors aren't supported.
        # According to Monday docs, cursor pagination is primary for items/subitems.

        variables = {"workspaceId": [workspace_id]} if workspace_id else {}
        response = await self.client.execute_query(query_first, variables)
        return response.get("data", {}).get("boards", [])

    async def get_groups(self, board_id: str) -> list[dict[str, Any]]:
        """
        Fetch groups for a specific board.

        Args:
            board_id (str): The ID of the board to fetch groups for.

        Returns:
            list[dict[str, Any]]: A list of dictionaries, each representing a group on the board.
        """
        query = """
        query ($boardId: [ID!]) {
          boards(ids: $boardId) {
            groups {
              id
              title
            }
          }
        }
        """
        variables = {"boardId": [board_id]}
        response = await self.client.execute_query(query, variables)
        try:
            return response["data"]["boards"][0].get("groups", [])
        except (KeyError, IndexError):
            return []

    async def get_columns(self, board_id: str) -> list[dict[str, Any]]:
        """
        Fetch column definitions for a specific board.

        Args:
            board_id (str): The ID of the board to fetch columns for.

        Returns:
            list[dict[str, Any]]: A list of dictionaries, each representing a column definition.
        """
        query = """
        query ($boardId: [ID!]) {
          boards(ids: $boardId) {
            columns {
              id
              title
              type
              settings_str
            }
          }
        }
        """
        variables = {"boardId": [board_id]}
        response = await self.client.execute_query(query, variables)
        try:
            return response["data"]["boards"][0].get("columns", [])
        except (KeyError, IndexError):
            return []

    async def get_items(self, board_id: str) -> list[dict[str, Any]]:
        """
        Fetch all items from a board, automatically handling cursor pagination.

        Args:
            board_id (str): The ID of the board to fetch items from.

        Returns:
            list[dict[str, Any]]: A list of all items on the board.
        """
        query_first = """
        query ($boardId: [ID!]) {
          boards(ids: $boardId) {
            items_page(limit: 500) {
              cursor
              items {
                  id
                  name
                  group {
                      id
                  }
              }
            }
          }
        }
        """
        query_next = """
        query ($cursor: String!) {
          next_items_page(limit: 500, cursor: $cursor) {
            cursor
            items {
              id
              name
              group {
                  id
              }
            }
          }
        }
        """
        all_items = []
        variables = {"boardId": [board_id]}

        # Initial Fetch
        response = await self.client.execute_query(query_first, variables)
        try:
            items_page = response["data"]["boards"][0]["items_page"]
            all_items.extend(items_page.get("items", []))
            cursor = items_page.get("cursor")
        except (KeyError, IndexError):
            return []

        # Paginate
        while cursor:
            variables = {"cursor": cursor}
            response = await self.client.execute_query(query_next, variables)
            try:
                items_page = response["data"]["next_items_page"]
                all_items.extend(items_page.get("items", []))
                cursor = items_page.get("cursor")
            except KeyError:
                break

        return all_items

    async def discover_full_account(
        self, output_path: str = "local_inventory.json"
    ) -> dict[str, list]:
        """
        Orchestrates a full account discovery, mapping dependencies and saving state locally.

        Args:
            output_path (str, optional): The path to save the local JSON inventory file. Defaults to "local_inventory.json".

        Returns:
            dict[str, list]: A dictionary containing all discovered workspaces, boards, groups, columns, and items.
        """
        logger.info("Starting Account Discovery...")
        inventory = {
            "workspaces": [],
            "boards": [],
            "groups": [],
            "columns": [],
            "items": [],
        }

        # 1. Workspaces
        workspaces = await self.get_workspaces()
        inventory["workspaces"] = workspaces

        # 2. Boards
        boards = await self.get_boards()
        inventory["boards"] = boards

        for board in boards:
            board_id = board["id"]
            logger.info(f"Discovering board: {board_id}")

            # 3. Groups
            groups = await self.get_groups(board_id)
            for group in groups:
                group["parent_board_id"] = board_id
            inventory["groups"].extend(groups)

            # 4. Columns
            columns = await self.get_columns(board_id)
            for column in columns:
                column["parent_board_id"] = board_id
            inventory["columns"].extend(columns)

            # 5. Items (Paginated)
            items = await self.get_items(board_id)
            for item in items:
                item["parent_board_id"] = board_id
            inventory["items"].extend(items)

        # Save locally
        with open(output_path, "w", encoding="utf-8") as f:  # noqa: ASYNC230
            json.dump(inventory, f, indent=2)

        logger.info(
            f"Discovery complete. Saved {len(inventory['boards'])} boards and {len(inventory['items'])} items to {output_path}"
        )
        return inventory
