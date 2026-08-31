import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.job_routes import job_router
from src.api.worker_routes import worker_router
from src.core.config import settings
from src.core.local_queue import local_worker_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Determine if we are running locally based on absence of K_SERVICE (Cloud Run env var)
    is_local = settings.is_local

    worker_tasks = []
    if is_local:
        logger.info("Starting local async worker pool (simulating Cloud Tasks)...")
        for i in range(5):  # 5 concurrent workers
            task = asyncio.create_task(local_worker_loop(i))
            worker_tasks.append(task)

    yield

    if worker_tasks:
        logger.info("Shutting down local async workers...")
        for task in worker_tasks:
            task.cancel()
        # Optionally wait for them to finish cancelling
        await asyncio.gather(*worker_tasks, return_exceptions=True)


app = FastAPI(title="Monday.com Migration API", lifespan=lifespan)

# Allow CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(job_router, prefix="/api/v1/jobs", tags=["jobs"])
app.include_router(worker_router, prefix="/api/v1/worker", tags=["worker"])
