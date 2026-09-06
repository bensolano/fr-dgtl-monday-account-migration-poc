from src.infrastructure.gcp.services import gcp_clients
from src.infrastructure.gcp.tasks import GCSDagStorage, get_task_queue
from src.infrastructure.monday.client import MondayClient
from src.infrastructure.monday.rate_limit import TokenBucketRateLimiter
from src.infrastructure.state.firestore import StateManager
from src.services.classification import ClassificationService
from src.services.discovery import DiscoveryService
from src.services.job import JobService
from src.services.orchestration import OrchestrationService
from src.services.report import ReportService


def default_discovery_factory(api_key: str) -> DiscoveryService:
    """Factory function to build a DiscoveryService with a dynamic API key."""
    client = MondayClient(api_key=api_key)
    return DiscoveryService(client=client)


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

_job_engine_instance = JobService(
    classifier=ClassificationService(),
    reporter=ReportService(),
    gcp_clients=gcp_clients,
    state_manager=_state_manager_instance,
    discovery_factory=default_discovery_factory,
)

_orchestration_instance = OrchestrationService(
    state_manager=_state_manager_instance,
    dag_storage=GCSDagStorage(),
    task_queue=get_task_queue(),
)


def get_state_manager() -> StateManager:
    """Dependency provider for StateManager (singleton)."""
    return _state_manager_instance


def get_job_engine() -> JobService:
    """Dependency provider that wires concrete engines into JobService (singleton)."""
    return _job_engine_instance


def get_orchestration() -> OrchestrationService:
    """Dependency provider that wires infrastructure into OrchestrationService (singleton)."""
    return _orchestration_instance
