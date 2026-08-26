import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from google.cloud import secretmanager

from src.core.monday_client import MondayClient
from src.core.state import StateManager
from src.engines.execution_engine import ExecutionEngine

logger = logging.getLogger(__name__)

worker_router = APIRouter()
state_manager = StateManager()

PROJECT_ID = os.environ.get("PROJECT_ID", "local-dev-project")

try:
    secret_client = secretmanager.SecretManagerServiceClient()
except Exception as e:  # noqa: BLE001
    logger.warning(f"Failed to initialize Secret Manager in worker_routes: {e}")
    secret_client = None


def get_dest_api_key(job_id: str) -> str:
    if not secret_client:
        raise RuntimeError("Secret Manager client is not initialized.")
    secret_name = f"projects/{PROJECT_ID}/secrets/job-{job_id}-dest-key/versions/latest"
    try:
        response = secret_client.access_secret_version(request={"name": secret_name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        logger.error(f"Failed to retrieve destination API key for job {job_id}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to retrieve destination API key."
        ) from e


@worker_router.post("/{stage}")
async def handle_task(stage: str, request: Request) -> dict[str, Any] | JSONResponse:
    """
    Cloud Tasks HTTP webhook handler.
    Receives tasks from the queues, checks idempotency, and applies mutations.
    """
    try:
        payload = await request.json()
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to parse task payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    job_id = payload.get("job_id")
    task = payload.get("task")

    if not job_id or not task:
        raise HTTPException(status_code=400, detail="Missing job_id or task in payload")

    entity_type = task.get("entity_type")
    source_id = task.get("source_id")
    entity_payload = task.get("payload")

    logger.info(
        f"Worker received {stage} task: Job {job_id} | Type {entity_type} | Source ID {source_id} | Payload Size: {len(str(entity_payload))} bytes"
    )

    # 1. Idempotency Check
    existing_dest_id = state_manager.get_dest_id(job_id, entity_type, source_id)
    if existing_dest_id:
        logger.info(
            f"Idempotency hit: {entity_type} {source_id} already exists as {existing_dest_id}. Bypassing."
        )
        return {"status": "skipped", "reason": "idempotent"}

    # 2. Proactive Rate Limiting (Token Bucket)
    estimated_cost = 50000
    if not state_manager.consume_budget(job_id, estimated_cost):
        logger.warning(
            f"Insufficient complexity budget for {entity_type}. Yielding 429 to Cloud Tasks."
        )
        # Return HTTP 429 to tell Cloud Tasks to back off and requeue natively
        return JSONResponse(
            status_code=429,
            content={"detail": "Complexity budget exhausted. Requeueing."},
        )

    # 3. Execution
    try:
        # In local dev testing without SecretManager, we might want to bypass or error gracefully
        try:
            dest_api_key = get_dest_api_key(job_id)
        except RuntimeError:
            dest_api_key = "MOCK_KEY_FOR_LOCAL_TESTING"

        client = MondayClient(api_key=dest_api_key)
        engine = ExecutionEngine(
            client=client, state_manager=state_manager, job_id=job_id
        )

        dest_id = await engine.execute(entity_type, source_id, entity_payload)
        logger.info(
            f"Successfully executed mutation for {entity_type} {source_id}. Created {dest_id}."
        )
        return {"status": "success", "dest_id": dest_id}

    except Exception as e:
        logger.error(f"Failed to execute mutation for {entity_type} {source_id}: {e}")
        # Pass 500 errors to Cloud Tasks which will retry based on its config
        raise HTTPException(status_code=500, detail=str(e)) from e
