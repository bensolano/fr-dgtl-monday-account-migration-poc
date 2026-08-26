from unittest.mock import MagicMock, patch

import pytest

from src.engines.job_engine import JobEngine


@pytest.fixture
def mock_gcp_clients():
    with (
        patch("src.engines.job_engine.firestore.Client") as mock_db,
        patch("src.engines.job_engine.storage.Client") as mock_storage,
        patch(
            "src.engines.job_engine.secretmanager.SecretManagerServiceClient"
        ) as mock_secret,
    ):
        yield mock_db, mock_storage, mock_secret


def test_job_engine_init(mock_gcp_clients):
    engine = JobEngine(project_id="test-proj", reports_bucket="test-bucket")
    assert engine.project_id == "test-proj"
    assert engine.reports_bucket == "test-bucket"
    assert engine.has_firestore() is True


def test_job_engine_set_job_status(mock_gcp_clients):
    mock_db, _, _ = mock_gcp_clients
    mock_db_instance = MagicMock()
    mock_db.return_value = mock_db_instance

    mock_doc = MagicMock()
    mock_db_instance.collection.return_value.document.return_value = mock_doc

    engine = JobEngine()
    engine.set_job_status("job-123", "RUNNING")

    mock_db_instance.collection.assert_called_with("jobs")
    mock_doc.set.assert_called_once()
    args, kwargs = mock_doc.set.call_args
    assert args[0]["status"] == "RUNNING"
    assert kwargs["merge"] is True


def test_job_engine_get_job(mock_gcp_clients):
    mock_db, _, _ = mock_gcp_clients
    mock_db_instance = MagicMock()
    mock_db.return_value = mock_db_instance

    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"status": "COMPLETED"}
    mock_db_instance.collection.return_value.document.return_value.get.return_value = (
        mock_doc
    )

    engine = JobEngine()
    result = engine.get_job("job-123")
    assert result == {"status": "COMPLETED"}


@pytest.mark.asyncio
@patch("src.engines.job_engine.MondayClient")
@patch("src.engines.job_engine.DiscoveryEngine")
@patch("src.engines.job_engine.ClassificationEngine")
@patch("src.engines.job_engine.ReportEngine")
async def test_execute_discovery_job(
    mock_report_engine,
    mock_class_engine,
    mock_disc_engine,
    mock_monday_client,
    mock_gcp_clients,
):
    _mock_db, mock_storage, mock_secret = mock_gcp_clients

    # Mock Secret Manager
    mock_secret_instance = MagicMock()
    mock_secret.return_value = mock_secret_instance
    mock_secret_response = MagicMock()
    mock_secret_response.payload.data.decode.return_value = "fake_api_key"
    mock_secret_instance.access_secret_version.return_value = mock_secret_response

    # Mock Discovery
    mock_disc_instance = MagicMock()
    mock_disc_engine.return_value = mock_disc_instance
    # Make discover_full_account an async mock return value
    async def mock_discover(*args, **kwargs):
        return {"workspaces": []}
    mock_disc_instance.discover_full_account.side_effect = mock_discover

    # Mock Classification
    mock_class_instance = MagicMock()
    mock_class_engine.return_value = mock_class_instance
    mock_class_instance.process_inventory.return_value = {"workspaces": []}

    # Mock Report
    mock_rep_instance = MagicMock()
    mock_report_engine.return_value = mock_rep_instance
    mock_rep_instance.generate_markdown_report.return_value = "# Report"

    # Mock Storage
    mock_storage_instance = MagicMock()
    mock_storage.return_value = mock_storage_instance

    engine = JobEngine()

    # Avoid file writing in test
    with patch("builtins.open"), patch("json.dump"):
        await engine.execute_discovery_job("job-123")

    mock_secret_instance.access_secret_version.assert_called_once()
    mock_disc_instance.discover_full_account.assert_called_once()
    mock_class_instance.process_inventory.assert_called_once()
    mock_rep_instance.save_report.assert_called_once()
    mock_storage_instance.bucket.assert_called_once()
