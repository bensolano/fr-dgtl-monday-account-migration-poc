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
*   Built `main.py` to tie the Discovery, Classification, and Reporting engines into a single, executable end-to-end local flow.

**Next Up:**
*   **Manual Verification:** Run `export MONDAY_API_KEY='...' && uv run python main.py` against a real account to verify the physical `pre_migration_report.md`.
*   **Phase 3 (Orchestration):** Begin designing the Orchestrator DAG to transition from read-only reporting to the actual writing/creation loop.

## 2026-08-19 - Microservice Refactor & Frontend Scaffolding
**Decisions Made:**
*   **Architecture Shift:** Moving from a pure CLI tool to a decoupled architecture with a React+Vite frontend and a FastAPI backend to support production deployments on Cloud Run.
*   **Authentication:** Application Default Credentials (ADC) will be strictly used for all GCP services, both locally and in deployed environments.
*   **Frontend Stack:** React (TypeScript) + Vite with vanilla CSS for a lightweight, modern UI.
*   **Containerization:** Multi-stage Docker builds to deploy both components efficiently.

**Current State:**
*   Drafted and approved `docs/07-frontend-and-infra-plan.md`.
*   Refactored backend: Added `fastapi` and `uvicorn`, created `src/api/routes.py` and `models.py`.
*   Scaffolded frontend: Created React+Vite app in `frontend/`, implemented `App.tsx` for API key entry and job status polling.
*   Dockerized: Created `Dockerfile.api` and `Dockerfile.frontend`.
*   Updated project roadmap (`docs/03-implementation-roadmap.md`) to reflect the new Phase 2.5 infrastructure work.

**Next Up:**
*   **Infrastructure as Code:** Write Terraform modules for GCP deployment (Cloud Run, Secret Manager) relying on ADC.
*   **State Management:** Replace the in-memory Python `job_store` dict with Firestore.
*   **Storage:** Store the generated markdown reports in Cloud Storage instead of the local filesystem.

## 2026-08-26 - Deployment & Infrastructure Hardening
**Decisions Made:**
*   **Deployment:** Adopted Cloud Build for CI/CD and Terraform for infrastructure as code, maintaining strict reliance on ADC.
*   **Container Runtime:** Frontend API calls routed dynamically, NGINX configured to respect Cloud Run's `$PORT` environment variable.

**Current State:**
*   Completed Phase 2.5 of the Implementation Roadmap.
*   Deployed Portal UI and API via Cloud Build and Terraform definitions (Cloud Run).
*   Configured frontend NGINX and backend API containers to respect Cloud Run `PORT`.
*   Restructured directories, extracted job execution logic, and added missing `get_job` function in `job_engine`.
*   Added fallback logic to proxy report downloads when local signed URL generation fails.
*   Set up dedicated Cloud Run Job image with correct entrypoint.

**Next Up:**
*   **Phase 3 (Orchestration & Execution):** Build the DAG orchestrator respecting dependency order (workspace → board → group → column → item).
*   Set up Cloud Tasks queues per stage with coarse concurrency limits.
*   Implement token-bucket rate limiter and idempotency checks before create-mutations.
