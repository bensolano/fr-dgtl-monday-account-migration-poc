from pydantic import BaseModel


class JobCreateRequest(BaseModel):
    source_api_key: str
    dest_api_key: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # PENDING, RUNNING, COMPLETED, FAILED


class JobCreateResponse(BaseModel):
    job_id: str
    status: str
    message: str
