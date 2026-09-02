import datetime
from typing import Any, Protocol

from src.core.rate_limit import TokenBucketResult
from src.core.schemas import JobDocument, MigrationDag, TaskPayload

# ==============================================================================
# EDUCATIONAL NOTE: WHAT ARE PROTOCOLS?
# ==============================================================================
# In traditional languages (Java, C#), you define an `interface` and make your
# concrete classes explicitly inherit from it (Nominal Subtyping).
#
# Python uses `typing.Protocol` to achieve Structural Subtyping (Duck Typing).
# Our concrete classes (ClassificationEngine, ReportEngine) DO NOT need to inherit
# from these Protocols. As long as they have the methods defined here with the
# matching signatures, the type checker (MyPy/Ruff) will consider them valid.
#
# This allows complete decoupling: JobEngine only knows about these "shapes"
# of objects, not the actual objects themselves.
# ==============================================================================


class TokenBucketInterface(Protocol):
    """Protocol defining the mathematical evaluation of a token bucket."""

    def evaluate(
        self, current_tokens: int, last_reset: datetime.datetime, required_tokens: int
    ) -> TokenBucketResult:
        """Evaluates if enough tokens exist, returning the allowed status and new bucket state."""
        ...


class ClassifierInterface(Protocol):
    """Protocol defining the required behavior for a Classification Engine."""

    def process_inventory(self, inventory: dict[str, Any]) -> dict[str, Any]:
        """Processes a raw inventory and adds classification metadata."""
        ...


class ReporterInterface(Protocol):
    """Protocol defining the required behavior for a Report Engine."""

    def generate_markdown_report(self, classified_inventory: dict[str, Any]) -> str:
        """Generates a markdown string from a classified inventory."""
        ...

    def save_report(self, report_md: str, file_path: str) -> None:
        """Saves a report string to a local file path."""
        ...


class DiscovererInterface(Protocol):
    """Protocol defining the required behavior for a Discovery Engine."""

    async def discover_full_account(self, output_path: str) -> dict[str, Any]:
        """Discovers the entire account and returns the inventory payload."""
        ...


class StateInterface(Protocol):
    """Protocol defining state tracking, idempotency, and budget behavior."""

    def get_job(self, job_id: str) -> JobDocument | None:
        """Retrieves the state of a migration job."""
        ...

    def get_dest_id(self, job_id: str, entity_type: str, source_id: str) -> str | None:
        """Retrieves the destination ID for a given source ID to ensure idempotency."""
        ...

    def set_dest_id(
        self, job_id: str, entity_type: str, source_id: str, dest_id: str
    ) -> None:
        """Stores the destination ID mapped to the source ID for future idempotency checks."""
        ...

    def consume_budget(
        self, job_id: str, required_tokens: int = 50000
    ) -> tuple[bool, int]:
        """Proactively checks if the global token bucket has enough tokens and deducts them."""
        ...

    def sync_budget(
        self, job_id: str, actual_remaining: int, reset_in_seconds: int
    ) -> None:
        """Reactively syncs the token bucket with the exact numbers returned by Monday API."""
        ...

    def initialize_dag_state(self, job_id: str, dag: MigrationDag) -> None:
        """Initializes the stage gating counters for a new DAG execution."""
        ...

    def mark_task_complete(self, job_id: str, stage: str) -> bool:
        """Increments the completion counter for a stage and returns True if fully complete."""
        ...

    def save_dead_letter(
        self, job_id: str, stage: str, task: TaskPayload, error_message: str
    ) -> None:
        """Saves a permanently failed task to the dead letter queue."""
        ...

    def update_job_status(self, job_id: str, status: str) -> None:
        """Updates the top-level status of the job."""
        ...


class StorageInterface(Protocol):
    """Protocol defining blob storage behavior for DAG persistence."""

    async def save_dag(self, job_id: str, dag: MigrationDag) -> None:
        """Saves a computed DAG to storage."""
        ...

    async def load_dag(self, job_id: str) -> MigrationDag | None:
        """Loads a previously saved DAG from storage."""
        ...


class TaskQueueInterface(Protocol):
    """Protocol defining task enqueueing behavior."""

    async def enqueue_task(
        self,
        job_id: str,
        stage: str,
        task: TaskPayload,
        schedule_time: float | None = None,
    ) -> None:
        """Enqueues a single task payload to the specified stage queue."""
        ...


class GcpClientsInterface(Protocol):
    """Protocol defining GCP clients initialization and retrieval."""

    @property
    def storage_client(self) -> Any: ...

    @property
    def secret_client(self) -> Any: ...

    @property
    def run_client(self) -> Any: ...

    @property
    def firestore_client(self) -> Any: ...

    @property
    def tasks_client(self) -> Any: ...
