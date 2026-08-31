import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import RedirectResponse

from src.api.models import (
    ExecuteJobResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobStatusResponse,
)
from src.core import gcp
from src.core.monday_client import MondayClient
from src.core.state import StateManager
from src.core.task_deps import GCSDagStorage, get_task_queue
from src.engines.classification_engine import ClassificationEngine
from src.engines.discovery_engine import DiscoveryEngine
from src.engines.job_engine import JobEngine
from src.engines.orchestration_engine import OrchestrationEngine
from src.engines.report_engine import ReportEngine

logger = logging.getLogger(__name__)

job_router = APIRouter()

# ==============================================================================
# EDUCATIONAL NOTE: THE COMPOSITION ROOT (DEPENDENCY PROVIDER)
# ==============================================================================
# In a pure SOLID architecture, the business logic (JobEngine) knows NOTHING
# about concrete implementations.
#
# So, *someone* has to wire the concrete classes together. That is the job of the
# "Composition Root" — usually the outermost layer of the application (the Router).
#
# Here, FastAPI acts as our Composition Root. When a route asks for a `JobEngine`,
# FastAPI calls `get_job_engine()`, which instantiates the concrete classes and
# passes them to the engine.
# ==============================================================================


def default_discovery_factory(api_key: str) -> DiscoveryEngine:
    """Factory function to build a DiscoveryEngine with a dynamic API key."""
    client = MondayClient(api_key=api_key)
    return DiscoveryEngine(client=client)


def get_job_engine() -> JobEngine:
    """Dependency provider that wires concrete engines into JobEngine."""
    return JobEngine(
        classifier=ClassificationEngine(),
        reporter=ReportEngine(),
        discovery_factory=default_discovery_factory,
    )


def get_orchestration() -> OrchestrationEngine:
    """Dependency provider that wires infrastructure into OrchestrationEngine."""
    return OrchestrationEngine(
        state_manager=StateManager(),
        dag_storage=GCSDagStorage(),
        task_queue=get_task_queue(),
    )


@job_router.post("", response_model=JobCreateResponse)
async def create_job(
    request: JobCreateRequest,
    background_tasks: BackgroundTasks,
    job_engine: Annotated[JobEngine, Depends(get_job_engine)],
) -> JobCreateResponse:
    """
    Creates a new migration job, secures API keys in Secret Manager, and triggers execution.

    Args:
        request (JobCreateRequest): The request payload containing source/destination API keys.
        background_tasks (BackgroundTasks): FastAPI background tasks manager for local fallback.

    Returns:
        JobCreateResponse: The created job details including status and ID.

    Raises:
        HTTPException: If API keys fail to secure in Secret Manager.
    """
    job_id = str(uuid.uuid4())

    # Secure API Keys in Secret Manager
    try:
        gcp.store_job_secrets(job_id, request.source_api_key, request.dest_api_key)
    except Exception as e:
        logger.error(f"Failed to store secrets in Secret Manager: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to secure credentials."
        ) from e

    # Init state in Firestore
    job_engine.set_job_status(job_id, "PENDING")

    try:
        # Try to trigger PRODUCTION GCP Cloud Run Job
        triggered = gcp.trigger_cloud_run_discovery_job(job_id)
        if triggered:
            msg = "Cloud Run job triggered."
        else:
            # Fallback to local background task if env vars missing
            background_tasks.add_task(job_engine.execute_discovery_job, job_id)
            msg = "Local background task started."
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to trigger Cloud Run Job for {job_id}: {e}")
        job_engine.set_job_status(
            job_id, "FAILED", error="Failed to start background job infrastructure."
        )
        msg = "Failed to start background job infrastructure."

    return JobCreateResponse(
        job_id=job_id,
        status="PENDING",
        message=msg,
    )


