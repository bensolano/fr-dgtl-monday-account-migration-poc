import datetime
import logging
import os
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from google.cloud import run_v2, secretmanager, storage

from src.api.models import JobCreateRequest, JobCreateResponse, JobStatusResponse
from src.api.worker_routes import worker_router
from src.engines.job_engine import execute_discovery_job, get_job, set_job_status

logger = logging.getLogger(__name__)

app = FastAPI(title="Monday.com Migration API")

# Allow CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(worker_router, prefix="/api/v1/worker", tags=["worker"])

PROJECT_ID = os.environ.get("PROJECT_ID", "local-dev-project")
REGION = os.environ.get("REGION", "europe-west1")
REPORTS_BUCKET = os.environ.get("REPORTS_BUCKET", "local-dev-reports-bucket")
DISCOVERY_JOB_NAME = os.environ.get("DISCOVERY_JOB_NAME")

# Initialize GCP Clients (Relying on Application Default Credentials)
try:
    storage_client = storage.Client(project=PROJECT_ID)
    secret_client = secretmanager.SecretManagerServiceClient()
    run_client = run_v2.JobsClient()
except Exception as e:  # noqa: BLE001
    logger.warning(f"Failed to initialize GCP clients (ensure ADC is set): {e}")
    storage_client = None
    secret_client = None
    run_client = None


def trigger_cloud_run_job(job_id: str):
    """Triggers the Cloud Run batch job using the GCP SDK."""
    if not run_client or not DISCOVERY_JOB_NAME:
        logger.warning(
            f"Cloud Run Job client or DISCOVERY_JOB_NAME not configured. Cannot trigger job {job_id}."
        )
        return

    name = f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{DISCOVERY_JOB_NAME}"
    request = run_v2.RunJobRequest(
        name=name,
        overrides={
            "container_overrides": [{"env": [{"name": "JOB_ID", "value": job_id}]}]
        },
    )

    try:
        operation = run_client.run_job(request=request)
        logger.info(
            f"Triggered Cloud Run Job for {job_id}. Operation: {operation.operation.name}"
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to trigger Cloud Run Job for {job_id}: {e}")
        set_job_status(
            job_id, "FAILED", error="Failed to start background job infrastructure."
        )


@app.post("/api/v1/jobs", response_model=JobCreateResponse)
async def create_job(request: JobCreateRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())

    # Secure API Keys in Secret Manager
    if secret_client:
        parent = f"projects/{PROJECT_ID}"
        try:
            # Create Secret for Source Key
            source_secret_id = f"job-{job_id}-source-key"
            secret_client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": source_secret_id,
                    "secret": {"replication": {"automatic": {}}},
                }
            )
            secret_client.add_secret_version(
                request={
                    "parent": f"{parent}/secrets/{source_secret_id}",
                    "payload": {"data": request.source_api_key.encode("UTF-8")},
                }
            )

            # Destination key if provided
            if request.dest_api_key:
                dest_secret_id = f"job-{job_id}-dest-key"
                secret_client.create_secret(
                    request={
                        "parent": parent,
                        "secret_id": dest_secret_id,
                        "secret": {"replication": {"automatic": {}}},
                    }
                )
                secret_client.add_secret_version(
                    request={
                        "parent": f"{parent}/secrets/{dest_secret_id}",
                        "payload": {"data": request.dest_api_key.encode("UTF-8")},
                    }
                )
        except Exception as e:
            logger.error(f"Failed to store secrets in Secret Manager: {e}")
            raise HTTPException(
                status_code=500, detail="Failed to secure credentials."
            ) from e

    # Init state in Firestore
    set_job_status(job_id, "PENDING")

    if DISCOVERY_JOB_NAME and run_client:
        # PRODUCTION: Trigger actual GCP Cloud Run Job
        trigger_cloud_run_job(job_id)
        msg = "Cloud Run job triggered."
    else:
        # LOCAL DEVELOPMENT: Fallback to running it in the background of the FastAPI process
        background_tasks.add_task(execute_discovery_job, job_id)
        msg = "Local background task started."

    return JobCreateResponse(
        job_id=job_id,
        status="PENDING",
        message=msg,
    )


@app.get("/api/v1/jobs/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    job_data = get_job(job_id)
    if not job_data:
        # Fallback logic for local testing without firestore
        from src.engines.job_engine import db  # Import here to check local db state

        if not db:
            return JobStatusResponse(job_id=job_id, status="PENDING")
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(job_id=job_id, status=job_data.get("status", "UNKNOWN"))


@app.get("/api/v1/jobs/{job_id}/report")
async def get_job_report(job_id: str):
    job_data = get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    if job_data.get("status") != "COMPLETED":
        raise HTTPException(status_code=400, detail="Report not ready or job failed")

    report_gcs_path = job_data.get("report_path")
    if not report_gcs_path or not storage_client:
        raise HTTPException(
            status_code=404, detail="Report file not found or Storage unconfigured"
        )

    try:
        bucket = storage_client.bucket(REPORTS_BUCKET)
        blob = bucket.blob(report_gcs_path)

        # Attempt to generate a signed URL (Works in production with Service Account)
        try:
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(minutes=15),
                method="GET",
            )
            # Redirect the user's browser directly to the signed URL
            return RedirectResponse(url=signed_url)
        except Exception as signing_error:  # noqa: BLE001
            logger.warning(
                f"Failed to generate signed URL (likely local dev with ADC): {signing_error}. Falling back to direct download."
            )
            # Fallback for local development using ADC token
            from fastapi.responses import Response

            content = blob.download_as_bytes()
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
