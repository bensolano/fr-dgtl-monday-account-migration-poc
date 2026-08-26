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
    """
    Retrieves the destination Monday.com API key for a given job from Secret Manager.

    Args:
        job_id (str): The unique identifier of the migration job.

    Returns:
        str: The decoded API key.

    Raises:
        RuntimeError: If the Secret Manager client is not initialized.
        HTTPException: If retrieving the secret fails.
    """
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


def estimate_complexity(entity_type: str, payload: dict[str, Any]) -> int:
    """
    Estimates the GraphQL complexity cost of creating an entity.
    This allows the Token Bucket to proactively rate limit based on realistic payload weights.

    Args:
        entity_type (str): The type of the entity (workspace, board, group, column, item).
        payload (dict[str, Any]): The payload data for the entity.

    Returns:
        int: The estimated complexity cost in points.
    """
    base_costs = {
        "workspace": 1000,
        "board": 5000,
        "group": 500,
        "column": 1000,
        "item": 10,
    }

    cost = base_costs.get(entity_type, 1000)

    # Example heuristic: items with lots of column values cost more
    if entity_type == "item" and "column_values" in payload:
        cost += len(payload["column_values"]) * 10

    return cost


@worker_router.post("/{stage}")
async def handle_task(stage: str, request: Request) -> dict[str, Any] | JSONResponse:
    """
    Cloud Tasks HTTP webhook handler.
    Receives tasks from the queues, checks idempotency, enforces rate limits, and applies mutations.

    Args:
        stage (str): The DAG stage currently being executed (e.g., 'boards', 'items').
        request (Request): The incoming FastAPI HTTP request containing the Cloud Task payload.

    Returns:
        dict[str, Any] | JSONResponse: A success dict or an HTTP 429 JSONResponse for rate limiting.

    Raises:
        HTTPException: If the payload is invalid, missing required fields, or execution fails.
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
    estimated_cost = estimate_complexity(entity_type, entity_payload)
    if not state_manager.consume_budget(job_id, estimated_cost):
        logger.warning(
            f"Insufficient complexity budget ({estimated_cost} required) for {entity_type}. Yielding 429 to Cloud Tasks."
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

        # 4. Stage Gating (DAG state decrement)
        # We assume the stage name corresponds closely to the entity_type ('board' -> 'boards')
        # This triggers the enqueue of the next stage if this was the last task.
        plural_stage = f"{entity_type}s"
        is_stage_done = state_manager.mark_task_complete(job_id, plural_stage)

        if is_stage_done:
            logger.info(
                f"Stage '{plural_stage}' for job {job_id} is completely finished!"
            )
            # In a full implementation, you would enqueue the *next* stage here, e.g. using OrchestratorEngine

        return {"status": "success", "dest_id": dest_id}

    except Exception as e:
        logger.error(f"Failed to execute mutation for {entity_type} {source_id}: {e}")
        # Pass 500 errors to Cloud Tasks which will retry based on its config
        raise HTTPException(status_code=500, detail=str(e)) from e
