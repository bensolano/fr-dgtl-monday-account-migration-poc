from typing import Any, Protocol

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
    """Protocol defining state tracking behavior (e.g. for DAG orchestration)."""

    def initialize_dag_state(
        self, job_id: str, dag: dict[str, list[dict[str, Any]]]
    ) -> None:
        """Initializes the stage gating counters for a new DAG execution."""
        ...


class StorageInterface(Protocol):
    """Protocol defining blob storage behavior for DAG persistence."""

    def save_dag(self, job_id: str, dag: dict[str, list[dict[str, Any]]]) -> None:
        """Saves a computed DAG to storage."""
        ...

    def load_dag(self, job_id: str) -> dict[str, list[dict[str, Any]]] | None:
        """Loads a previously saved DAG from storage."""
        ...


class TaskQueueInterface(Protocol):
    """Protocol defining task enqueueing behavior."""

    def enqueue_task(self, job_id: str, stage: str, task: dict[str, Any]) -> None:
        """Enqueues a single task payload to the specified stage queue."""
        ...
