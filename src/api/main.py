import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.job_routes import job_router
from src.api.worker_routes import worker_router

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

app.include_router(job_router, prefix="/api/v1/jobs", tags=["jobs"])
app.include_router(worker_router, prefix="/api/v1/worker", tags=["worker"])
