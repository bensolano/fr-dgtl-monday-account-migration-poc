# Session & Decision Tracking

## 2026-08-18 - Project Initialization

**Decisions Made:**

- **Tech Stack:** Python (async) for the core orchestration and API clients. Dependency and environment management is handled by `uv` (replacing `pip`/`venv`).
- **Code Quality:** Enforce `ruff` for all linting and formatting. `ruff check --fix .` and `ruff format .` must be run at the end of every implementation step.
- **Architecture & Clean Code:** Strict enforcement of SRP and DRY. Logic must be decoupled (e.g., separating Exceptions from API Clients).
- **Documentation:** Enforce strict Google-style docstrings (Args/Returns) for all methods.
- **Networking & Retries:** `httpx` for async HTTP requests and `tenacity` for generic network retries.
- **Testing:** Local-first approach. We will use `pytest`, `pytest-asyncio`, and `respx` for offline mocking of the Monday.com API.
- **Incremental Build:** Storage and state will initially be routed to local files (JSON/SQLite) for local testing of the Discovery phase. GCP integrations (Firestore, BigQuery, Cloud Tasks) will be introduced only after local logic is proven.

**Current State:**

- Synthesized Monday.com API documentation and extracted special guidelines from the `fr-dgtl-monday-carrefour` reference project into `GEMINI.md`.
- Created this tracking document.
- Initialized project skeleton (`src/`, `tests/`), `requirements.txt`, and `.venv`.
- Verified local testing loop with test scaffolding.
- Implemented `src/monday_client.py` incorporating UUID Idempotency generation, explicit rate limit (429) header parsing, and 200 OK application error handling.
- Implemented unit tests in `tests/test_monday_client.py` using `respx` to successfully verify all edge cases.
- Implemented `src/discovery.py` (The Discovery Engine) with paginated readers for Workspaces, Boards, Groups, Columns, and Items.
- Tested Discovery logic locally, mocking the paginated API responses and verifying the resulting `local_inventory.json` output structure.
- Implemented `src/classification.py` (The Rules Engine) which parses an inventory and tags objects as `full`, `partial`, or `manual_only` based on the capability matrix.
- Tested Classification logic locally via `tests/test_classification.py`.
- Implemented `src/report_generator.py` to parse a classified inventory and generate a human-readable Markdown summary.
- Tested Report Generator locally via `tests/test_report_generator.py`.
- Built `main.py` to tie the Discovery, Classification, and Reporting engines into a single, executable end-to-end local flow.

**Next Up:**

- **Manual Verification:** Run `export MONDAY_API_KEY='...' && uv run python main.py` against a real account to verify the physical `pre_migration_report.md`.
- **Phase 3 (Orchestration):** Begin designing the Orchestrator DAG to transition from read-only reporting to the actual writing/creation loop.

## 2026-08-19 - Microservice Refactor & Frontend Scaffolding

**Decisions Made:**

- **Architecture Shift:** Moving from a pure CLI tool to a decoupled architecture with a React+Vite frontend and a FastAPI backend to support production deployments on Cloud Run.
- **Authentication:** Application Default Credentials (ADC) will be strictly used for all GCP services, both locally and in deployed environments.
- **Frontend Stack:** React (TypeScript) + Vite with vanilla CSS for a lightweight, modern UI.
- **Containerization:** Multi-stage Docker builds to deploy both components efficiently.

**Current State:**

- Drafted and approved `docs/07-frontend-and-infra-plan.md`.
- Refactored backend: Added `fastapi` and `uvicorn`, created `src/api/routes.py` and `models.py`.
- Scaffolded frontend: Created React+Vite app in `frontend/`, implemented `App.tsx` for API key entry and job status polling.
- Dockerized: Created `Dockerfile.api` and `Dockerfile.frontend`.
- Updated project roadmap (`docs/03-implementation-roadmap.md`) to reflect the new Phase 2.5 infrastructure work.

**Next Up:**

- **Infrastructure as Code:** Write Terraform modules for GCP deployment (Cloud Run, Secret Manager) relying on ADC.
- **State Management:** Replace the in-memory Python `job_store` dict with Firestore.
- **Storage:** Store the generated markdown reports in Cloud Storage instead of the local filesystem.

