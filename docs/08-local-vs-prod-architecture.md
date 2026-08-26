# Local vs. Deployed Architecture Flow

This document outlines the system architecture and execution flow for the Monday.com Account Migration tool, highlighting the differences between **Local Development** and **Deployed (GCP Production)** environments. 

## 1. Execution Flow Overview

When an Operator submits a migration discovery job via the frontend portal, the request follows this general flow:

1.  **Job Creation (`POST /api/v1/jobs`)**: 
    *   The FastAPI backend generates a `job_id`.
    *   API keys (Source/Destination) are securely saved.
    *   Initial status (`PENDING`) is recorded.
    *   The async Discovery Job is triggered.
2.  **Job Execution (Discovery, Classification, Report)**:
    *   The background process queries the Monday.com API.
    *   It classifies the objects.
    *   It generates a Markdown report.
    *   The report is uploaded to Cloud Storage.
    *   Job status is updated to `COMPLETED`.
3.  **Polling & Download (`GET /api/v1/jobs/{job_id}/report`)**:
    *   The frontend polls for job status.
    *   Once `COMPLETED`, the frontend requests the report URL.
    *   The API validates the request and serves the report back to the user.

## 2. GCP Services Usage

Both the local and deployed environments rely on GCP services, but they authenticate and orchestrate them differently.

| Service | Used Locally? | Used in Production? | Details |
| :--- | :--- | :--- | :--- |
| **Secret Manager** | ✅ Yes | ✅ Yes | Used to store and retrieve Monday.com API keys securely without logging them. |
| **Firestore** | ✅ Yes | ✅ Yes | Used as the state store for `job_id` tracking, statuses, and metadata. |
| **Cloud Storage** | ✅ Yes | ✅ Yes | Used to persist the generated Markdown reports (`pre_migration_report.md`). |
| **Cloud Run (API)** | ❌ No (FastAPI + Uvicorn) | ✅ Yes | Hosts the FastAPI backend as a persistent service. |
| **Cloud Run Jobs** | ❌ No (FastAPI Background Task) | ✅ Yes | Executes the heavy discovery/migration workloads asynchronously. |

## 3. The Local Development Bypasses

When running locally (via `start_local.sh`), the system leverages Application Default Credentials (ADC) via `gcloud auth application-default login` and bypasses certain production orchestrations.

### A. Async Execution Bypass
*   **Production**: `routes.py` calls the Cloud Run API to trigger a standalone **Cloud Run Job** for the discovery phase. This ensures the workload is isolated and doesn't consume the web server's resources.
*   **Local**: Since the `DISCOVERY_JOB_NAME` environment variable is not set locally, `routes.py` falls back to injecting the `execute_discovery_job` function into the FastAPI **BackgroundTasks**. The work happens in the same process as the web server.

### B. Report Download Bypass
*   **Production**: When downloading the report, the API generates a **Signed URL** using the Cloud Run Service Account's private key. This allows the frontend to download the report directly from GCS via a secure, time-limited link, completely bypassing the FastAPI server for bandwidth.
*   **Local**: ADC credentials used locally provide a token, but *not* a private key. Thus, local ADC cannot generate a Signed URL. 
*   **The Fix/Fallback**: When signed URL generation fails, the API gracefully falls back to proxying the file. The FastAPI backend downloads the file from GCS into memory (`blob.download_as_bytes()`) and serves it directly as a standard HTTP Response (`Response(content, media_type="text/markdown")`).

## 4. Authentication Mechanism

*   **Local**: Relies entirely on your user account credentials configured via `gcloud auth application-default login`. Your user account must have permissions to read/write to Secret Manager, Firestore, and GCS in the specified `PROJECT_ID`.
*   **Production**: Authenticates using dedicated **Service Accounts** configured via Terraform (`terraform/main.tf`). The Cloud Run web service uses one service account (with permissions to trigger jobs), while the Cloud Run Job uses another (with permissions to execute the discovery).

## 5. Execution Orchestration (Phase 3 & Beyond)

As the project transitions from read-only Discovery into the Execution phase (writing data to the destination account), the architecture introduces new infrastructure components to handle scale, dependency ordering, and rate limits.

### A. State & Idempotency (Firestore)
*   To ensure mutations are idempotent and relationships (e.g., items within a specific group) are preserved, the system maintains an ID map.
*   **Structure**: For every created entity, a mapping of `source_id -> dest_id` is stored in Firestore, typically as a subcollection under the main job document (e.g., `jobs/{job_id}/id_map`).
*   **Idempotency Checks**: Before executing any create mutation, the execution engine queries this `id_map` collection. If a `dest_id` already exists for the given `source_id`, the creation is safely bypassed.

### B. Cloud Tasks & DAG Gating
*   **DAG Builder**: The orchestrator parses the discovery inventory and builds a Directed Acyclic Graph (DAG) of creation tasks respecting monday.com's strict hierarchy (Workspace → Board → Group → Column → Item → Subitem → Update).
*   **Queues**: Tasks are pushed to GCP Cloud Tasks queues dedicated to specific stages. These queues enforce `max_dispatches_per_second` to provide a coarse hardware-level rate limit.
*   **Gating**: A stage (e.g., Groups) cannot begin execution until the upstream stage (e.g., Boards) is 100% complete. This is managed via Pub/Sub events or Firestore listeners that monitor the completion status of queued tasks and trigger the next stage.
*   **Local Bypass**: When running locally without Cloud Tasks provisioning, the orchestrator executes tasks sequentially or via local async queues (`asyncio.Queue`), mocking the Cloud Tasks dispatch mechanism to maintain developer velocity.
