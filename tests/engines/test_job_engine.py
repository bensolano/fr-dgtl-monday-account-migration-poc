from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.fixture
def mock_classifier():
    classifier = MagicMock()
    classifier.process_inventory.return_value = {"workspaces": []}
    return classifier


@pytest.fixture
def mock_reporter():
    reporter = MagicMock()
    reporter.generate_markdown_report.return_value = "# Report"
    return reporter


@pytest.fixture
def mock_discovery_factory():
    discoverer = AsyncMock()
    discoverer.discover_full_account.return_value = {"workspaces": []}

    def factory(api_key: str):
        return discoverer

    # Attach the discoverer to the factory so tests can assert on it
    factory.discoverer = discoverer
    return factory


def test_job_engine_init(
    mock_gcp_clients, mock_classifier, mock_reporter, mock_discovery_factory
):
    engine = JobEngine(
        classifier=mock_classifier,
        reporter=mock_reporter,
        discovery_factory=mock_discovery_factory,
        project_id="test-proj",
        reports_bucket="test-bucket",
    )
    assert engine.project_id == "test-proj"
    assert engine.reports_bucket == "test-bucket"
    assert engine.has_firestore() is True


def test_job_engine_set_job_status(
    mock_gcp_clients, mock_classifier, mock_reporter, mock_discovery_factory
):
    mock_db, _, _ = mock_gcp_clients
    mock_db_instance = MagicMock()
    mock_db.return_value = mock_db_instance

    mock_doc = MagicMock()
    mock_db_instance.collection.return_value.document.return_value = mock_doc

    engine = JobEngine(
        classifier=mock_classifier,
        reporter=mock_reporter,
        discovery_factory=mock_discovery_factory,
    )
    engine.set_job_status("job-123", "RUNNING")

    mock_db_instance.collection.assert_called_with("jobs")
    mock_doc.set.assert_called_once()
    args, kwargs = mock_doc.set.call_args
    assert args[0]["status"] == "RUNNING"
    assert kwargs["merge"] is True


def test_job_engine_get_job(
    mock_gcp_clients, mock_classifier, mock_reporter, mock_discovery_factory
):
    mock_db, _, _ = mock_gcp_clients
    mock_db_instance = MagicMock()
    mock_db.return_value = mock_db_instance

    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"status": "COMPLETED"}
    mock_db_instance.collection.return_value.document.return_value.get.return_value = (
        mock_doc
    )

    engine = JobEngine(
        classifier=mock_classifier,
        reporter=mock_reporter,
        discovery_factory=mock_discovery_factory,
    )
    result = engine.get_job("job-123")
    assert result == {"status": "COMPLETED"}


@pytest.mark.asyncio
async def test_execute_discovery_job(
    mock_gcp_clients, mock_classifier, mock_reporter, mock_discovery_factory
):
    _mock_db, mock_storage, mock_secret = mock_gcp_clients

    # Mock Secret Manager
    mock_secret_instance = MagicMock()
    mock_secret.return_value = mock_secret_instance
    mock_secret_response = MagicMock()
    mock_secret_response.payload.data.decode.return_value = "fake_api_key"
    mock_secret_instance.access_secret_version.return_value = mock_secret_response

    # Mock Storage
    mock_storage_instance = MagicMock()
    mock_storage.return_value = mock_storage_instance

    engine = JobEngine(
        classifier=mock_classifier,
        reporter=mock_reporter,
        discovery_factory=mock_discovery_factory,
    )

    # Avoid file writing in test
    with patch("builtins.open"), patch("json.dump"):
        await engine.execute_discovery_job("job-123")

    mock_secret_instance.access_secret_version.assert_called_once()

    # Assert on our injected mocks instead of patched globals!
    mock_discovery_factory.discoverer.discover_full_account.assert_called_once()
    mock_classifier.process_inventory.assert_called_once()
    mock_reporter.save_report.assert_called_once()

    mock_storage_instance.bucket.assert_called_once()