## 2026-08-26 - Deployment & Infrastructure Hardening

**Decisions Made:**

- **Deployment:** Adopted Cloud Build for CI/CD and Terraform for infrastructure as code, maintaining strict reliance on ADC.
- **Container Runtime:** Frontend API calls routed dynamically, NGINX configured to respect Cloud Run's `$PORT` environment variable.

**Current State:**

- Completed Phase 2.5 of the Implementation Roadmap.
- Deployed Portal UI and API via Cloud Build and Terraform definitions (Cloud Run).
- Configured frontend NGINX and backend API containers to respect Cloud Run `PORT`.
- Restructured directories, extracted job execution logic, and added missing `get_job` function in `job_engine`.
- Added fallback logic to proxy report downloads when local signed URL generation fails.
- Set up dedicated Cloud Run Job image with correct entrypoint.
- Implemented Firestore-backed `StateManager` (`src/core/state.py`) to manage idempotency mappings (`get_dest_id`, `set_dest_id`) before execution.
- Implemented `OrchestrationEngine` (`src/engines/orchestration_engine.py`) to parse classified inventories into a staged DAG, properly filtering out `manual_only` tasks and enforcing execution order.
- Updated `terraform/main.tf` to provision dedicated Cloud Tasks queues for Phase 3 Execution (Workspaces, Boards, Groups, Columns, Items).
- Added `google-cloud-tasks` client library and updated `OrchestrationEngine.enqueue_dag` to push the first stage of valid items directly to GCP queues.
- Implemented FastAPI worker endpoints (`src/api/worker_routes.py`) to receive Cloud Tasks payloads and execute the required idempotency checks via `StateManager`.
- Refactored FastAPI route structure to separate concerns: `job_routes.py` for Discovery triggers and `worker_routes.py` for DAG execution, orchestrated by `src/api/main.py`.
- Implemented `TokenBucket` proactive rate limiting in `StateManager` using Firestore transactions.
- Modified `MondayClient._execute_query_with_retries` to support `distributed=True`, returning complexity metadata and raising `MondayRateLimitError` to leverage Cloud Tasks native backoff instead of localized `asyncio.sleep`.
- Implemented `ExecutionEngine` (`src/engines/execution_engine.py`) to map source payloads (workspaces, boards, groups, columns, items) into explicit Monday.com GraphQL creation mutations.
- Updated FastAPI worker routes (`src/api/worker_routes.py`) to fetch the `dest_api_key` securely, instantiate the `ExecutionEngine`, and sync complexity budgets post-execution.
- Implemented Stage Gating in `StateManager` using Firestore transactions (`initialize_dag_state`, `mark_task_complete`). The orchestration seeds the task counters per stage, and worker routes decrement them upon success, firing an event when a stage hits zero to continue DAG execution.
- Added `POST /api/v1/jobs/{job_id}/execute` to `job_routes.py` to formally trigger Phase 3 Execution. This reads the saved `inventory.json` from GCS, builds the DAG, saves it to `dag.json`, and enqueues the first valid stage to Cloud Tasks.
- Wired up the stage gating cascade in `worker_routes.py` so that finishing the final task of a stage pulls the DAG and dynamically enqueues the next stage sequentially.
- Updated the React Frontend (`frontend/src/App.tsx`) to support Phase 3. Added the "Confirm & Execute Migration" button, the polling loop for `EXECUTING`, and the terminal `MIGRATION_COMPLETED` status view.

**Next Up:**

- **Phase 4 (Reporting & Ops):** BigQuery events table, final execution actuals vs plan, and Cloud Scheduler purges.

## 2026-08-28 - Bug Fixes, Pydantic Refactoring & DAG Documentation

**Decisions Made:**

