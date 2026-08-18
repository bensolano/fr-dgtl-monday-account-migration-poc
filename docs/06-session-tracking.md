# Session & Decision Tracking

## 2026-08-18 - Project Initialization
**Decisions Made:**
*   **Tech Stack:** Python (async) for the core orchestrator and API clients. Dependency and environment management is handled by `uv` (replacing `pip`/`venv`).
*   **Code Quality:** Enforce `ruff` for all linting and formatting. `ruff check --fix .` and `ruff format .` must be run at the end of every implementation step.
*   **Architecture & Clean Code:** Strict enforcement of SRP and DRY. Logic must be decoupled (e.g., separating Exceptions from API Clients).
*   **Networking & Retries:** `httpx` for async HTTP requests and `tenacity` for generic network retries.
*   **Testing:** Local-first approach. We will use `pytest`, `pytest-asyncio`, and `respx` for offline mocking of the Monday.com API.
*   **Incremental Build:** Storage and state will initially be routed to local files (JSON/SQLite) for local testing of the Discovery phase. GCP integrations (Firestore, BigQuery, Cloud Tasks) will be introduced only after local logic is proven.

**Current State:**
*   Synthesized Monday.com API documentation and extracted special guidelines from the `fr-dgtl-monday-carrefour` reference project into `GEMINI.md`.
*   Created this tracking document.
*   Initialized project skeleton (`src/`, `tests/`), `requirements.txt`, and `.venv`.
*   Verified local testing loop with test scaffolding.
*   Implemented `src/monday_client.py` incorporating UUID Idempotency generation, explicit rate limit (429) header parsing, and 200 OK application error handling.
*   Implemented unit tests in `tests/test_monday_client.py` using `respx` to successfully verify all edge cases.

**Next Up:**
*   Implement `src/discovery.py` (The Discovery Engine - Local Emulation).
*   Implement paginated readers (Boards, Items, Columns, Workspaces, Groups).
*   Test Discovery logic locally by exporting the output to a local JSON file or SQLite database.
