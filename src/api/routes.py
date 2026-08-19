import datetime
import logging
import os
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from google.cloud import firestore, secretmanager, storage

from src.api.models import JobCreateRequest, JobCreateResponse, JobStatusResponse

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

PROJECT_ID = os.environ.get("PROJECT_ID", "local-dev-project")
REPORTS_BUCKET = os.environ.get("REPORTS_BUCKET", "local-dev-reports-bucket")

# Initialize GCP Clients (Relying on Application Default Credentials)
try:
    db = firestore.Client(project=PROJECT_ID)
    storage_client = storage.Client(project=PROJECT_ID)
    secret_client = secretmanager.SecretManagerServiceClient()
except Exception as e:  # noqa: BLE001
    logger.warning(f"Failed to initialize GCP clients (ensure ADC is set): {e}")
    db = None
    storage_client = None
    secret_client = None


def set_job_status(
    job_id: str, status: str, report_path: str | None = None, error: str | None = None
):
    """Helper to update Firestore job status"""
    if not db:
        logger.warning(f"No Firestore client. Would update job {job_id} to {status}")
        return
    doc_ref = db.collection("jobs").document(job_id)
    update_data = {"status": status, "updated_at": datetime.datetime.now(datetime.UTC)}
    if report_path:
        update_data["report_path"] = report_path
    if error:
        update_data["error"] = error
    # Use set with merge to create if not exists
    doc_ref.set(update_data, merge=True)


def get_job(job_id: str):
    if not db:
        return None
    doc = db.collection("jobs").document(job_id).get()
    if doc.exists:
        return doc.to_dict()
    return None


async def run_discovery_job(job_id: str, source_api_key: str):
    """
    Simulates the background discovery job.
    In the full architecture, this would trigger a Cloud Run Job via GCP API.
    For this POC, we run it in the background task.
    """
    logger.info(f"Starting discovery job for {job_id}")
    set_job_status(job_id, "RUNNING")

    from src.classification import ClassificationEngine
    from src.discovery import DiscoveryEngine
    from src.monday_client import MondayClient
    from src.report_generator import ReportGenerator

    try:
        # 1. Discovery
        client = MondayClient(api_key=source_api_key)
        discovery_engine = DiscoveryEngine(client=client)

        # Save inventory locally first
        local_inventory_path = f"/tmp/{job_id}_inventory.json"
        inventory = await discovery_engine.discover_full_account(
            output_path=local_inventory_path
        )

        # 2. Classification
        classification_engine = ClassificationEngine()
        classified_inventory = classification_engine.process_inventory(inventory)

        # 3. Report Generation
        report_generator = ReportGenerator()
        report_md = report_generator.generate_markdown_report(classified_inventory)
        local_report_path = f"/tmp/{job_id}_report.md"
        report_generator.save_report(report_md, file_path=local_report_path)

        # 4. Upload to Cloud Storage
        report_gcs_path = None
        if storage_client:
            bucket = storage_client.bucket(REPORTS_BUCKET)
            blob_name = f"reports/{job_id}/pre_migration_report.md"
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(local_report_path)
            report_gcs_path = blob_name
            logger.info(f"Uploaded report to GCS: gs://{REPORTS_BUCKET}/{blob_name}")

        set_job_status(job_id, "COMPLETED", report_path=report_gcs_path)
        logger.info(f"Discovery job {job_id} completed successfully.")

    except Exception as e:  # noqa: BLE001
        logger.error(f"Discovery job {job_id} failed: {e}")
        set_job_status(job_id, "FAILED", error=str(e))


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

    # In production, we'd trigger a Cloud Run Job here passing the job_id.
    # For now, simulate background processing locally.
    background_tasks.add_task(run_discovery_job, job_id, request.source_api_key)

    return JobCreateResponse(
        job_id=job_id,
        status="PENDING",
        message="Discovery job created and started in background.",
    )


@app.get("/api/v1/jobs/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    job_data = get_job(job_id)
    if not job_data:
        # Fallback logic for local testing without firestore
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

        # Generate a signed URL for the frontend to download directly
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=15),
            method="GET",
        )
        # Redirect the user's browser directly to the signed URL
        return RedirectResponse(url=signed_url)
    except Exception as e:
        logger.error(f"Failed to generate signed URL: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to generate download link"
        ) from e
