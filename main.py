import argparse
import asyncio
import logging
import os
import sys

from src.core.monday_client import MondayClient
from src.engines.classification_engine import ClassificationEngine
from src.engines.discovery_engine import DiscoveryEngine
from src.engines.job_engine import JobEngine
from src.engines.report_engine import ReportEngine

# Configure standard logging to output to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def default_discovery_factory(api_key: str) -> DiscoveryEngine:
    """Factory function to build a DiscoveryEngine with a dynamic API key."""
    client = MondayClient(api_key=api_key)
    return DiscoveryEngine(client=client)


async def main() -> None:
    """
    Main execution flow for the dedicated Cloud Run Job.
    Expects JOB_ID to be passed via environment variable (in production)
    or via CLI argument (for local testing).
    """
    parser = argparse.ArgumentParser(
        description="Monday.com Migration Cloud Run Job Entrypoint"
    )
    parser.add_argument(
        "--job-id",
        type=str,
        help="The unique ID of the job to process.",
    )
    args = parser.parse_args()

    # Cloud Run Jobs typically inject environment variables
    job_id = args.job_id or os.environ.get("JOB_ID")

    if not job_id:
        logger.error(
            "No JOB_ID provided. Must be passed via --job-id or JOB_ID environment variable."
        )
        sys.exit(1)

    logger.info(f"--- BATCH JOB STARTED FOR JOB_ID: {job_id} ---")
    engine = JobEngine(
        classifier=ClassificationEngine(),
        reporter=ReportEngine(),
        discovery_factory=default_discovery_factory,
    )
    await engine.execute_discovery_job(job_id)
    logger.info("--- BATCH JOB FINISHED ---")


if __name__ == "__main__":
    asyncio.run(main())
