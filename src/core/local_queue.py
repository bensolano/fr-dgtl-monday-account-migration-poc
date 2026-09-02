import asyncio
import logging
import time

import httpx

from src.core.schemas import TaskPayload

logger = logging.getLogger(__name__)

_local_queue: asyncio.Queue | None = None


class LocalTaskQueue:
    """Simulates Cloud Tasks locally using an asyncio.Queue and background workers."""

    def __init__(self, service_url: str = "http://127.0.0.1:8000"):
        """
        Initializes the LocalTaskQueue.

        Args:
            service_url (str): The base URL of the local FastAPI server.
        """
        self.service_url = service_url

    async def enqueue_task(
        self,
        job_id: str,
        stage: str,
        task: TaskPayload,
        schedule_time: float | None = None,
    ) -> None:
        """
        Enqueues a task to the local asyncio queue, optionally with a delay.

        Args:
            job_id (str): The unique identifier of the migration job.
            stage (str): The DAG stage currently being executed.
            task (TaskPayload): The payload containing the entity data to migrate.
            schedule_time (float | None): Optional Unix timestamp for when to execute the task.

        Returns:
            None
        """
        global _local_queue
        if _local_queue is None:
            _local_queue = asyncio.Queue()

        delay = 0.0
        if schedule_time is not None:
            now = time.time()
            delay = max(0.0, float(schedule_time) - now)

        payload = {"job_id": job_id, "task": task.model_dump()}

        if delay > 0:
            # For local dev, we just sleep in a background task before pushing to queue
            async def delayed_enqueue():
                await asyncio.sleep(delay)
                await _local_queue.put((stage, payload))

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(delayed_enqueue())
            except RuntimeError:
                # If no loop is running, just put it immediately (fallback)
                await _local_queue.put((stage, payload))
        else:
            await _local_queue.put((stage, payload))


async def local_worker_loop(worker_id: int, service_url: str = "http://127.0.0.1:8000"):
    """
    Background loop that processes tasks from the local queue and fires HTTP webhooks.

    Args:
        worker_id (int): The identifier for this worker instance.
        service_url (str): The base URL of the local FastAPI server to send POST requests to.

    Returns:
        None
    """
    global _local_queue
    if _local_queue is None:
        _local_queue = asyncio.Queue()

    logger.info(f"Local worker {worker_id} started.")

    # Using httpx to hit our own FastAPI server just like GCP Cloud Tasks would
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            stage, payload = await _local_queue.get()
            url = f"{service_url}/api/v1/worker/{stage}"
            try:
                # HTTP request to simulate Cloud Tasks POST webhook
                resp = await client.post(url, json=payload)
                if resp.status_code == 429:
                    # Generic rate limit fallback
                    await asyncio.sleep(1.0)
                    await _local_queue.put((stage, payload))
                elif resp.status_code >= 500:
                    logger.error(
                        f"Worker {worker_id} encountered severe server error: {resp.text}"
                    )
                    # We drop the task here since application-level retries are handled in handle_task via 200 OK requeues.
                    # If it's a true 500, it means the server crashed before handling it. We drop to avoid infinite loops.
            except Exception as e:  # noqa: BLE001
                logger.error(f"Worker {worker_id} network failure: {e}")
                # Network level failure, also drop to avoid infinite loops
            finally:
                _local_queue.task_done()
