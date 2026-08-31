from pydantic import BaseModel


class JobCreateRequest(BaseModel):
    source_api_key: str


class ExecuteJobRequest(BaseModel):
    dest_api_key: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # PENDING, RUNNING, COMPLETED, FAILED


class JobCreateResponse(BaseModel):
    job_id: str
    status: str
    message: str


class ExecuteJobResponse(BaseModel):
    status: str
    message: str


class TaskResponse(BaseModel):
    status: str
    reason: str | None = None
    dest_id: str | None = None
