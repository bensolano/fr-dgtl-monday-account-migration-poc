# Chronological Execution Flow & Method Overview

This document outlines the entire migration lifecycle from the user's initial click to the final completion state. It details the chronological order of execution, the specific Python methods invoked, and the GCP infrastructure utilized at each step.

---

## Phase 1: Discovery Initiation

The user provides their read-only source API key to begin mapping the account.

### Step 1: User Request

- **User Action:** Enters API keys in the React Portal and clicks "Start Discovery Job".
- **Endpoint:** `POST /api/v1/jobs` (`src/api/job_routes.py -> create_job`)
- **GCP Services:**
  - **Secret Manager:** Secures the provided source and destination API keys under `job-{job_id}-source-key`.
  - **Firestore:** Initializes the job state document `jobs/{job_id}` with status `PENDING`.
  - **Cloud Run (Jobs API):** The web server asynchronously triggers the standalone Cloud Run Job (`execute_discovery_job`) using the GCP SDK.

---

## Phase 2: Account Mapping & Classification

The background Cloud Run Job executes the heavy read-only operations without blocking the web UI.

### Step 2: Discovery Execution

- **Entrypoint:** `main.py -> main()` (for local) or Cloud Run container entrypoint.
- **Method:** `JobEngine.execute_discovery_job(job_id)` (Engine logic injected via Dependency Injection / Protocols).
- **GCP Services:** **Secret Manager** (reads the source API key via `src.core.gcp` utility to instantiate `MondayClient`).

### Step 3: Fetching the Data

- **Class:** `DiscoveryEngine` (Satisfies `DiscovererInterface`)
- **Methods Invoked Sequentially:**
  1.  `get_workspaces()`
  2.  `get_boards(workspace_id)`
  3.  `get_groups(board_id)`
  4.  `get_columns(board_id)`
  5.  `get_items(board_id)` (Handles strict cursor pagination)
- **Output:** A massive, unclassified JSON dictionary representing the entire account.

### Step 4: Capability Classification

- **Class:** `ClassificationEngine` (Satisfies `ClassifierInterface`)
- **Method:** `process_inventory(inventory)`
- **Action:** Iterates through the JSON. Flags unsupported items (`manual_only`) based on the monday.com API capability matrix.

### Step 5: Report Generation & Storage

- **Class:** `ReportEngine` (Satisfies `ReporterInterface`)
- **Method:** `generate_markdown_report(classified_inventory)`
- **GCP Services:**
  - **Cloud Storage:** Saves the Markdown report (`reports/{job_id}/pre_migration_report.md`) and the raw JSON (`reports/{job_id}/inventory.json`) via `src.core.gcp`.
  - **Firestore:** Updates job status to `COMPLETED`.

### Step 6: User Review

- **User Action:** The React Portal polls `GET /api/v1/jobs/{job_id}/status`. Seeing `COMPLETED`, the UI displays the download button.
- **Endpoint:** `GET /api/v1/jobs/{job_id}/report`
- **GCP Services:** Generates a Signed URL via **Cloud Storage** for secure, direct download.

---

## Phase 3: Orchestration & Execution

After reviewing the Markdown report, the user consents to write data to the destination account.

### Step 7: Execution Launch

- **User Action:** Clicks "Confirm & Execute Migration" in the React Portal.
- **Endpoint:** `POST /api/v1/jobs/{job_id}/execute`
- **GCP Services:**
  - **Cloud Storage:** Downloads the raw `inventory.json`.
  - **Firestore:** Updates job status to `EXECUTING`.

### Step 8: DAG Construction

- **Class:** `OrchestrationEngine` (Requires injected `StateInterface`, `StorageInterface`, `TaskQueueInterface`)
- **Method:** `build_dag(inventory_data)`
- **Action:** Filters out `manual_only` classifications. Reorganizes the flat JSON into an ordered Directed Acyclic Graph (DAG) array: `workspaces -> boards -> groups -> columns -> items`.

### Step 9: DAG Queuing & State Initialization

- **Method:** `OrchestrationEngine.enqueue_dag(job_id, dag)`
- **GCP Services:**
  - **Cloud Storage:** Uploads `dag.json` (via `GCSDagStorage`) so distributed workers can retrieve the blueprint later.
  - **Firestore:** Calls `StateManager.initialize_dag_state()` (via `StateInterface`). Creates a `dag_state/{stage}` counter for every stage (e.g., `boards: {total_tasks: 50, completed: 0}`).
  - **Cloud Tasks:** Dispatches only the _first_ tage (`workspaces`) to the `migration-workspaces` queue via `_enqueue_stage()` (via `get_task_queue()` factory resolving to `CloudTaskQueue` or `LocalTaskQueue`).

### Step 10: Task Handling & Proactive Rate Limiting

- **Endpoint:** `POST /api/v1/worker/{stage}` (`src/api/worker_routes.py -> handle_task`)
- **GCP Services:**
  - **Firestore (Idempotency):** Calls `StateManager.get_dest_id()`. If a mapping exists, the worker skips execution.
  - **Firestore (Token Bucket):** Calls `StateManager.consume_budget()`. Transactionally deducts estimated complexity from `state/complexity_bucket`. If empty, it computes the exact `retry_in` reset delay, re-enqueues the task with a future `schedule_time`, and returns a `200 OK` (Re-enqueue Pattern) to avoid blind exponential backoff.

### Step 11: GraphQL Mutations & Reactive Sync

- **Class:** `ExecutionEngine`
- **Method:** `execute(entity_type, source_id, payload)`
- **Action:** Maps source IDs to destination IDs (e.g., looking up the new `dest_board_id` to create a group). Executes the creation mutation using `MondayClient(distributed=True)`.
- **GCP Services:**
  - **Firestore (Idempotency):** Saves the new ID mapping via `StateManager.set_dest_id()`.
  - **Firestore (Token Bucket):** `ExecutionEngine._sync_complexity(response)` reads the live `complexity.after` metadata from monday.com and calibrates the bucket.

### Step 12: Stage Gating Cascade

- **Method:** `StateManager.mark_task_complete(job_id, stage)`
- **GCP Services:**
  - **Firestore:** Transactionally increments `completed_tasks`.
  - If `completed_tasks == total_tasks`, the worker calls `OrchestrationEngine.enqueue_next_stage()`.
  - **Cloud Storage:** The Orchestrator downloads `dag.json`, finds the next stage (e.g., `boards`), and pushes it to **Cloud Tasks**, repeating Step 10 until the DAG is exhausted.
