import logging
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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

# In-memory store for POC. Will be replaced by Firestore.
# Structure: { "job_id": { "status": "PENDING", ... } }
job_store = {}


async def run_discovery_job(job_id: str, source_api_key: str):
    """
    Simulates the background discovery job.
    In the full architecture, this would trigger a Cloud Run Job.
    """
    logger.info(f"Starting discovery job for {job_id}")
    job_store[job_id]["status"] = "RUNNING"

    # Import here to avoid circular dependencies if needed later
    from src.classification import ClassificationEngine
    from src.discovery import DiscoveryEngine
    from src.monday_client import MondayClient
    from src.report_generator import ReportGenerator

    try:
        # 1. Discovery
        client = MondayClient(api_key=source_api_key)
        discovery_engine = DiscoveryEngine(client=client)

        # Save inventory to a job-specific file for now (later Cloud Storage or BigQuery)
        inventory_path = f"{job_id}_inventory.json"
        inventory = await discovery_engine.discover_full_account(
            output_path=inventory_path
        )

        # 2. Classification
        classification_engine = ClassificationEngine()
        classified_inventory = classification_engine.process_inventory(inventory)

        # 3. Report Generation
        report_generator = ReportGenerator()
        report_md = report_generator.generate_markdown_report(classified_inventory)
        report_path = f"{job_id}_report.md"
        report_generator.save_report(report_md, file_path=report_path)

        job_store[job_id]["status"] = "COMPLETED"
        job_store[job_id]["report_path"] = report_path
        logger.info(f"Discovery job {job_id} completed successfully.")

    except Exception as e:  # noqa: BLE001
        logger.error(f"Discovery job {job_id} failed: {e}")
        job_store[job_id]["status"] = "FAILED"
        job_store[job_id]["error"] = str(e)


@app.post("/api/v1/jobs", response_model=JobCreateResponse)
async def create_job(request: JobCreateRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    job_store[job_id] = {"status": "PENDING"}

    # In production, we'd store keys in Secret Manager scoped by job_id here.
    # For now, we pass it to the background task (which simulates the Cloud Run Job)
    background_tasks.add_task(run_discovery_job, job_id, request.source_api_key)

    return JobCreateResponse(
        job_id=job_id,
        status="PENDING",
        message="Discovery job created and started in background.",
    )


@app.get("/api/v1/jobs/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    if job_id not in job_store:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(job_id=job_id, status=job_store[job_id]["status"])


@app.get("/api/v1/jobs/{job_id}/report")
async def get_job_report(job_id: str):
    if job_id not in job_store:
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = job_store[job_id]
    if job_data["status"] != "COMPLETED":
        raise HTTPException(status_code=400, detail="Report not ready or job failed")

    # Later: return signed URL for Cloud Storage
    import os

    from fastapi.responses import FileResponse

    report_path = job_data.get("report_path")
    if not report_path or not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="Report file not found")

    return FileResponse(path=report_path, filename=f"migration_report_{job_id}.md")
