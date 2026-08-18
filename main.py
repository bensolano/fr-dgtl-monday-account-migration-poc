import argparse
import asyncio
import json
import logging
import os
import sys

from src.classification import ClassificationEngine
from src.discovery import DiscoveryEngine
from src.monday_client import MondayClient
from src.report_generator import ReportGenerator

# Configure standard logging to output to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """
    Main execution flow for local emulation of the Monday account migration assessment.

    Reads MONDAY_API_KEY from the environment, runs discovery, classifies the inventory,
    and generates a pre-migration markdown report locally.

    Returns:
        None
    """
    parser = argparse.ArgumentParser(description="Monday.com Migration Discovery Tool")
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Skip discovery and use existing local_inventory.json",
    )
    args = parser.parse_args()

    # Initialize dependencies
    classification_engine = ClassificationEngine()
    report_generator = ReportGenerator()

    # 1. Discovery
    logger.info("--- PHASE 1: DISCOVERY ---")
    if args.use_cache and os.path.exists("local_inventory.json"):
        logger.info("Loading inventory from local_inventory.json...")
        with open("local_inventory.json", "r", encoding="utf-8") as f:  # noqa: ASYNC230
            inventory = json.load(f)
    else:
        api_key = os.environ.get("MONDAY_API_KEY")
        if not api_key:
            logger.error(
                "MONDAY_API_KEY environment variable is missing. "
                "Please run: export MONDAY_API_KEY='your_token' before executing."
            )
            sys.exit(1)

        client = MondayClient(api_key=api_key)
        discovery_engine = DiscoveryEngine(client=client)

        inventory = await discovery_engine.discover_full_account(
            output_path="local_inventory.json"
        )

    # 2. Classification
    logger.info("--- PHASE 2: CLASSIFICATION ---")
    classified_inventory = classification_engine.process_inventory(inventory)

    # 3. Report Generation
    logger.info("--- PHASE 3: REPORT GENERATION ---")
    report_md = report_generator.generate_markdown_report(classified_inventory)
    report_generator.save_report(report_md, file_path="pre_migration_report.md")

    logger.info(
        "End-to-End local emulation complete. Please review 'pre_migration_report.md'."
    )


if __name__ == "__main__":
    asyncio.run(main())