- **API Layer:** Fixed a Pydantic schema generation error in FastAPI for endpoints returning non-JSON responses (`RedirectResponse`, `Response`), and audited all API routes to ensure they return Pydantic schema-friendly models.
- **Thin Controllers:** Enforced "thin controllers" by moving all GCP client initialization and business logic (Secret Manager, Cloud Run, Cloud Storage) out of the FastAPI routers and into a dedicated `src/core/gcp.py` module.
- **Dependency Injection:** Enforced the use of FastAPI Dependency Injection (`Annotated[ClassName, Depends()]`) for all business engines instead of module-level global state, updating `GEMINI.md` to reflect this architectural rule.
- **Data Models:** Replaced untyped `dict[str, Any]` payloads throughout the core engines (`OrchestrationEngine`, `StateManager`, `TaskDeps`) with strict Pydantic models to enforce type safety and validation.
- **Documentation:** Formalized the mental model of the DAG in `docs/04-data-models-and-schemas.md` as a strict sequential pipeline (`workspaces` -> `boards` -> `groups` -> `columns` -> `items`) gated by completion counters, rather than a graph of individual task-level dependencies.
- **FastAPI Routing:** Removed the "dynamic composition root" workaround in `worker_routes.py` and replaced the raw `Request` injection with a validated `WorkerTaskRequest` Pydantic model.

**Current State:**

- Added `response_model=None` to `job_routes.py` `/{job_id}/report` endpoint to prevent FastAPI from failing on schema generation.
- Created `ExecuteJobResponse` and `TaskResponse` models in `src/api/models.py`.
- Updated `execute_job` (in `job_routes.py`) and `handle_task` (in `worker_routes.py`) to use the newly created Pydantic models.
- Replaced explicit `JSONResponse` returns with `HTTPException` raises (e.g., status 429) in `handle_task` to comply with static typing.
- Created `src/core/gcp.py` containing `GCPClients` singleton and utility methods (`store_job_secrets`, `get_dest_api_key`, `trigger_cloud_run_discovery_job`, `get_inventory`, etc.).
- Refactored `src/api/job_routes.py` and `src/api/worker_routes.py` to strip out raw GCP SDK logic in favor of `src.core.gcp`.
- Refactored `job_routes.py` and `worker_routes.py` to inject `JobEngine`, `StateManager`, and `OrchestrationEngine` directly into endpoints via `Depends()`.
- Created `src/core/schemas.py` containing `MigrationDag`, `TaskPayload`, `JobDocument`, and `WorkerTaskRequest`.
- Refactored `src/engines/interfaces.py` to type hint the new Pydantic models.
- Updated `OrchestrationEngine` to construct and return a `MigrationDag` object.
- Updated `StateManager` to parse job documents into `JobDocument` and process `MigrationDag` objects.
- Updated `CloudTaskQueue` and `GCSDagStorage` in `task_deps.py` to serialize/deserialize Pydantic models via `.model_dump_json()` and `.model_validate_json()`.
- Refactored `worker_routes.py` `handle_task` endpoint to accept `WorkerTaskRequest`, removing manual JSON parsing.
- Fixed unit tests in `test_state.py` and `test_orchestration_engine.py` to accommodate object attribute access instead of dictionary bracket notation.
- Updated `docs/04-data-models-and-schemas.md` to accurately reflect the DAG stage gating architecture and the updated Cloud Tasks payload shape.
- Added Mermaid diagrams to `docs/02-architecture.md` (Architecture Flow) and `docs/04-data-models-and-schemas.md` (ERD and Pipeline DAG) to visually represent the data flows and models.
- Fixed a `TypeError` in the Cloud Run job entrypoint (`main.py`) by properly injecting dependencies into `JobEngine`.
- Verified that all tests and linters pass.

**Next Up:**

- **Refactor Rate Limiting:** Implement the Re-enqueue Pattern in `worker_routes.py` and `StateManager` to dynamically reschedule Cloud Tasks based on exact rate limit reset times instead of returning HTTP 429s.
- **Local Execution Fallback:** Implement a bounded `asyncio.Queue` worker pool tied to the FastAPI lifecycle to simulate Cloud Tasks execution locally without requiring external GCP queueing infrastructure.
- Continue with Phase 4 (Reporting & Ops).

## 2026-08-31 - Rate Limiting, Frontend Parity, and Local DX Fixes

**Decisions Made:**