@job_router.get("/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    job_engine: Annotated[JobEngine, Depends(get_job_engine)],
) -> JobStatusResponse:
    """
    Retrieves the current execution status of a specific job.

    Args:
        job_id (str): The unique identifier of the job.
        job_engine (JobEngine): Injected engine for job state.

    Returns:
        JobStatusResponse: The status payload.

    Raises:
        HTTPException: If the job cannot be found in the datastore.
    """
    job_data = job_engine.get_job(job_id)
    if not job_data:
        # Fallback logic for local testing without firestore
        if not job_engine.has_firestore():
            return JobStatusResponse(job_id=job_id, status="PENDING")
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(job_id=job_id, status=job_data.get("status", "UNKNOWN"))


@job_router.post("/{job_id}/execute", response_model=ExecuteJobResponse)
async def execute_job(
    job_id: str,
    job_engine: Annotated[JobEngine, Depends(get_job_engine)],
    orchestration: Annotated[OrchestrationEngine, Depends(get_orchestration)],
) -> ExecuteJobResponse:
    """
    Triggers the actual migration execution (Phase 3) for a previously discovered job.
    Downloads the inventory, builds the DAG, and enqueues the first stage to Cloud Tasks.

    Args:
        job_id (str): The unique identifier of the job to execute.
        job_engine (JobEngine): Injected engine for job state.
        orchestration (OrchestrationEngine): Injected DAG builder and executor.

    Returns:
        ExecuteJobResponse: Status payload.

    Raises:
        HTTPException: If the job is not ready or the inventory cannot be found.
    """
    job_data = job_engine.get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    if job_data.get("status") not in ["COMPLETED", "SCOPE_CONFIRMED"]:
        raise HTTPException(
            status_code=400,
            detail="Job must be COMPLETED (discovery done) before executing.",
        )

    try:
        inventory_data = gcp.get_inventory(job_id)

        dag = orchestration.build_dag(inventory_data)

        job_engine.set_job_status(job_id, "EXECUTING")

        orchestration.enqueue_dag(job_id, dag)

        return ExecuteJobResponse(
            status="EXECUTING",
            message="Migration DAG built and enqueued to Cloud Tasks.",
        )

    except Exception as e:
        logger.error(f"Failed to execute DAG for job {job_id}: {e}")
        job_engine.set_job_status(job_id, "FAILED", error=str(e))
        raise HTTPException(
            status_code=500, detail="Failed to start migration execution."
        ) from e


@job_router.get("/{job_id}/report", response_model=None)
async def get_job_report(
    job_id: str,
    job_engine: Annotated[JobEngine, Depends(get_job_engine)],
) -> RedirectResponse | Any:
    """
    Generates a secure download link for the completed migration report.

    Args:
        job_id (str): The unique identifier of the job.
        job_engine (JobEngine): Injected engine for job state.

    Returns:
        RedirectResponse | Response: Redirects to a signed GCS URL or streams the file locally.

    Raises:
        HTTPException: If the job is not completed, not found, or the report is missing.
    """
    job_data = job_engine.get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    if job_data.get("status") != "COMPLETED":
        raise HTTPException(status_code=400, detail="Report not ready or job failed")

    report_gcs_path = job_data.get("report_path")
    if not report_gcs_path:
        raise HTTPException(status_code=404, detail="Report file not found")

    try:
        # Attempt to generate a signed URL (Works in production with Service Account)
        try:
            signed_url = gcp.get_report_signed_url(report_gcs_path)
            # Redirect the user's browser directly to the signed URL
            return RedirectResponse(url=signed_url)
        except Exception as signing_error:  # noqa: BLE001
            logger.warning(
                f"Failed to generate signed URL (likely local dev with ADC): {signing_error}. Falling back to direct download."
            )
            # Fallback for local development using ADC token
            from fastapi.responses import Response

            content = gcp.get_report_bytes(report_gcs_path)
            return Response(
                content=content,
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f'attachment; filename="report_{job_id}.md"'
                },
            )
    except Exception as e:
        logger.error(f"Failed to retrieve report: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to retrieve report from storage"
        ) from e
