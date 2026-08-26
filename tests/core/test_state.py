from unittest.mock import MagicMock, patch

import pytest

from src.core.state import StateManager


@pytest.fixture
def mock_firestore_client():
    with patch("src.core.state.firestore.Client") as mock_client:
        mock_db = MagicMock()
        mock_client.return_value = mock_db
        yield mock_db


def test_state_manager_init_success(mock_firestore_client):
    manager = StateManager(project_id="test-project")
    assert manager.db is not None
    assert manager.project_id == "test-project"


def test_get_job_exists(mock_firestore_client):
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"status": "PENDING"}

    mock_collection = MagicMock()
    mock_document = MagicMock()

    mock_firestore_client.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_document
    mock_document.get.return_value = mock_doc

    manager = StateManager()
    result = manager.get_job("job123")

    assert result == {"status": "PENDING"}
    mock_firestore_client.collection.assert_called_with("jobs")
    mock_collection.document.assert_called_with("job123")


def test_get_dest_id_exists(mock_firestore_client):
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"dest_id": "dest456"}

    mock_jobs = MagicMock()
    mock_job_doc = MagicMock()
    mock_id_map = MagicMock()
    mock_id_doc = MagicMock()

    mock_firestore_client.collection.return_value = mock_jobs
    mock_jobs.document.return_value = mock_job_doc
    mock_job_doc.collection.return_value = mock_id_map
    mock_id_map.document.return_value = mock_id_doc
    mock_id_doc.get.return_value = mock_doc

    manager = StateManager()
    result = manager.get_dest_id("job123", "board", "src123")

    assert result == "dest456"
    mock_id_map.document.assert_called_with("board_src123")


def test_set_dest_id(mock_firestore_client):
    mock_jobs = MagicMock()
    mock_job_doc = MagicMock()
    mock_id_map = MagicMock()
    mock_id_doc = MagicMock()

    mock_firestore_client.collection.return_value = mock_jobs
    mock_jobs.document.return_value = mock_job_doc
    mock_job_doc.collection.return_value = mock_id_map
    mock_id_map.document.return_value = mock_id_doc

    manager = StateManager()
    with patch("src.core.state.firestore") as mock_firestore_module:
        mock_firestore_module.SERVER_TIMESTAMP = "TIMESTAMP"
        manager.set_dest_id("job123", "board", "src123", "dest456")

    mock_id_doc.set.assert_called_once_with(
        {
            "source_id": "src123",
            "dest_id": "dest456",
            "entity_type": "board",
            "created_at": "TIMESTAMP",
        }
    )
