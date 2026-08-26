# Monday.com API Best Practices & Guidelines

Always thoroughly read the official documentation at:
https://developer.monday.com/api-reference/docs/

When developing against the Monday.com API in this project, adhere strictly to the following rules, constraints, limits, and best practices:

## 1. Core API Architecture & Optimization
*   **Request Only What You Need:** Avoid querying unnecessary fields or deeply nested relationships to minimize complexity cost.
*   **Use Fragments:** Utilize GraphQL fragments to query column-specific data efficiently.
*   **Prefer Batching:** Always use the `change_multiple_column_values` mutation instead of firing multiple individual `change_simple_column_value` mutations.
*   **Mandatory Pagination:** Implement cursor-based pagination or the `limit` argument for large datasets.
*   **Never Poll:** Use real-time webhooks to listen for changes on boards instead of periodically polling the API.
*   **Caching:** Implement local caching for static or semi-static data.

## 2. API Coverage Gaps (Aligns with Capability Matrix)
The Monday.com API does not support several features available in the web UI. This aligns with the limitations described in our capability matrix (tagged as `manual_only` or requiring workarounds):
*   **Bulk Operations:** There is no file-based bulk import/update flow or bulk column creation endpoint.
*   **Automations:** The API cannot create, delete, update, or list board automations (recipes).
*   **Trash Management:** The API cannot restore items from the trash or perform bulk trash operations.
*   **Board Conversions:** `board_kind` (public, private, share) is locked at creation and cannot be changed via the API. Classic boards cannot be converted to multi-level boards.
*   **Workdocs Limitations:** No doc-specific webhook events; only Markdown export is supported; no binary image uploads for doc blocks.

## 3. Rate Limits & Complexity Budgets
Monday.com enforces rate limits. All requests (including failed/rate-limited ones) count.
*   **Complexity Limits:** Max 5,000,000 (5M) complexity points per query. Always include the `complexity` field in your GraphQL queries to monitor remaining budget and reset times.
*   **Daily Call Limits:** Varies by tier (e.g., Free/Standard/Basic: 1,000 calls/day; Enterprise: 25,000 soft limit).
*   **Minute & Concurrency Limits:** Apply depending on account tiers (e.g., 40 mutations/min for `create_board`).
*   **Rate Limit Headers:** Always respect `RateLimit-Policy`, `RateLimit`, and `Retry-After` headers.

## 4. Error Handling
*   **CRITICAL RULE: The "200 OK" Application Error Quirk:** Monday.com returns an HTTP 200 OK status code for application-level errors. Your error-handling middleware must inspect the JSON response body for an `errors` array.
*   **Partial Data:** GraphQL requests can return partial data. If a query fails on one field but succeeds on others, the response will contain both a partial `data` object and an `errors` array.
*   **Troubleshooting:** Always log the `request_id` from the `extensions` object for debugging.
*   **`COMPLEXITY_BUDGET_EXHAUSTED` (HTTP 429):** Complexity limit reached. Requeue using the server-provided reset time (`reset_in_x_seconds`), not generic backoff.

## 5. Idempotency & Safe Retries
To prevent duplicate side effects, Monday.com supports the `Idempotency-Key` header.
*   **Rules:** The header is ignored on queries (reads are inherently idempotent). Only applies to POST requests.
*   **Usage:** Use for retrying after network timeouts or 5xx server errors. Do NOT use for retrying after a `429 Too Many Requests` error.
*   **Key Stability:** Never generate a new key on a retry attempt. The key must remain identical across retries for deduplication to work.

## 6. Implementation Patterns (Reference: `fr-dgtl-monday-carrefour`)
Based on our reference architecture, enforce the following implementation standards:

*   **Idempotency Key Generation:** Generate a standard UUID (e.g., `uuid.uuid4()`) and attach it as the `Idempotency-Key` header for mutations. Critically, **re-use the same UUID during retries** of the same operation. Log the `Idempotency-Replayed` response header when triggered.
*   **Advanced Batching with Aliases:** Use GraphQL aliases (e.g., `update_0: change_multiple_column_values(...)`, `update_1: ...`) to dynamically combine multiple, distinct updates into a single GraphQL query block, further reducing network overhead.
*   **Dynamic Rate Limit Retries (429s & Budgets):** Implement a dedicated retry loop specifically for rate limits. Determine exact sleep durations by parsing the `RateLimit` header (extracting `t=` values for reset times), checking `Retry-After`, or checking the GraphQL error extensions for `retry_in_seconds`. Sleep explicitly (e.g., `asyncio.sleep()`) instead of using generic backoff.
*   **Network vs. Logic Retries:** Separate rate-limit logic from transient network issues. Use a resilient retry library (like `tenacity` in Python) to handle generic HTTP exceptions (e.g., timeouts, 502s) with standard exponential backoff (e.g., max 3 attempts).
*   **Handling Partial Successes in Batches:** When executing batch mutations, if the response contains both `data` (partial success) and `errors`, do not immediately throw an uncaught exception. Log a warning with the partial errors and allow the successful operations to persist.
*   **Pagination Standards:** Standardize cursor pagination limit at 500 items per request, using `items_page` for the initial query and `next_items_page` for subsequent cursor fetches.

## 7. Code Quality & Formatting
*   **Python Syntax:** Enforce the use of modern Python 3.12+ syntax and typing features (e.g., modern type hinting without `Optional`/`Union` where appropriate, `match`/`case` statements, f-strings, etc.).
*   **Ruff:** This project uses `ruff` for all Python linting and formatting.
*   **Mandatory Step:** At the end of *every* implementation step or file modification, you MUST run `uv run ruff check --fix .`, `uv run ruff format .`, and `uv run pytest` before concluding the turn.

## 8. Architecture & Clean Code
*   **Single Responsibility Principle (SRP):** Enforce strict separation of concerns. Do not bundle disparate logical components (e.g., exceptions, data models, network clients) in the same file. E.g., all custom exceptions must live in `src/core/exceptions.py`.
*   **DRY (Don't Repeat Yourself):** Consolidate reused logic (like standard pagination handlers) into central helper services.

## 9. Documentation Standards
*   **Strict Docstrings:** Every method/function that accepts input parameters or returns a value MUST have a comprehensive docstring.
*   **Format:** We use the Google docstring format. You must explicitly document the `Args:` (including their types) and `Returns:` (including the type) for every method.

## 10. Session Tracking
*   **Mandatory Update:** At the end of every significant implementation step or completed phase, you MUST update `docs/06-session-tracking.md` with the date, decisions made, the current state of work, and next steps.
*   **Roadmap Sync:** Along with the session tracker, `docs/03-implementation-roadmap.md` MUST be kept up to date by checking off completed items and modifying the plan when moving forward.
*   **Git Sync:** Keep the session tracker and roadmap aligned with git history.

## 11. Architecture Documentation
*   **Keep Architecture Updated:** Whenever architectural decisions are made, new infrastructure is introduced, or we transition between local and production implementations, you MUST update `docs/08-local-vs-prod-architecture.md` to reflect the current state. This ensures our architectural blueprints remain accurate as the plan evolves.
