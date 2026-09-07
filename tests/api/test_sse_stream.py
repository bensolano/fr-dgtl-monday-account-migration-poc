from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from src.api.routers.jobs import stream_inventory
from src.domain.models import JobStatusResponse


@pytest.mark.asyncio
async def test_stream_inventory_uses_named_database_and_headers():
    mock_job_service = AsyncMock()
    mock_job_service.get_job.return_value = {
        "job_id": "test-job-123",
        "status": "EXECUTING",
    }

    mock_request = AsyncMock()
    mock_request.is_disconnected.return_value = True

    with patch("google.cloud.firestore.Client") as mock_firestore_cls, \
         patch("src.infrastructure.gcp.services.gcp_clients") as mock_gcp_clients:
        mock_gcp_clients.credentials = MagicMock()
        mock_firestore_instance = MagicMock()
        mock_firestore_cls.return_value = mock_firestore_instance

        mock_watch = MagicMock()
        mock_inventory_ref = MagicMock()
        mock_inventory_ref.on_snapshot.return_value = mock_watch
        mock_firestore_instance.collection.return_value.document.return_value.collection.return_value = mock_inventory_ref

        response = await stream_inventory(
            job_id="test-job-123",
            request=mock_request,
            job_engine=mock_job_service,
        )

        # Verify response headers
        assert response.status_code == 200
        assert response.media_type == "text/event-stream"
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["connection"] == "keep-alive"
        assert response.headers["x-accel-buffering"] == "no"

        # Verify firestore.Client was called with database=settings.DATABASENAME ("migration-poc")
        mock_firestore_cls.assert_called_once()
        _, kwargs = mock_firestore_cls.call_args
        assert kwargs.get("database") == "migration-poc"


