import logging
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    Consumes a classified Monday.com inventory and generates a human-readable
    Markdown report summarizing the migration scope and caveats.
    """

    def generate_markdown_report(
        self, inventory: dict[str, list[dict[str, Any]]]
    ) -> str:
        """
        Generates a markdown formatted report from a classified inventory.

        Args:
            inventory (dict[str, list[dict[str, Any]]]): The classified inventory dictionary.

        Returns:
            str: The fully formatted Markdown report.
        """
        logger.info("Generating Markdown report...")

        lines = [
            "# Monday.com Pre-Migration Assessment Report",
            "",
            "This report summarizes the objects discovered in the source Monday.com account and their readiness for automated migration.",
            "",
            "## 1. Executive Summary",
            "",
            "| Object Type | Total Discovered | Full Auto | Partial (w/ Caveats) | Manual Only |",
            "|---|---|---|---|---|",
        ]

        # Calculate totals
        for obj_type in ["workspaces", "boards", "groups", "columns", "items"]:
            items = inventory.get(obj_type, [])
            total = len(items)
            counts = Counter(item.get("classification", "unknown") for item in items)

            lines.append(
                f"| **{obj_type.capitalize()}** | {total} | {counts.get('full', 0)} | {counts.get('partial', 0)} | {counts.get('manual_only', 0)} |"
            )

        lines.extend(
            [
                "",
                "## 2. Caveats & Manual Interventions",
                "",
                "The following objects require special attention. They will either be partially migrated (requiring manual mapping later) or cannot be migrated via the API at all.",
                "",
            ]
        )

        # Gather caveats
        has_caveats = False
        for obj_type in ["workspaces", "boards", "groups", "columns", "items"]:
            items_with_caveats = [
                item for item in inventory.get(obj_type, []) if item.get("caveat")
            ]

            if items_with_caveats:
                has_caveats = True
                lines.append(f"### {obj_type.capitalize()}")
                for item in items_with_caveats:
                    name = item.get("name") or item.get("title") or "Unknown"
                    item_id = item.get("id", "N/A")
                    classification = item.get("classification", "unknown").upper()
                    caveat = item.get("caveat")
                    lines.append(
                        f"- **{name}** (ID: `{item_id}`) `[{classification}]`: {caveat}"
                    )
                lines.append("")

        if not has_caveats:
            lines.append(
                "No partial or manual-only objects were detected. The selected scope is 100% fully migratable."
            )

        lines.extend(
            [
                "",
                "## 3. Appendix: All Discovered Boards",
                "",
                "A complete list of boards discovered during the assessment. Use these IDs to trace exact locations in your Monday account.",
                "",
                "| Board Name | Board ID | Classification |",
                "|---|---|---|",
            ]
        )

        for board in inventory.get("boards", []):
            name = board.get("name", "Unknown")
            b_id = board.get("id", "N/A")
            cls = board.get("classification", "unknown").upper()
            lines.append(f"| {name} | `{b_id}` | {cls} |")

        lines.extend(
            [
                "",
                "---",
                "*Report generated automatically by the Monday Account Migration Tool.*",
            ]
        )

        logger.info("Markdown report generation complete.")
        return "\n".join(lines)

    def save_report(
        self, report_content: str, file_path: str = "pre_migration_report.md"
    ) -> None:
        """
        Saves the generated markdown string to a local file.

        Args:
            report_content (str): The markdown string to save.
            file_path (str, optional): The path to write the file to. Defaults to 'pre_migration_report.md'.

        Returns:
            None
        """
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        logger.info(f"Report saved to {file_path}")
