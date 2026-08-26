from src.engines.orchestrator_engine import OrchestratorEngine


def test_build_dag_filters_manual_only():
    inventory = {
        "workspaces": [
            {"id": "ws1", "name": "Valid WS", "classification": "full"},
            {"id": "ws2", "name": "Invalid WS", "classification": "manual_only"},
        ],
        "boards": [{"id": "b1", "name": "Valid Board", "classification": "partial"}],
        "columns": [{"id": "c1", "title": "Dep Col", "classification": "manual_only"}],
    }

    engine = OrchestratorEngine()
    dag = engine.build_dag(inventory)

    assert len(dag["workspaces"]) == 1
    assert dag["workspaces"][0]["source_id"] == "ws1"

    assert len(dag["boards"]) == 1
    assert dag["boards"][0]["source_id"] == "b1"

    assert len(dag["columns"]) == 0
    assert len(dag["groups"]) == 0
    assert len(dag["items"]) == 0


def test_build_dag_order():
    engine = OrchestratorEngine()
    # The dictionary order is guaranteed to match stage_order in output
    assert engine.stage_order == ["workspaces", "boards", "groups", "columns", "items"]
