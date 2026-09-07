# Local vs. Deployed Architecture Flow

This document outlines the system architecture and execution flow for the Monday.com Account Migration tool, highlighting how the system gracefully bridges the gap between **Local Development** and **Deployed (GCP Production)** environments without altering core business logic.

---

## Phase 1 & 2: Discovery & Reporting

The first phase maps the Monday.com account, classifies compatibility, and generates the Markdown report.

### Triggering the Workload
*   **Production (GCP):** `src/api/routers/jobs.py` calls the Cloud Run API using the GCP SDK to trigger a standalone **Cloud Run Job**. This ensures the heavy discovery workload is entirely decoupled from the web-server CPU.
*   **Local Bypass:** Since `DISCOVERY_JOB_NAME` is absent locally, FastAPI falls back to injecting the `execute_discovery_job` function into **BackgroundTasks**. The work happens concurrently within the web server process.

### Report Download & Delivery
*   **Production (GCP):** The API generates a **Signed URL** using the Cloud Run Service Account's private key. The frontend downloads the report directly from Google Cloud Storage, bypassing the FastAPI server completely to save bandwidth.
*   **Local Bypass:** Local Application Default Credentials (ADC) cannot sign URLs securely. The API gracefully falls back to a proxy mechanism—it downloads the file from GCS into memory (`blob.download_as_bytes()`) and serves it directly as an HTTP Response to the browser.

---

## Phase 3: Execution & Orchestration

The third phase handles writing the discovered objects to the destination account while navigating strict rate limits and dependency graphs (Workspaces -> Boards -> Groups, etc.).

### State & Idempotency
*   **Both Environments:** To prevent duplicate entities during network retries, an ID map (`jobs/{job_id}/id_map/{entity_type}_{source_id}`) is stored in **Firestore**. Every creation mutation queries this map before proceeding. Local and Prod both execute this using standard Firestore Document SDK calls.

### Queueing & DAG Routing (Cloud Tasks)
*   **Production (GCP):** The `OrchestrationService` parses the inventory into a strict DAG and dispatches the workloads as HTTP POST payloads into dedicated **Cloud Tasks Queues** (`migration-workspaces`, `migration-boards`, etc.). Cloud Tasks natively limits concurrency via `max_dispatches_per_second`.
*   **Local Bypass:** To simulate and test the orchestrator locally, we continue using real Google Cloud Tasks. The local environment configures the `SERVICE_URL` environment variable via `.env` to point to a public tunnel (like `ngrok` or `localtunnel`). Cloud Tasks will dispatch HTTP POST requests directly to your local FastAPI server running the worker routes, ensuring local testing perfectly aligns with the real GCP infrastructure without mocking async execution.

### Rate Limiting (Token Bucket)
*   **Both Environments:** Monday.com tracks "complexity points." We manage this via a transactional **Token Bucket** in Firestore (`jobs/{job_id}/state/complexity_bucket`). 
    *   **Proactive Throttle (Re-enqueue Pattern):** `src/api/routers/workers.py` estimates the cost of an operation and attempts to deduct tokens. If the budget is exhausted, it does *not* wait in the container or return an HTTP 429. Instead, it extracts the reset time, programmatically re-enqueues a clone of the current task into Cloud Tasks with a `schedule_time` set to the exact future reset moment, and returns a `200 OK`. This prevents container bloat and minimizes compute costs while ensuring precise retry scheduling.
    *   **Reactive Sync:** When the `MondayClient` successfully executes a query, it reads the live `complexity` metadata from the response and updates the Firestore bucket directly, keeping local approximations tightly calibrated to reality.

### Stage Gating
*   **Both Environments:** A strict DAG requires that the `workspaces` stage completes before `boards` begins. The Orchestrator registers the total expected tasks per stage in Firestore (`jobs/{job_id}/dag_state/{stage}`). As each FastAPI worker finishes a mutation, it transactionally decrements this counter. When it hits zero, it triggers the enqueue loop for the subsequent stage.

## Real-Time UI Tracking (SSE)
*   **Both Environments:** The frontend relies on Server-Sent Events (SSE) to display a live progress table of the migration.
*   **Backend Implementation:** Because the Python `firestore.AsyncClient` does not support `on_snapshot` listeners natively, `src/api/routers/jobs.py` dynamically spins up a *synchronous* Firestore client for the `/jobs/{job_id}/inventory/stream` route. The synchronous `on_snapshot` callback runs in a background gRPC thread. When documents are modified, the callback bridges the thread gap by pushing updates into an `asyncio.Queue` using `loop.call_soon_threadsafe`, which an async generator then yields to the client as an SSE stream. This approach prevents deadlocks in the main FastAPI event loop while supporting persistent connections.
