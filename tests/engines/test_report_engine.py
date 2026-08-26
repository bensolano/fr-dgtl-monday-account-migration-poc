import os

import pytest

from src.engines.report_engine import ReportEngine


@pytest.fixture
def generator():
    return ReportEngine()


@pytest.fixture
def mock_inventory():
    return {
        "workspaces": [
            {"id": "w1", "name": "WS1", "classification": "full", "caveat": None}
        ],
        "boards": [
            {"id": "b1", "name": "Board 1", "classification": "full", "caveat": None},
            {
                "id": "b2",
                "name": "Shared Board",
                "classification": "full",
                "caveat": "Cannot be created as share via API.",
            },
        ],
        "columns": [
            {"id": "c1", "title": "Status", "classification": "full", "caveat": None},
            {
                "id": "c2",
                "title": "Mirror Col",
                "classification": "partial",
                "caveat": "Requires connect board first.",
            },
            {
                "id": "c3",
                "title": "Dep Col",
                "classification": "manual_only",
                "caveat": "No write API.",
            },
        ],
        "items": [
            {"id": "i1", "name": "Item 1", "classification": "full", "caveat": None}
        ],
    }


def test_generate_markdown_report_structure(generator, mock_inventory):
    """Test that the report contains the correct headers and tables."""
    report = generator.generate_markdown_report(mock_inventory)

    # Check headers
    assert "# Monday.com Pre-Migration Assessment Report" in report
    assert "## 1. Executive Summary" in report
    assert "## 2. Caveats & Manual Interventions" in report

    # Check table rows exist and counts are correct
    assert "| **Boards** | 2 | 2 | 0 | 0 |" in report
    assert "| **Columns** | 3 | 1 | 1 | 1 |" in report
    assert "| **Items** | 1 | 1 | 0 | 0 |" in report


def test_generate_markdown_report_caveats(generator, mock_inventory):
    """Test that items with caveats are correctly listed in the caveats section."""
    report = generator.generate_markdown_report(mock_inventory)

    # Board caveat
    assert "- **Shared Board** (ID: `b2`) `[FULL]`:" in report
    assert "Cannot be created as share via API." in report

    # Column caveats
    assert "- **Mirror Col** (ID: `c2`) `[PARTIAL]`:" in report
    assert "Requires connect board first." in report

    assert "- **Dep Col** (ID: `c3`) `[MANUAL_ONLY]`:" in report
    assert "No write API." in report


def test_generate_markdown_report_appendix(generator, mock_inventory):
    """Test that the appendix correctly logs boards."""
    report = generator.generate_markdown_report(mock_inventory)

    assert "## 3. Appendix: All Discovered Boards" in report
    assert "| Board 1 | `b1` | FULL |" in report
    assert "| Shared Board | `b2` | FULL |" in report


def test_generate_markdown_report_no_caveats(generator):
    """Test the report output when no caveats are present."""
    perfect_inventory = {
        "boards": [
            {"id": "b1", "name": "Board 1", "classification": "full", "caveat": None}
        ]
    }
    report = generator.generate_markdown_report(perfect_inventory)

    assert "No partial or manual-only objects were detected." in report


def test_save_report(generator, tmp_path):
    """Test that the report saves correctly to the filesystem."""
    output_file = tmp_path / "test_report.md"
    content = "# Test Report"

    generator.save_report(content, str(output_file))

    assert os.path.exists(output_file)
    with open(output_file, "r") as f:
        saved_content = f.read()
    assert saved_content == "# Test Report"
