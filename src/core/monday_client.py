import asyncio
import logging
import re
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.core.exceptions import (
    MondayApiHttpError,
    MondayGraphQLError,
    MondayRateLimitError,
)

logger = logging.getLogger(__name__)


class MondayClient:
    API_URL = "https://api.monday.com/v2"

    def __init__(self, api_key: str):
        """
        Initializes the MondayClient.

        Args:
            api_key (str): The Monday.com API token used for authentication.
        """
        self.headers = {
            "Authorization": api_key,
            "API-Version": "2026-07",
            "Content-Type": "application/json",
        }

    async def execute_query(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        distributed: bool = False,
    ) -> dict[str, Any]:
        """
        Executes a GraphQL query.

        Args:
            query: The GraphQL query string.
            variables: Query variables.
            idempotency_key: UUID for preventing duplicate side effects.
            distributed: If True, raises MondayRateLimitError instead of sleeping on 429s.
        """
        try:
            return await self._execute_query_with_retries(
                query, variables, idempotency_key, distributed
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise MondayApiHttpError(
                    "Authentication failed: Invalid or expired Monday API token.", 401
                ) from e
            elif e.response.status_code == 403:
                raise MondayApiHttpError(
                    "Authorization failed: The provided token does not have the required permissions.",
                    403,
                ) from e
            elif e.response.status_code == 404:
                raise MondayApiHttpError("Resource not found.", 404) from e
            else:
                raise MondayApiHttpError(
                    f"Monday API returned an HTTP error: {e.response.status_code} {e.response.reason_phrase}.",
                    e.response.status_code,
                ) from e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    async def _execute_query_with_retries(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        distributed: bool = False,
    ) -> dict[str, Any]:
        rate_limit_retries = 0
        max_rate_limit_retries = 5

        while True:
            payload = {"query": query, "variables": variables or {}}
            request_headers = dict(self.headers)

            if idempotency_key:
                request_headers["Idempotency-Key"] = idempotency_key
                if rate_limit_retries > 0:
                    logger.info(f"Retrying with Idempotency-Key: {idempotency_key}")

            async with httpx.AsyncClient(
                headers=request_headers, timeout=60.0
            ) as client:
                response = await client.post(self.API_URL, json=payload)

                if idempotency_key and "idempotency-replayed" in response.headers:
                    logger.info(
                        f"Idempotency-Replayed: {response.headers['idempotency-replayed']}"
                    )

                # 1. Parse Rate Limits
                rate_limit_header = response.headers.get("RateLimit", "")
                retry_s = None
                if "r=0" in rate_limit_header and "t=" in rate_limit_header:
                    t_values = [
                        int(t) for t in re.findall(r"t=(\d+)", rate_limit_header)
                    ]
                    if t_values:
                        retry_s = max(t_values)

                # HTTP 429
                if response.status_code == 429 and not retry_s:
                    retry_s = int(response.headers.get("Retry-After", 60))

                # Raise for other HTTP errors (triggers tenacity retry loop)
                if response.status_code != 429:
                    response.raise_for_status()

                try:
                    data = response.json()
                except ValueError:
                    data = {}

            # 2. Check for GraphQL Rate Limits disguised as 200 OK
            if not retry_s and "errors" in data:
                for error in data["errors"]:
                    if "retry_in_seconds" in error.get("extensions", {}):
                        retry_s = max(
                            retry_s or 0, error["extensions"]["retry_in_seconds"]
                        )

            # 3. Handle Rate Limit sleep logic explicitly
            if retry_s is not None:
                if distributed:
                    # In distributed mode (Cloud Tasks), we bubble up to let the dispatcher retry
                    logger.warning(
                        f"Rate limit exceeded (distributed). Requesting requeue in {retry_s}s."
                    )
                    raise MondayRateLimitError(
                        "Rate limit exceeded.", retry_in_seconds=retry_s
                    )

                if rate_limit_retries >= max_rate_limit_retries:
                    raise MondayRateLimitError(
                        f"Max rate limit retries ({max_rate_limit_retries}) exceeded.",
                        retry_in_seconds=retry_s,
                    )
                logger.warning(f"Rate limit exceeded. Sleeping for {retry_s}s...")
                await asyncio.sleep(retry_s)
                rate_limit_retries += 1
                continue

            # 4. Extract complexity metadata for the token bucket sync
            complexity_data = None
            if "data" in data and "complexity" in data["data"]:
                complexity_data = data["data"]["complexity"]

            # 5. Process GraphQL 200 OK Applications Errors
            if "errors" in data:
                has_data = data.get("data") is not None
                if has_data:
                    logger.warning(f"Partial success. GraphQL Errors: {data['errors']}")
                else:
                    logger.error(f"GraphQL Error: {data['errors']}")

                raise MondayGraphQLError(
                    "Monday API GraphQL Error",
                    errors=data["errors"],
                    data=data.get("data"),
                )

            # Attach complexity metadata directly to the root for the caller to sync
            if complexity_data:
                data["_meta_complexity"] = complexity_data

            return data
