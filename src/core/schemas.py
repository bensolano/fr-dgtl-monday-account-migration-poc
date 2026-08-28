from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SecretRef(BaseModel):
    secret_ref: str


class JobDocument(BaseModel):
    job_id: str
    status: str
    operator_email: str
    source_account: SecretRef
    dest_account: SecretRef
    created_at: datetime | None = None
    expires_at: datetime | None = None


class TaskPayload(BaseModel):
    entity_type: str
    source_id: str
    payload: dict[str, Any]


class MigrationDag(BaseModel):
    workspaces: list[TaskPayload] = Field(default_factory=list)
    boards: list[TaskPayload] = Field(default_factory=list)
    groups: list[TaskPayload] = Field(default_factory=list)
    columns: list[TaskPayload] = Field(default_factory=list)
    items: list[TaskPayload] = Field(default_factory=list)
