from unittest.mock import patch

import httpx
import pytest
import respx

from src.exceptions import MondayGraphQLError
from src.monday_client import MondayClient


@pytest.fixture
def client():
    return MondayClient("test_token")


@respx.mock
@pytest.mark.asyncio
async def test_successful_query(client):
    respx.post("https://api.monday.com/v2").respond(
        json={"data": {"boards": [{"id": "123"}]}}
    )
    res = await client.execute_query("{ boards { id } }")
    assert res["data"]["boards"][0]["id"] == "123"


@respx.mock
@pytest.mark.asyncio
async def test_200_ok_graphql_error(client):
    respx.post("https://api.monday.com/v2").respond(
        status_code=200, json={"errors": [{"message": "Invalid query"}]}
    )
    with pytest.raises(MondayGraphQLError) as exc:
        await client.execute_query("invalid")
    assert exc.value.errors[0]["message"] == "Invalid query"
    assert exc.value.data is None


@respx.mock
@pytest.mark.asyncio
async def test_partial_success(client):
    respx.post("https://api.monday.com/v2").respond(
        status_code=200,
        json={"data": {"success": True}, "errors": [{"message": "Partial failure"}]},
    )
    with pytest.raises(MondayGraphQLError) as exc:
        await client.execute_query("mutation")

    # Caller should be able to extract the successful data
    assert exc.value.errors[0]["message"] == "Partial failure"
    assert exc.value.data == {"success": True}


@respx.mock
@pytest.mark.asyncio
@patch("src.monday_client.asyncio.sleep")
async def test_rate_limit_retry_429(mock_sleep, client):
    route = respx.post("https://api.monday.com/v2")

    # Simulate a 429 followed by a success
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "5"}, json={}),
        httpx.Response(200, json={"data": {"success": True}}),
    ]

    res = await client.execute_query("{ query }")
    assert res["data"]["success"] is True
    mock_sleep.assert_called_once_with(5)


@respx.mock
@pytest.mark.asyncio
async def test_idempotency_key(client):
    def check_headers(request):
        assert "Idempotency-Key" in request.headers
        assert request.headers["Idempotency-Key"] == "uuid-1234"
        return httpx.Response(200, json={"data": {"success": True}})

    respx.post("https://api.monday.com/v2").mock(side_effect=check_headers)
    res = await client.execute_query("mutation", idempotency_key="uuid-1234")
    assert res["data"]["success"] is True
