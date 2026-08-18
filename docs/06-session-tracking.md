# Session & Decision Tracking

## 2026-08-18 - Project Initialization
**Decisions Made:**
*   **Tech Stack:** Python (async) for the core orchestrator and API clients. Dependency and environment management is handled by `uv` (replacing `pip`/`venv`).
*   **Code Quality:** Enforce `ruff` for all linting and formatting. `ruff check --fix .` and `ruff format .` must be run at the end of every implementation step.
*   **Architecture & Clean Code:** Strict enforcement of SRP and DRY. Logic must be decoupled (e.g., separating Exceptions from API Clients).
*   **Documentation:** Enforce strict Google-style docstrings (Args/Returns) for all methods.
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
*   Implemented `src/discovery.py` (The Discovery Engine) with paginated readers for Workspaces, Boards, Groups, Columns, and Items.
*   Tested Discovery logic locally, mocking the paginated API responses and verifying the resulting `local_inventory.json` output structure.
*   Implemented `src/classification.py` (The Rules Engine) which parses an inventory and tags objects as `full`, `partial`, or `manual_only` based on the capability matrix.
*   Tested Classification logic locally via `tests/test_classification.py`.
*   Implemented `src/report_generator.py` to parse a classified inventory and generate a human-readable Markdown summary.
*   Tested Report Generator locally via `tests/test_report_generator.py`.

**Next Up:**
*   Build an End-to-End Local Execution Script (`main.py`).
*   Tie together `DiscoveryEngine` -> `ClassificationEngine` -> `ReportGenerator` into a single runnable flow.
*   Run the script and manually verify the physical `pre_migration_report.md` output.
