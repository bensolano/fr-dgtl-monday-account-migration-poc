import json
import logging
import os
from typing import Any

from google.cloud import storage

try:
    from google.cloud import tasks_v2
except ImportError:
    tasks_v2 = None

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "local-dev-project")
REGION = os.environ.get("REGION", "europe-west1")
SERVICE_URL = os.environ.get("SERVICE_URL", "https://example.com")
REPORTS_BUCKET = os.environ.get("REPORTS_BUCKET", "local-dev-reports-bucket")


class GCSDagStorage:
    def __init__(self, project_id: str = PROJECT_ID, bucket_name: str = REPORTS_BUCKET):
        self.client = storage.Client(project=project_id)
        self.bucket = self.client.bucket(bucket_name)

    def save_dag(self, job_id: str, dag: dict[str, list[dict[str, Any]]]) -> None:
        blob = self.bucket.blob(f"reports/{job_id}/dag.json")
        blob.upload_from_string(json.dumps(dag), content_type="application/json")

    def load_dag(self, job_id: str) -> dict[str, list[dict[str, Any]]] | None:
        blob = self.bucket.blob(f"reports/{job_id}/dag.json")
        if not blob.exists():
            return None
        return json.loads(blob.download_as_string())


class CloudTaskQueue:
    def __init__(
        self,
        project_id: str = PROJECT_ID,
        region: str = REGION,
        service_url: str = SERVICE_URL,
    ):
        self.project_id = project_id
        self.region = region
        self.service_url = service_url
        self.client = tasks_v2.CloudTasksClient() if tasks_v2 else None

    def enqueue_task(self, job_id: str, stage: str, task: dict[str, Any]) -> None:
        if not self.client:
            return

        queue_name = f"migration-{stage}"
        parent = self.client.queue_path(self.project_id, self.region, queue_name)

        payload_bytes = json.dumps({"job_id": job_id, "task": task}).encode("utf-8")
        task_def = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{self.service_url}/api/v1/worker/{stage}",
                "headers": {"Content-type": "application/json"},
                "body": payload_bytes,
            }
        }
        self.client.create_task(request={"parent": parent, "task": task_def})
