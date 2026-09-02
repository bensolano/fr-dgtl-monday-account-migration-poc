import asyncio
import datetime
import json
import logging
from typing import Any

import google.auth
from google.cloud import storage
from google.cloud.firestore import AsyncClient as FirestoreAsyncClient
from google.cloud.run_v2 import JobsAsyncClient, RunJobRequest
from google.cloud.secretmanager import SecretManagerServiceAsyncClient
from google.cloud.tasks_v2 import CloudTasksAsyncClient

from src.core.config import settings

logger = logging.getLogger(__name__)

PROJECT_ID = settings.PROJECT_ID
REGION = settings.REGION
REPORTS_BUCKET = settings.REPORTS_BUCKET
DISCOVERY_JOB_NAME = settings.DISCOVERY_JOB_NAME


class GCPClients:
    def __init__(self) -> None:
        self._credentials = None
        self._storage_client = None
        self._secret_client = None
        self._run_client = None
        self._firestore_client = None
        self._tasks_client = None

    @property
    def credentials(self):
        if self._credentials is None:
            try:
                self._credentials, _ = google.auth.default()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to fetch default credentials: {e}")
        return self._credentials

    @property
    def storage_client(self):
        if self._storage_client is None:
            try:
                self._storage_client = storage.Client(
                    project=PROJECT_ID, credentials=self.credentials
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to initialize Storage client: {e}")
        return self._storage_client

    @property
    def secret_client(self):
        if self._secret_client is None:
            try:
                self._secret_client = SecretManagerServiceAsyncClient(
                    credentials=self.credentials
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to initialize Secret Manager client: {e}")
        return self._secret_client

    @property
    def run_client(self):
        if self._run_client is None:
            try:
                self._run_client = JobsAsyncClient(credentials=self.credentials)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to initialize Cloud Run client: {e}")
        return self._run_client

    @property
    def firestore_client(self):
        if self._firestore_client is None:
            try:
                self._firestore_client = FirestoreAsyncClient(
                    project=PROJECT_ID, credentials=self.credentials
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to initialize Firestore client: {e}")
        return self._firestore_client

    @property
    def tasks_client(self):
        if self._tasks_client is None:
            try:
                self._tasks_client = CloudTasksAsyncClient(credentials=self.credentials)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to initialize Cloud Tasks client: {e}")
        return self._tasks_client


gcp_clients = GCPClients()


async def store_job_secrets(job_id: str, source_api_key: str) -> None:
    if not gcp_clients.secret_client:
        logger.warning(
            f"Secret Manager not available. Storing source secret for job {job_id} in memory."
        )
        from src.api.dependencies import get_state_manager

        state_manager = get_state_manager()
        if not hasattr(state_manager, "_local_memory_secrets"):
            state_manager._local_memory_secrets = {}
        if job_id not in state_manager._local_memory_secrets:
            state_manager._local_memory_secrets[job_id] = {}
        state_manager._local_memory_secrets[job_id]["source_key"] = source_api_key
        return

    parent = f"projects/{PROJECT_ID}"

    # Source Key
    source_secret_id = f"job-{job_id}-source-key"
    await gcp_clients.secret_client.create_secret(
        request={
            "parent": parent,
            "secret_id": source_secret_id,
            "secret": {"replication": {"automatic": {}}},
        }
    )
    await gcp_clients.secret_client.add_secret_version(
        request={
            "parent": f"{parent}/secrets/{source_secret_id}",
            "payload": {"data": source_api_key.encode("UTF-8")},
        }
    )


async def store_dest_secret(job_id: str, dest_api_key: str) -> None:
    if not gcp_clients.secret_client:
        logger.warning(
            f"Secret Manager not available. Storing dest secret for job {job_id} in memory."
        )
        from src.api.dependencies import get_state_manager

        state_manager = get_state_manager()
        if not hasattr(state_manager, "_local_memory_secrets"):
            state_manager._local_memory_secrets = {}
        if job_id not in state_manager._local_memory_secrets:
            state_manager._local_memory_secrets[job_id] = {}
        state_manager._local_memory_secrets[job_id]["dest_key"] = dest_api_key
        return

    parent = f"projects/{PROJECT_ID}"
    dest_secret_id = f"job-{job_id}-dest-key"
    await gcp_clients.secret_client.create_secret(
        request={
            "parent": parent,
            "secret_id": dest_secret_id,
            "secret": {"replication": {"automatic": {}}},
        }
    )
    await gcp_clients.secret_client.add_secret_version(
        request={
            "parent": f"{parent}/secrets/{dest_secret_id}",
            "payload": {"data": dest_api_key.encode("UTF-8")},
        }
    )


async def delete_job_secrets(job_id: str) -> None:
    if not gcp_clients.secret_client:
        return

    parent = f"projects/{PROJECT_ID}"
    for suffix in ["source-key", "dest-key"]:
        secret_name = f"{parent}/secrets/job-{job_id}-{suffix}"
        try:
            await gcp_clients.secret_client.delete_secret(request={"name": secret_name})
            logger.info(f"Deleted secret {secret_name}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to delete secret {secret_name}: {e}")


async def delete_gcs_artifacts(job_id: str) -> None:
    if not gcp_clients.storage_client:
        return

    def _delete_blobs():
        bucket = gcp_clients.storage_client.bucket(REPORTS_BUCKET)
        blobs = bucket.list_blobs(prefix=f"reports/{job_id}/")
        for blob in blobs:
            try:
                blob.delete()
                logger.info(f"Deleted GCS artifact {blob.name}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to delete GCS artifact {blob.name}: {e}")

        # Also delete dag storage if they use a separate prefix like dags/{job_id}
        # It might be in the same bucket.
        blobs = bucket.list_blobs(prefix=f"dags/{job_id}/")
        for blob in blobs:
            try:
                blob.delete()
                logger.info(f"Deleted GCS artifact {blob.name}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to delete GCS artifact {blob.name}: {e}")

    await asyncio.to_thread(_delete_blobs)


async def get_dest_api_key(job_id: str) -> str:
    if not gcp_clients.secret_client:
        logger.warning(
            f"Secret Manager not available. Retrieving dest secret for job {job_id} from memory."
        )
        from src.api.dependencies import get_state_manager

        state_manager = get_state_manager()
        if (
            hasattr(state_manager, "_local_memory_secrets")
            and job_id in state_manager._local_memory_secrets
        ):
            dest_key = state_manager._local_memory_secrets[job_id].get("dest_key")
            if dest_key:
                return dest_key
        raise RuntimeError(
            "Secret Manager client not configured and secret not in local memory."
        )

    name = f"projects/{PROJECT_ID}/secrets/job-{job_id}-dest-key/versions/latest"
    response = await gcp_clients.secret_client.access_secret_version(
        request={"name": name}
    )
    return response.payload.data.decode("UTF-8")


async def trigger_cloud_run_discovery_job(job_id: str) -> bool:
    if not gcp_clients.run_client or not DISCOVERY_JOB_NAME:
        logger.warning(
            f"Cloud Run Job client or DISCOVERY_JOB_NAME not configured. Cannot trigger job {job_id}."
        )
        return False

    name = f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{DISCOVERY_JOB_NAME}"
    request = RunJobRequest(
        name=name,
        overrides={
            "container_overrides": [{"env": [{"name": "JOB_ID", "value": job_id}]}]
        },
    )

    try:
        operation = await gcp_clients.run_client.run_job(request=request)
        logger.info(
            f"Triggered Cloud Run Job for {job_id}. Operation: {operation.operation.name}"
        )
        return True
    except Exception as e:
        logger.error(f"Failed to trigger Cloud Run Job for {job_id}: {e}")
        raise


async def get_inventory(job_id: str) -> dict[str, Any]:
    if not gcp_clients.storage_client:
        raise RuntimeError("Storage client unconfigured.")

    def _download():
        bucket = gcp_clients.storage_client.bucket(REPORTS_BUCKET)
        inventory_blob = bucket.blob(f"reports/{job_id}/inventory.json")

        if not inventory_blob.exists():
            raise FileNotFoundError("Classified inventory not found in GCS.")

        return json.loads(inventory_blob.download_as_string())

    return await asyncio.to_thread(_download)


async def get_report_signed_url(report_gcs_path: str) -> str:
    if not gcp_clients.storage_client:
        raise RuntimeError("Storage client unconfigured.")

    def _generate():
        bucket = gcp_clients.storage_client.bucket(REPORTS_BUCKET)
        blob = bucket.blob(report_gcs_path)

        return blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=15),
            method="GET",
        )

    return await asyncio.to_thread(_generate)


async def get_report_bytes(report_gcs_path: str) -> bytes:
    if not gcp_clients.storage_client:
        raise RuntimeError("Storage client unconfigured.")

    def _download():
        bucket = gcp_clients.storage_client.bucket(REPORTS_BUCKET)
        blob = bucket.blob(report_gcs_path)
        return blob.download_as_bytes()

    return await asyncio.to_thread(_download)
