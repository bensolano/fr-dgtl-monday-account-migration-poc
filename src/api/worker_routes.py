import logging

from fastapi import APIRouter, HTTPException, Request

from src.core.state import StateManager

logger = logging.getLogger(__name__)

worker_router = APIRouter()
state_manager = StateManager()


@worker_router.post("/{stage}")
async def handle_task(stage: str, request: Request):
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
    # Estimate cost. A real implementation might map this closer to reality.
    estimated_cost = 50000
    if not state_manager.consume_budget(job_id, estimated_cost):
        logger.warning(
            f"Insufficient complexity budget for {entity_type}. Yielding 429 to Cloud Tasks."
        )
        from fastapi.responses import JSONResponse

        # Return HTTP 429 to tell Cloud Tasks to back off and requeue natively
        return JSONResponse(
            status_code=429,
            content={"detail": "Complexity budget exhausted. Requeueing."},
        )

    # 3. Execution (Mocked for now)
    # TODO: Initialize MondayClient with dest_api_key from SecretManager
    # TODO: Execute exact mutation based on stage and payload using distributed=True
    # TODO: Use returned `_meta_complexity` to call state_manager.sync_budget()

    mock_dest_id = f"mock_dest_{source_id}"
    logger.info(
        f"Mock executed mutation for {entity_type} {source_id}. Created {mock_dest_id}."
    )

    # 4. Store ID mapping
    state_manager.set_dest_id(job_id, entity_type, source_id, mock_dest_id)

    return {"status": "success", "dest_id": mock_dest_id}