- **Rate Limiting:** Adopted the Re-enqueue Pattern for rate limit mitigation. Instead of throwing HTTP 429s which rely on generic Cloud Tasks backoff, workers now return `200 OK` but explicitly re-enqueue tasks with a `schedule_time` offset by the exact rate limit `retry_in` seconds, preserving budget efficiency and tight schedules.
- **Local Simulation:** Bypassed the need for live GCP Cloud Tasks by injecting a lightweight, FastAPI-lifespan-tied `LocalTaskQueue`. Background loops intercept task messages in `asyncio.Queue` and send local HTTP POST requests, natively mimicking Cloud Tasks webhooks and providing a complete offline testing cycle.
- **Dead Letter Queue (DLQ):** Implemented an application-level DLQ. Tasks now carry a `retry_count` in their payload. Non-rate-limit exceptions cause the worker to increment the counter and re-enqueue (up to 3 times) with exponential backoff. Upon total exhaustion, the task is saved to a `dead_letters` collection in Firestore, marked as completed in the DAG so it doesn't hang the pipeline, and safely dropped.
- **Deferred Write Authorization:** Implemented "Explicit consent UI" by splitting API key inputs. The source API key is provided for Discovery, and the destination API key is only requested post-discovery before Execution, mitigating risk.
- **Capability Reporting:** Added a static Migration Capability Matrix summary directly to the Markdown report and the React UI for better user transparency.
- **Job Lifecycle Controls:** Added `CANCEL` and `DELETE` endpoints to the backend and surfaced them via danger buttons in the UI for complete data and execution lifecycle management.
- **Lazy GCP Client Initialization:** Enforced the Lazy Initialization pattern (using `@property` accessors) for all Google Cloud SDK clients (`firestore.Client`, `storage.Client`, `SecretManagerServiceClient`, and `CloudTasksClient`) across the core engines to fix aggressive file descriptor (FD) leaks and gRPC multi-processing warnings when running under `uvicorn` and FastAPI's `BackgroundTasks`.

**Current State:**

- Updated `CloudTaskQueue.enqueue_task` in `src/core/task_deps.py` to accept `schedule_time` (converting it into `timestamp_pb2` payload).
- Implemented `LocalTaskQueue` and `local_worker_loop` in `src/core/local_queue.py` backed by `asyncio.Queue` and `httpx`.
- Tied the `local_worker_loop` to the FastAPI application startup via `@asynccontextmanager` lifespan in `src/api/main.py`.
- Added `get_task_queue()` factory to `src/core/task_deps.py` and modified `worker_routes.py` and `job_routes.py` dependency providers to use it dynamically based on the `K_SERVICE` environment variable.
- Updated `StateManager.consume_budget()` in `src/core/state.py` to return a tuple `(bool, int)` supplying the exact `retry_in` delay in seconds when a budget check fails.
- Modified the `handle_task` endpoint in `worker_routes.py` to catch `MondayRateLimitError` and budget-exhaustion states by computing a future `schedule_time`, re-enqueueing the task via `orchestration.task_queue.enqueue_task`, and returning a 200 `skipped` response.
- Modified `TaskPayload` schema to include `retry_count`.
- Added `save_dead_letter` method to `StateManager`.
- Modified `handle_task` to catch general exceptions, retry up to 3 times with exponential backoff, and ultimately route permanent failures to the DLQ in Firestore.
- Updated `LocalTaskQueue` to drop `500` errors instead of infinite looping, deferring to the new application-level retry logic.
- Updated `docs/03-implementation-roadmap.md` to check off Phase 3 retry policy constraints since exact re-enqueue delays and DLQ are fully implemented.
- **CLEAN Architecture Refactor:** Extracted the mathematical logic for the Token Bucket into a pure `TokenBucketRateLimiter` class (SRP) in `src/core/rate_limit.py` and extracted time calculations into `src/core/time_utils.py`.
- **Dependency Inversion (DIP):** Removed all inline instantiations of the `StateManager` and rate limiter. `ExecutionEngine` and `JobEngine` now strictly rely on `StateInterface`. `StateManager` now accepts `TokenBucketInterface` as an injected dependency, natively wired via FastAPI's composition root in `job_routes.py` and `worker_routes.py`.
- Updated `JobCreateRequest` to only require `source_api_key`.
- Added `ExecuteJobRequest` expecting `dest_api_key` to `POST /jobs/{job_id}/execute`.
- Created `DELETE /jobs/{job_id}` endpoint to purge Firestore documents, Secret Manager keys, and GCS artifacts.
- Created `POST /jobs/{job_id}/cancel` endpoint to halt job pipelines via state transition to `CANCELLED`.
- Refactored `src/core/gcp.py` to cleanly split `store_dest_secret` and handle deep artifact deletion.
- Appended the static capability matrix appendix to `ReportEngine.generate_markdown_report`.
- Completely overhauled `frontend/src/App.tsx` and `App.css` to introduce the explicit step-by-step workflow, capability component, and danger actions.
- Checked off "Explicit consent UI" in the roadmap.
- Refactored `GCPClients` singleton in `src/core/gcp.py` to instantiate clients lazily.
- Refactored `JobEngine` in `src/engines/job_engine.py` to use `@property` accessors for `db`, `storage_client`, and `secret_client`.
- Refactored `StateManager` in `src/core/state.py` to instantiate `firestore.Client` lazily to avoid socket duplication upon FastAPI injection.
- Refactored `GCSDagStorage` and `CloudTaskQueue` in `src/core/task_deps.py` to instantiate `storage.Client` and `tasks_v2.CloudTasksClient` lazily, preventing per-request gRPC connection overhead.
- Fixed a `ValidationError` in `job_engine.py` by ensuring `set_job_status("PENDING")` writes the fully valid `JobDocument` schema (with placeholder accounts) to Firestore on initialization.
- Fixed a 404 error during local development when retrieving the report by implementing a fallback to `/tmp/{job_id}_report.md` in the `/api/v1/jobs/{job_id}/report` route when GCS paths are missing or unreachable.
- Updated unit tests (`test_state.py`) to correctly trigger and test the new lazy evaluation properties.

