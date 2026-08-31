import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.api.models import TaskResponse
from src.core import gcp
from src.core.exceptions import MondayRateLimitError
from src.core.monday_client import MondayClient
from src.core.schemas import WorkerTaskRequest
from src.core.state import StateManager
from src.core.task_deps import GCSDagStorage, get_task_queue
from src.engines.execution_engine import ExecutionEngine
from src.engines.orchestration_engine import OrchestrationEngine

logger = logging.getLogger(__name__)

worker_router = APIRouter()


def get_orchestration() -> OrchestrationEngine:
    """Dependency provider that wires infrastructure into OrchestrationEngine."""
    return OrchestrationEngine(
        state_manager=StateManager(),
        dag_storage=GCSDagStorage(),
        task_queue=get_task_queue(),
    )


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


@worker_router.post("/{stage}", response_model=TaskResponse)
async def handle_task(
    stage: str,
    request_payload: WorkerTaskRequest,
    state_manager: Annotated[StateManager, Depends()],
    orchestration: Annotated[OrchestrationEngine, Depends(get_orchestration)],
) -> TaskResponse:
    """
    Cloud Tasks HTTP webhook handler.
    Receives tasks from the queues, checks idempotency, enforces rate limits, and applies mutations.

    Args:
        stage (str): The DAG stage currently being executed (e.g., 'boards', 'items').
        request_payload (WorkerTaskRequest): The incoming validated Cloud Task payload.
        state_manager (StateManager): Injected dependency for job state and gating.
        orchestration (OrchestrationEngine): Injected dependency for triggering subsequent stages.

    Returns:
        TaskResponse: A success or skipped status payload.

    Raises:
        HTTPException: If the payload is invalid, missing required fields, execution fails, or rate limits hit (429).
    """
    job_id = request_payload.job_id
    task = request_payload.task

    entity_type = task.entity_type
    source_id = task.source_id
    entity_payload = task.payload

    logger.info(
        f"Worker received {stage} task: Job {job_id} | Type {entity_type} | Source ID {source_id} | Payload Size: {len(str(entity_payload))} bytes"
    )

    # 1. Idempotency Check
    existing_dest_id = state_manager.get_dest_id(job_id, entity_type, source_id)
    if existing_dest_id:
        logger.info(
            f"Idempotency hit: {entity_type} {source_id} already exists as {existing_dest_id}. Bypassing."
        )
        return TaskResponse(status="skipped", reason="idempotent")

    # 2. Proactive Rate Limiting (Token Bucket)
    estimated_cost = estimate_complexity(entity_type, entity_payload)
    is_safe, retry_in = state_manager.consume_budget(job_id, estimated_cost)
    if not is_safe:
        logger.warning(
            f"Insufficient complexity budget ({estimated_cost} required) for {entity_type}. Re-enqueueing in {retry_in}s."
        )
        import time

        schedule_time = time.time() + retry_in
        orchestration.task_queue.enqueue_task(
            job_id, stage, task, schedule_time=schedule_time
        )
        return TaskResponse(status="skipped", reason="rate_limited_requeued")

    # 3. Execution
    try:
        # ==============================================================================
        # EDUCATIONAL NOTE: THE DYNAMIC COMPOSITION ROOT
        # ==============================================================================
        # Wait, if FastAPI routing is the Composition Root, why aren't we injecting
        # ExecutionEngine via `Depends()` in the route signature?
        #
        # Because ExecutionEngine requires `job_id` and a dynamic API key to be built.
        # Here, `job_id` is buried inside the raw `await request.json()` payload.
        # FastAPI's `Depends()` runs *before* the route body executes, so it cannot
        # easily parse the dynamic JSON body to extract `job_id` to build the engine.
        #
        # Therefore, this specific route block acts as a "Manual Composition Root".
        # We manually fetch the concrete dependencies (API key, MondayClient), wire
        # them together with the already-injected `state_manager`, and instantiate
        # the ExecutionEngine.
        #
        # This still obeys SOLID! The route (the outer layer) is doing the dirty work
        # of wiring, keeping the ExecutionEngine itself pure.
        # ==============================================================================

        # In local dev testing without SecretManager, we might want to bypass or error gracefully
        try:
            dest_api_key = gcp.get_dest_api_key(job_id)
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
            # Use the injected orchestration to trigger the next stage
            orchestration.enqueue_next_stage(job_id, current_stage=plural_stage)

        return TaskResponse(status="success", dest_id=str(dest_id))

    except MondayRateLimitError as e:
        logger.warning(
            f"Rate limit hit during execution for {entity_type} {source_id}: {e}"
        )
        import time

        schedule_time = time.time() + e.retry_in_seconds
        orchestration.task_queue.enqueue_task(
            job_id, stage, task, schedule_time=schedule_time
        )
        return TaskResponse(status="skipped", reason="rate_limited_requeued")
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to execute mutation for {entity_type} {source_id}: {e}")

        MAX_RETRIES = 3
        if task.retry_count < MAX_RETRIES:
            task.retry_count += 1
            logger.info(
                f"Retrying task (attempt {task.retry_count}/{MAX_RETRIES}) for {entity_type} {source_id}"
            )
            import time

            # Exponential backoff: 2, 4, 8 seconds
            schedule_time = time.time() + (2**task.retry_count)
            orchestration.task_queue.enqueue_task(
                job_id, stage, task, schedule_time=schedule_time
            )
            return TaskResponse(status="skipped", reason="transient_error_requeued")
        else:
            logger.error(
                f"Task permanently failed after {MAX_RETRIES} retries. Moving to Dead Letter Queue."
            )
            state_manager.save_dead_letter(job_id, stage, task.model_dump(), str(e))

            # CRITICAL: We must mark the task as "complete" in the stage counter even if it failed,
            # otherwise the DAG stage will never reach 100% and will hang forever.
            plural_stage = f"{entity_type}s"
            is_stage_done = state_manager.mark_task_complete(job_id, plural_stage)

            if is_stage_done:
                logger.info(
                    f"Stage '{plural_stage}' for job {job_id} is completely finished (with some dead letters)!"
                )
                orchestration.enqueue_next_stage(job_id, current_stage=plural_stage)

            return TaskResponse(status="failed", reason="dead_lettered")
