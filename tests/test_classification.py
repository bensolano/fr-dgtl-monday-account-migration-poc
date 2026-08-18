import pytest

from src.classification import ClassificationEngine


@pytest.fixture
def engine():
    return ClassificationEngine()


def test_classify_standard_objects(engine):
    """Test that standard structural objects are marked full."""
    ws_result = engine.classify_workspace({"id": "1"})
    assert ws_result["classification"] == "full"
    assert ws_result["caveat"] is None

    board_result = engine.classify_board({"id": "2", "board_kind": "public"})
    assert board_result["classification"] == "full"

    group_result = engine.classify_group({"id": "3"})
    assert group_result["classification"] == "full"

    item_result = engine.classify_item({"id": "4"})
    assert item_result["classification"] == "full"


def test_classify_board_share(engine):
    """Test that 'share' boards get a specific caveat."""
    result = engine.classify_board({"id": "2", "board_kind": "share"})
    assert result["classification"] == "full"
    assert "cannot be explicitly created" in result["caveat"]


def test_classify_columns(engine):
    """Test column type capability rules."""
    # Text (Full)
    txt_res = engine.classify_column({"type": "text"})
    assert txt_res["classification"] == "full"

    # Formula (Partial)
    form_res = engine.classify_column({"type": "formula"})
    assert form_res["classification"] == "partial"
    assert "cross-board dependencies" in form_res["caveat"]

    # Board Relation / Connect Boards (Partial)
    rel_res = engine.classify_column({"type": "board_relation"})
    assert rel_res["classification"] == "partial"
    assert "connected board to be migrated first" in rel_res["caveat"]

    # Dependency (Manual Only)
    dep_res = engine.classify_column({"type": "dependency"})
    assert dep_res["classification"] == "manual_only"
    assert "lack full write support" in dep_res["caveat"]


def test_process_inventory(engine):
    """Test the full tree iterator mutates correctly."""
    inventory = {
        "workspaces": [{"id": "w1"}],
        "boards": [{"id": "b1", "board_kind": "share"}],
        "columns": [{"type": "formula"}],
        "items": [],
    }

    processed = engine.process_inventory(inventory)

    assert processed["workspaces"][0]["classification"] == "full"
    assert processed["boards"][0]["classification"] == "full"
    assert processed["boards"][0]["caveat"] is not None
    assert processed["columns"][0]["classification"] == "partial"
