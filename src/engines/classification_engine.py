import logging
from typing import Any

logger = logging.getLogger(__name__)


class ClassificationEngine:
    """
    Evaluates discovered Monday.com objects against the capability matrix
    to determine their migration path: 'full', 'partial', or 'manual_only'.
    """

    def classify_workspace(self, workspace: dict[str, Any]) -> dict[str, Any]:
        """
        Classifies a workspace object.

        Args:
            workspace (dict[str, Any]): The workspace dictionary.

        Returns:
            dict[str, Any]: A dictionary containing 'classification' and 'caveat'.
        """
        return {
            "classification": "full",
            "caveat": None,
        }

    def classify_board(self, board: dict[str, Any]) -> dict[str, Any]:
        """
        Classifies a board object.

        Args:
            board (dict[str, Any]): The board dictionary.

        Returns:
            dict[str, Any]: A dictionary containing 'classification' and 'caveat'.
        """
        if board.get("board_kind") == "share":
            # Just an example logic hook: some shared boards might have specific caveats.
            return {
                "classification": "full",
                "caveat": "Board kind 'share' cannot be explicitly created via API; will be created as a standard board.",
            }

        return {
            "classification": "full",
            "caveat": None,
        }

    def classify_group(self, group: dict[str, Any]) -> dict[str, Any]:
        """
        Classifies a group object.

        Args:
            group (dict[str, Any]): The group dictionary.

        Returns:
            dict[str, Any]: A dictionary containing 'classification' and 'caveat'.
        """
        return {
            "classification": "full",
            "caveat": None,
        }

    def classify_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """
        Classifies an item object.

        Args:
            item (dict[str, Any]): The item dictionary.

        Returns:
            dict[str, Any]: A dictionary containing 'classification' and 'caveat'.
        """
        return {
            "classification": "full",
            "caveat": None,
        }

    def classify_column(self, column: dict[str, Any]) -> dict[str, Any]:
        """
        Classifies a column based on its type and settings against the capability matrix.

        Args:
            column (dict[str, Any]): The column dictionary.

        Returns:
            dict[str, Any]: A dictionary containing 'classification' and 'caveat'.
        """
        col_type = column.get("type", "")

        if col_type == "formula":
            return {
                "classification": "partial",
                "caveat": "Formula can be recreated, but cross-board dependencies must be migrated first.",
            }

        if col_type in ("board_relation", "mirror"):
            return {
                "classification": "partial",
                "caveat": f"Column type '{col_type}' requires the connected board to be migrated first. Values mapped post-creation.",
            }

        if col_type == "dependency":
            return {
                "classification": "manual_only",
                "caveat": "Dependency columns often lack full write support via API for complex configurations.",
            }

        return {
            "classification": "full",
            "caveat": None,
        }

    def process_inventory(self, inventory: dict[str, list]) -> dict[str, list]:
        """
        Iterates over a full discovery inventory, mutating each object to append
        its classification and caveat.

        Args:
            inventory (dict[str, list]): The dictionary of discovered objects (workspaces, boards, etc.).

        Returns:
            dict[str, list]: The mutated inventory with classifications appended.
        """
        logger.info("Starting inventory classification...")

        for ws in inventory.get("workspaces", []):
            ws.update(self.classify_workspace(ws))

        for board in inventory.get("boards", []):
            board.update(self.classify_board(board))

        for group in inventory.get("groups", []):
            group.update(self.classify_group(group))

        for col in inventory.get("columns", []):
            col.update(self.classify_column(col))

        for item in inventory.get("items", []):
            item.update(self.classify_item(item))

        logger.info("Classification complete.")
        return inventory
