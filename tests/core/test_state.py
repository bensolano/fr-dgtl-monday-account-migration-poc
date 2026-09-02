from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.state import StateManager


@pytest.fixture
def mock_gcp_clients():
    mock_gcp = MagicMock()
    mock_db = MagicMock()  # Reference builders are sync
    mock_gcp.firestore_client = mock_db
    yield mock_gcp


def test_state_manager_init_success(mock_gcp_clients):
    manager = StateManager(gcp_clients=mock_gcp_clients, project_id="test-project")
    assert manager.db is not None
    assert manager.project_id == "test-project"


@pytest.mark.asyncio
async def test_get_job_exists(mock_gcp_clients):
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        "job_id": "job123",
        "status": "PENDING",
        "operator_email": "test@test.com",
        "source_account": {"secret_ref": "sec1"},
        "dest_account": {"secret_ref": "sec2"},
    }

    mock_collection = MagicMock()
    mock_document = AsyncMock()

    mock_gcp_clients.firestore_client.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_document
    mock_document.get.return_value = mock_doc

    manager = StateManager(gcp_clients=mock_gcp_clients)
    result = await manager.get_job("job123")

    assert result.status == "PENDING"
    assert result.job_id == "job123"
    mock_gcp_clients.firestore_client.collection.assert_called_with("jobs")
    mock_collection.document.assert_called_with("job123")


@pytest.mark.asyncio
async def test_get_dest_id_exists(mock_gcp_clients):
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"dest_id": "dest456"}

    mock_jobs = MagicMock()
    mock_job_doc = MagicMock()
    mock_id_map = MagicMock()
    mock_id_doc = AsyncMock()

    mock_gcp_clients.firestore_client.collection.return_value = mock_jobs
    mock_jobs.document.return_value = mock_job_doc
    mock_job_doc.collection.return_value = mock_id_map
    mock_id_map.document.return_value = mock_id_doc
    mock_id_doc.get.return_value = mock_doc

    manager = StateManager(gcp_clients=mock_gcp_clients)
    result = await manager.get_dest_id("job123", "board", "src123")

    assert result == "dest456"
    mock_id_map.document.assert_called_with("board_src123")


@pytest.mark.asyncio
async def test_set_dest_id(mock_gcp_clients):
    mock_jobs = MagicMock()
    mock_job_doc = MagicMock()
    mock_id_map = MagicMock()
    mock_id_doc = AsyncMock()

    mock_gcp_clients.firestore_client.collection.return_value = mock_jobs
    mock_jobs.document.return_value = mock_job_doc
    mock_job_doc.collection.return_value = mock_id_map
    mock_id_map.document.return_value = mock_id_doc

    manager = StateManager(gcp_clients=mock_gcp_clients)
    with patch("src.core.state.firestore") as mock_firestore_module:
        mock_firestore_module.SERVER_TIMESTAMP = "TIMESTAMP"
        await manager.set_dest_id("job123", "board", "src123", "dest456")

    mock_id_doc.set.assert_called_once_with(
        {
            "source_id": "src123",
            "dest_id": "dest456",
            "entity_type": "board",
            "created_at": "TIMESTAMP",
        }
    )