**Next Up:**

- Continue with Phase 4 (Reporting & Ops).
- Start implementing BigQuery `migration_events` table + live progress view.

## 2026-09-02 - Async GCP Clients & Cloud Tasks Tunneling

**Decisions Made:**

- **Async GCP Clients:** Upgraded to official Async Google Cloud SDKs (`FirestoreAsyncClient`, `SecretManagerServiceAsyncClient`, `JobsAsyncClient`, `CloudTasksAsyncClient`) for high-throughput, non-blocking I/O.
- **Storage Threading:** Wrapped synchronous `google.cloud.storage` calls in `asyncio.to_thread()` to prevent event loop blocking.
- **SOLID Decoupling:** Introduced `GcpClientsInterface` injected via `dependencies.py` to remove inline imports and circular dependencies in `JobEngine` and `StateManager`.
- **Remove Local asyncio Queue:** Deprecated and removed the `LocalTaskQueue` and in-memory background worker loop `local_queue.py` that simulated Cloud Tasks.
- **Consistent Execution Context:** All environments (local and production) will now use `CloudTaskQueue` and dispatch directly to Google Cloud Tasks.
- **Local Tunnels:** Local development will use tunneling tools (e.g. `ngrok`) set via the `SERVICE_URL` environment variable to receive webhooks from actual Cloud Tasks, providing higher fidelity parity between local testing and production execution.

**Current State:**

- Refactored `src/core/gcp.py` to expose async clients.
- Updated `StateManager` and `JobEngine` to `await` all datastore/infrastructure calls.
- Updated API routes (`job_routes.py`, `worker_routes.py`) to correctly `await` async engine methods.
- Updated test suite (`test_job_engine.py`, `test_state.py`) to use `AsyncMock` for terminal operations, ensuring all 30 tests pass.
- Verified local FastAPI execution without event loop hangs.
- Deleted `src/core/local_queue.py`.
- Removed `local_worker_loop` background tasks from the FastAPI lifespan in `src/api/main.py`.
- Updated `get_task_queue()` in `src/core/task_deps.py` to unconditionally return `CloudTaskQueue`.
- Updated `docs/08-local-vs-prod-architecture.md` and `docs/09-method-overview.md` to reflect the tunneling architecture.

**Next Up:**

- Continue with Phase 4 (Reporting & Ops).
- Start implementing BigQuery `migration_events` table + live progress view.
