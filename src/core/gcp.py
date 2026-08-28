import datetime
import json
import logging
import os
from typing import Any

from google.cloud import run_v2, secretmanager, storage

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "local-dev-project")
REGION = os.environ.get("REGION", "europe-west1")
REPORTS_BUCKET = os.environ.get("REPORTS_BUCKET", "local-dev-reports-bucket")
DISCOVERY_JOB_NAME = os.environ.get("DISCOVERY_JOB_NAME")


class GCPClients:
    def __init__(self) -> None:
        try:
            self.storage_client = storage.Client(project=PROJECT_ID)
            self.secret_client = secretmanager.SecretManagerServiceClient()
            self.run_client = run_v2.JobsClient()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to initialize GCP clients (ensure ADC is set): {e}")
            self.storage_client = None
            self.secret_client = None
            self.run_client = None


gcp_clients = GCPClients()


def store_job_secrets(
    job_id: str, source_api_key: str, dest_api_key: str | None = None
) -> None:
    if not gcp_clients.secret_client:
        return

    parent = f"projects/{PROJECT_ID}"

    # Source Key
    source_secret_id = f"job-{job_id}-source-key"
    gcp_clients.secret_client.create_secret(
        request={
            "parent": parent,
            "secret_id": source_secret_id,
            "secret": {"replication": {"automatic": {}}},
        }
    )
    gcp_clients.secret_client.add_secret_version(
        request={
            "parent": f"{parent}/secrets/{source_secret_id}",
            "payload": {"data": source_api_key.encode("UTF-8")},
        }
    )

    # Destination key if provided
    if dest_api_key:
        dest_secret_id = f"job-{job_id}-dest-key"
        gcp_clients.secret_client.create_secret(
            request={
                "parent": parent,
                "secret_id": dest_secret_id,
                "secret": {"replication": {"automatic": {}}},
            }
        )
        gcp_clients.secret_client.add_secret_version(
            request={
                "parent": f"{parent}/secrets/{dest_secret_id}",
                "payload": {"data": dest_api_key.encode("UTF-8")},
            }
        )


def get_dest_api_key(job_id: str) -> str:
    if not gcp_clients.secret_client:
        raise RuntimeError("Secret Manager client not configured.")

    name = f"projects/{PROJECT_ID}/secrets/job-{job_id}-dest-key/versions/latest"
    response = gcp_clients.secret_client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def trigger_cloud_run_discovery_job(job_id: str) -> bool:
    if not gcp_clients.run_client or not DISCOVERY_JOB_NAME:
        logger.warning(
            f"Cloud Run Job client or DISCOVERY_JOB_NAME not configured. Cannot trigger job {job_id}."
        )
        return False

    name = f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{DISCOVERY_JOB_NAME}"
    request = run_v2.RunJobRequest(
        name=name,
        overrides={
            "container_overrides": [{"env": [{"name": "JOB_ID", "value": job_id}]}]
        },
    )

    try:
        operation = gcp_clients.run_client.run_job(request=request)
        logger.info(
            f"Triggered Cloud Run Job for {job_id}. Operation: {operation.operation.name}"
        )
        return True
    except Exception as e:
        logger.error(f"Failed to trigger Cloud Run Job for {job_id}: {e}")
        raise


def get_inventory(job_id: str) -> dict[str, Any]:
    if not gcp_clients.storage_client:
        raise RuntimeError("Storage client unconfigured.")

    bucket = gcp_clients.storage_client.bucket(REPORTS_BUCKET)
    inventory_blob = bucket.blob(f"reports/{job_id}/inventory.json")

    if not inventory_blob.exists():
        raise FileNotFoundError("Classified inventory not found in GCS.")

    return json.loads(inventory_blob.download_as_string())


def get_report_signed_url(report_gcs_path: str) -> str:
    if not gcp_clients.storage_client:
        raise RuntimeError("Storage client unconfigured.")
    bucket = gcp_clients.storage_client.bucket(REPORTS_BUCKET)
    blob = bucket.blob(report_gcs_path)

    return blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(minutes=15),
        method="GET",
    )


def get_report_bytes(report_gcs_path: str) -> bytes:
    if not gcp_clients.storage_client:
        raise RuntimeError("Storage client unconfigured.")
    bucket = gcp_clients.storage_client.bucket(REPORTS_BUCKET)
    blob = bucket.blob(report_gcs_path)
    return blob.download_as_bytes()
