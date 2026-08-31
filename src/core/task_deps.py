import json
import logging
import os

from google.cloud import storage

from src.core.local_queue import LocalTaskQueue
from src.core.schemas import MigrationDag, TaskPayload

try:
    from google.cloud import tasks_v2
    from google.protobuf import timestamp_pb2
except ImportError:
    tasks_v2 = None
    timestamp_pb2 = None

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "local-dev-project")
REGION = os.environ.get("REGION", "europe-west1")
SERVICE_URL = os.environ.get("SERVICE_URL", "https://example.com")
REPORTS_BUCKET = os.environ.get("REPORTS_BUCKET", "local-dev-reports-bucket")


class GCSDagStorage:
    """Manages storing and retrieving the migration DAG state in Google Cloud Storage."""

    def __init__(self, project_id: str = PROJECT_ID, bucket_name: str = REPORTS_BUCKET):
        """
        Initializes the GCSDagStorage client.

        Args:
            project_id (str): The GCP project ID.
            bucket_name (str): The GCS bucket name for storing reports and DAGs.
        """
        self.client = storage.Client(project=project_id)
        self.bucket = self.client.bucket(bucket_name)

    def save_dag(self, job_id: str, dag: MigrationDag) -> None:
        """
        Serializes and uploads the MigrationDag to GCS.

        Args:
            job_id (str): The unique identifier of the migration job.
            dag (MigrationDag): The migration DAG object to save.

        Returns:
            None
        """
        blob = self.bucket.blob(f"reports/{job_id}/dag.json")
        blob.upload_from_string(dag.model_dump_json(), content_type="application/json")

    def load_dag(self, job_id: str) -> MigrationDag | None:
        """
        Downloads and deserializes the MigrationDag from GCS.

        Args:
            job_id (str): The unique identifier of the migration job.

        Returns:
            MigrationDag | None: The parsed DAG if found, else None.
        """
        blob = self.bucket.blob(f"reports/{job_id}/dag.json")
        if not blob.exists():
            return None
        return MigrationDag.model_validate_json(blob.download_as_string())


class CloudTaskQueue:
    """Manages enqueuing tasks into Google Cloud Tasks for distributed execution."""

    def __init__(
        self,
        project_id: str = PROJECT_ID,
        region: str = REGION,
        service_url: str = SERVICE_URL,
    ):
        """
        Initializes the CloudTaskQueue client.

        Args:
            project_id (str): The GCP project ID.
            region (str): The GCP region where the queue is located.
            service_url (str): The base URL of the worker API for the webhook.
        """
        self.project_id = project_id
        self.region = region
        self.service_url = service_url
        self.client = tasks_v2.CloudTasksClient() if tasks_v2 else None

    def enqueue_task(
        self,
        job_id: str,
        stage: str,
        task: TaskPayload,
        schedule_time: float | None = None,
    ) -> None:
        """
        Pushes a single task to the appropriate Cloud Tasks queue.

        Args:
            job_id (str): The unique identifier of the migration job.
            stage (str): The DAG stage currently being executed (e.g., 'workspaces', 'boards').
            task (TaskPayload): The payload containing the entity data to migrate.
            schedule_time (float | None): Optional Unix timestamp for when to execute the task.

        Returns:
            None
        """
        if not self.client:
            return

        queue_name = f"migration-{stage}"
        parent = self.client.queue_path(self.project_id, self.region, queue_name)

        payload_bytes = json.dumps(
            {"job_id": job_id, "task": task.model_dump()}
        ).encode("utf-8")
        task_def = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{self.service_url}/api/v1/worker/{stage}",
                "headers": {"Content-type": "application/json"},
                "body": payload_bytes,
            }
        }

        if schedule_time is not None and timestamp_pb2 is not None:
            timestamp = timestamp_pb2.Timestamp()
            timestamp.FromSeconds(int(schedule_time))
            task_def["schedule_time"] = timestamp

        self.client.create_task(request={"parent": parent, "task": task_def})


def get_task_queue():
    """
    Dependency factory that returns the appropriate task queue implementation.

    Returns:
        LocalTaskQueue | CloudTaskQueue: The task queue client depending on the environment.
    """
    is_local = "K_SERVICE" not in os.environ
    if is_local:
        return LocalTaskQueue()
    return CloudTaskQueue()
