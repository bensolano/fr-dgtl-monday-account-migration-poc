# Session & Decision Tracking

## 2026-08-18 - Project Initialization
**Decisions Made:**
*   **Tech Stack:** Python (async) for the core orchestration and API clients. Dependency and environment management is handled by `uv` (replacing `pip`/`venv`).
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
*   Implemented Firestore-backed `StateManager` (`src/core/state.py`) to manage idempotency mappings (`get_dest_id`, `set_dest_id`) before execution.
*   Implemented `OrchestrationEngine` (`src/engines/orchestration_engine.py`) to parse classified inventories into a staged DAG, properly filtering out `manual_only` tasks and enforcing execution order.
*   Updated `terraform/main.tf` to provision dedicated Cloud Tasks queues for Phase 3 Execution (Workspaces, Boards, Groups, Columns, Items).
*   Added `google-cloud-tasks` client library and updated `OrchestrationEngine.enqueue_dag` to push the first stage of valid items directly to GCP queues.
*   Implemented FastAPI worker endpoints (`src/api/worker_routes.py`) to receive Cloud Tasks payloads and execute the required idempotency checks via `StateManager`.
*   Refactored FastAPI route structure to separate concerns: `job_routes.py` for Discovery triggers and `worker_routes.py` for DAG execution, orchestrated by `src/api/main.py`.
*   Implemented `TokenBucket` proactive rate limiting in `StateManager` using Firestore transactions.
*   Modified `MondayClient._execute_query_with_retries` to support `distributed=True`, returning complexity metadata and raising `MondayRateLimitError` to leverage Cloud Tasks native backoff instead of localized `asyncio.sleep`.
*   Implemented `ExecutionEngine` (`src/engines/execution_engine.py`) to map source payloads (workspaces, boards, groups, columns, items) into explicit Monday.com GraphQL creation mutations.
*   Updated FastAPI worker routes (`src/api/worker_routes.py`) to fetch the `dest_api_key` securely, instantiate the `ExecutionEngine`, and sync complexity budgets post-execution.
*   Implemented Stage Gating in `StateManager` using Firestore transactions (`initialize_dag_state`, `mark_task_complete`). The orchestration seeds the task counters per stage, and worker routes decrement them upon success, firing an event when a stage hits zero to continue DAG execution.
*   Added `POST /api/v1/jobs/{job_id}/execute` to `job_routes.py` to formally trigger Phase 3 Execution. This reads the saved `inventory.json` from GCS, builds the DAG, saves it to `dag.json`, and enqueues the first valid stage to Cloud Tasks.
*   Wired up the stage gating cascade in `worker_routes.py` so that finishing the final task of a stage pulls the DAG and dynamically enqueues the next stage sequentially.
*   Updated the React Frontend (`frontend/src/App.tsx`) to support Phase 3. Added the "Confirm & Execute Migration" button, the polling loop for `EXECUTING`, and the terminal `MIGRATION_COMPLETED` status view.

**Next Up:**
*   **Phase 4 (Reporting & Ops):** BigQuery events table, final execution actuals vs plan, and Cloud Scheduler purges.

## 2026-08-28 - Bug Fixes, Pydantic Refactoring & DAG Documentation
**Decisions Made:**
*   **API Layer:** Fixed a Pydantic schema generation error in FastAPI for endpoints returning non-JSON responses (`RedirectResponse`, `Response`), and audited all API routes to ensure they return Pydantic schema-friendly models.
*   **Thin Controllers:** Enforced "thin controllers" by moving all GCP client initialization and business logic (Secret Manager, Cloud Run, Cloud Storage) out of the FastAPI routers and into a dedicated `src/core/gcp.py` module.
*   **Dependency Injection:** Enforced the use of FastAPI Dependency Injection (`Annotated[ClassName, Depends()]`) for all business engines instead of module-level global state, updating `GEMINI.md` to reflect this architectural rule.
*   **Data Models:** Replaced untyped `dict[str, Any]` payloads throughout the core engines (`OrchestrationEngine`, `StateManager`, `TaskDeps`) with strict Pydantic models to enforce type safety and validation.
*   **Documentation:** Formalized the mental model of the DAG in `docs/04-data-models-and-schemas.md` as a strict sequential pipeline (`workspaces` -> `boards` -> `groups` -> `columns` -> `items`) gated by completion counters, rather than a graph of individual task-level dependencies.
*   **FastAPI Routing:** Removed the "dynamic composition root" workaround in `worker_routes.py` and replaced the raw `Request` injection with a validated `WorkerTaskRequest` Pydantic model.

**Current State:**
*   Added `response_model=None` to `job_routes.py` `/{job_id}/report` endpoint to prevent FastAPI from failing on schema generation.
*   Created `ExecuteJobResponse` and `TaskResponse` models in `src/api/models.py`.
*   Updated `execute_job` (in `job_routes.py`) and `handle_task` (in `worker_routes.py`) to use the newly created Pydantic models.
*   Replaced explicit `JSONResponse` returns with `HTTPException` raises (e.g., status 429) in `handle_task` to comply with static typing.
*   Created `src/core/gcp.py` containing `GCPClients` singleton and utility methods (`store_job_secrets`, `get_dest_api_key`, `trigger_cloud_run_discovery_job`, `get_inventory`, etc.).
*   Refactored `src/api/job_routes.py` and `src/api/worker_routes.py` to strip out raw GCP SDK logic in favor of `src.core.gcp`.
*   Refactored `job_routes.py` and `worker_routes.py` to inject `JobEngine`, `StateManager`, and `OrchestrationEngine` directly into endpoints via `Depends()`.
*   Created `src/core/schemas.py` containing `MigrationDag`, `TaskPayload`, `JobDocument`, and `WorkerTaskRequest`.
*   Refactored `src/engines/interfaces.py` to type hint the new Pydantic models.
*   Updated `OrchestrationEngine` to construct and return a `MigrationDag` object.
*   Updated `StateManager` to parse job documents into `JobDocument` and process `MigrationDag` objects.
*   Updated `CloudTaskQueue` and `GCSDagStorage` in `task_deps.py` to serialize/deserialize Pydantic models via `.model_dump_json()` and `.model_validate_json()`.
*   Refactored `worker_routes.py` `handle_task` endpoint to accept `WorkerTaskRequest`, removing manual JSON parsing.
*   Fixed unit tests in `test_state.py` and `test_orchestration_engine.py` to accommodate object attribute access instead of dictionary bracket notation.
*   Updated `docs/04-data-models-and-schemas.md` to accurately reflect the DAG stage gating architecture and the updated Cloud Tasks payload shape.
*   Added Mermaid diagrams to `docs/02-architecture.md` (Architecture Flow) and `docs/04-data-models-and-schemas.md` (ERD and Pipeline DAG) to visually represent the data flows and models.
*   Verified that all tests and linters pass.

**Next Up:**
*   Continue with Phase 4 (Reporting & Ops).
