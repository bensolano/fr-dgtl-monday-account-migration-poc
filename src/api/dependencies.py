from src.core.gcp import gcp_clients
from src.core.monday_client import MondayClient
from src.core.rate_limit import TokenBucketRateLimiter
from src.core.state import StateManager
from src.core.task_deps import GCSDagStorage, get_task_queue
from src.engines.classification_engine import ClassificationEngine
from src.engines.discovery_engine import DiscoveryEngine
from src.engines.job_engine import JobEngine
from src.engines.orchestration_engine import OrchestrationEngine
from src.engines.report_engine import ReportEngine


def default_discovery_factory(api_key: str) -> DiscoveryEngine:
    """Factory function to build a DiscoveryEngine with a dynamic API key."""
    client = MondayClient(api_key=api_key)
    return DiscoveryEngine(client=client)


# ==============================================================================
# SINGLETON INSTANCES
# ==============================================================================
# We instantiate these globally so that they act as singletons for the life of
# the process. This prevents recreating gRPC clients (like firestore.Client)
# on every single request, which causes file descriptor leaks and thread
# exhaustion in Uvicorn/Gunicorn.
# ==============================================================================
_state_manager_instance = StateManager(
    gcp_clients=gcp_clients, rate_limiter=TokenBucketRateLimiter()
)

_job_engine_instance = JobEngine(
    classifier=ClassificationEngine(),
    reporter=ReportEngine(),
    gcp_clients=gcp_clients,
    state_manager=_state_manager_instance,
    discovery_factory=default_discovery_factory,
)

_orchestration_instance = OrchestrationEngine(
    state_manager=_state_manager_instance,
    dag_storage=GCSDagStorage(),
    task_queue=get_task_queue(),
)


def get_state_manager() -> StateManager:
    """Dependency provider for StateManager (singleton)."""
    return _state_manager_instance


def get_job_engine() -> JobEngine:
    """Dependency provider that wires concrete engines into JobEngine (singleton)."""
    return _job_engine_instance


def get_orchestration() -> OrchestrationEngine:
    """Dependency provider that wires infrastructure into OrchestrationEngine (singleton)."""
    return _orchestration_instance
