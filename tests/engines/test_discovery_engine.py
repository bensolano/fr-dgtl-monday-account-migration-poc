import os

import pytest
import respx

from src.core.monday_client import MondayClient
from src.engines.discovery_engine import DiscoveryEngine


@pytest.fixture
def client():
    return MondayClient("test_token")


@pytest.fixture
def engine(client):
    return DiscoveryEngine(client)


@respx.mock
@pytest.mark.asyncio
async def test_get_workspaces(engine):
    respx.post("https://api.monday.com/v2").respond(
        json={
            "data": {
                "workspaces": [
                    {"id": "1", "name": "Workspace 1", "state": "active"},
                    {"id": "2", "name": "Workspace 2", "state": "active"},
                ]
            }
        }
    )
    workspaces = await engine.get_workspaces()
    assert len(workspaces) == 2
    assert workspaces[0]["id"] == "1"


@respx.mock
@pytest.mark.asyncio
async def test_get_boards(engine):
    respx.post("https://api.monday.com/v2").respond(
        json={
            "data": {
                "boards": [
                    {
                        "id": "100",
                        "name": "Board 1",
                        "type": "board",
                        "board_kind": "public",
                    }
                ]
            }
        }
    )
    boards = await engine.get_boards()
    assert len(boards) == 1
    assert boards[0]["id"] == "100"


@respx.mock
@pytest.mark.asyncio
async def test_get_items_pagination(engine):
    # Mock the initial query returning items and a cursor
    respx.post("https://api.monday.com/v2").mock(
        side_effect=[
            respx.MockResponse(
                json={
                    "data": {
                        "boards": [
                            {
                                "items_page": {
                                    "cursor": "cursor_123",
                                    "items": [{"id": "item1"}, {"id": "item2"}],
                                }
                            }
                        ]
                    }
                }
            ),
            # Mock the next_items_page returning the last item and null cursor
            respx.MockResponse(
                json={
                    "data": {
                        "next_items_page": {
                            "cursor": None,
                            "items": [{"id": "item3"}],
                        }
                    }
                }
            ),
        ]
    )

    items = await engine.get_items("100")
    assert len(items) == 3
    assert items[0]["id"] == "item1"
    assert items[2]["id"] == "item3"


@respx.mock
@pytest.mark.asyncio
async def test_discover_full_account(engine, tmp_path):
    output_path = tmp_path / "test_inventory.json"

    # We will mock the entire sequence
    # Workspaces -> Boards -> Groups -> Columns -> Items

    route = respx.post("https://api.monday.com/v2")

    route.side_effect = [
        # Workspaces
        respx.MockResponse(json={"data": {"workspaces": [{"id": "ws1"}]}}),
        # Boards
        respx.MockResponse(json={"data": {"boards": [{"id": "b1"}]}}),
        # Groups
        respx.MockResponse(json={"data": {"boards": [{"groups": [{"id": "g1"}]}]}}),
        # Columns
        respx.MockResponse(json={"data": {"boards": [{"columns": [{"id": "c1"}]}]}}),
        # Items (no pagination for this mock)
        respx.MockResponse(
            json={
                "data": {
                    "boards": [
                        {"items_page": {"cursor": None, "items": [{"id": "i1"}]}}
                    ]
                }
            }
        ),
    ]

    inventory = await engine.discover_full_account(output_path=str(output_path))

    # Assert return structure
    assert len(inventory["workspaces"]) == 1
    assert len(inventory["boards"]) == 1
    assert len(inventory["groups"]) == 1
    assert len(inventory["columns"]) == 1
    assert len(inventory["items"]) == 1

    # Assert parent linking
    assert inventory["items"][0]["parent_board_id"] == "b1"

    # Assert file was written
    assert os.path.exists(output_path)
