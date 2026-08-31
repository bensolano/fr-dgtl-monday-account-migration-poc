# Monday.com Account Migration Assessment Tool

This tool performs a read-only discovery of a Monday.com account and generates a comprehensive Markdown report summarizing the objects discovered and their readiness for automated migration.

## Architecture

The project is built as a microservice architecture ready for GCP deployment:
*   **Backend (API & Workers):** FastAPI (Python 3.12)
*   **Frontend (Portal):** React + Vite (Node 24)
*   **Infrastructure:** Terraform modules for Cloud Run, Cloud Tasks, Firestore, Secret Manager, and Cloud Storage.

For deep dives into the system design, consult the `/docs` folder:
*   [02 - Architecture Details](docs/02-architecture.md)
*   [04 - Data Models & Schemas](docs/04-data-models-and-schemas.md)
*   [08 - Local vs. Production Execution Flow](docs/08-local-vs-prod-architecture.md)

## Core Capabilities (Phase 3 Completed)
*   **Read-Only Discovery**: Fully mapping workspaces, boards, groups, items, and columns.
*   **Classification Engine**: Cross-referencing against Monday's capability matrix to surface blocked fields.
*   **Orchestration DAG**: Transforming inventory into an explicitly ordered graph (Workspaces -> Boards -> Groups -> Columns -> Items) to adhere to strict parent-child constraints.
*   **Cloud Tasks Execution**: Queuing workloads asynchronously across dedicated GCP Cloud Tasks queues with rate limits per stage.
*   **Proactive Rate Limiting**: Global `TokenBucket` maintained in Firestore using a dynamic Re-enqueue pattern for precise, cost-effective scheduling around Monday.com rate limits.
*   **Idempotency Engine**: Firestore `source_id -> dest_id` mapping preventing duplicate entity creation on network retries.

## Local Development & Testing

We provide a single script to spin up the entire application locally for testing.

### Prerequisites
1.  Install [`uv`](https://github.com/astral-sh/uv) for Python management.
2.  Install [Node.js 24](https://nodejs.org/).
3.  *(Optional but Recommended)* To test the GCP integrations locally (Firestore, GCS), authenticate with your GCP account:
    ```bash
    gcloud auth application-default login
    ```

### Environment Variables & Configuration

The backend relies on the following environment variables. In Cloud Run, these are injected automatically via our CI/CD pipeline (Cloud Build) and Terraform configuration. For local development, copy the provided example file:

```bash
cp .env.example .env
```

**Variables:**
*   `PROJECT_ID`: The Google Cloud Project ID (e.g., `sandbox-bsolano`).
*   `REGION`: The GCP region (e.g., `europe-west1`).
*   `REPORTS_BUCKET`: The GCS bucket name for storing generated reports.
*   `DISCOVERY_JOB_NAME`: The Cloud Run Job name used to spawn background discovery workers.
*   `SERVICE_URL`: The URL of the FastAPI service, used when spawning background Cloud Tasks.
*   `K_SERVICE`: Provided automatically by Cloud Run. When absent, the application defaults to "local execution mode" (e.g., bypassing GCP Tasks in favor of asyncio).

### Starting the App
Run the following script from the root directory:
```bash
./start_local.sh
```

**What this script does:**
1.  **Environment Variables:** It automatically exports mock values for `PROJECT_ID` and `REPORTS_BUCKET` to your local terminal session. *Note: When deployed to GCP, you do not need to manage these manually; Terraform injects these directly into the Cloud Run container environment (see `terraform/main.tf`).*
2.  **Starts Backend:** Spools up the FastAPI server on `http://localhost:8000`.
3.  **Starts Frontend:** Spools up the Vite dev server on `http://localhost:5173`.

Once running, open [http://localhost:5173](http://localhost:5173) in your browser to enter your API keys and generate a report.

## Deployment

We strictly separate **Infrastructure Provisioning** (Terraform) from **Application Deployment** (Cloud Build).

1.  **Provision Infrastructure:**
    First, use Terraform to provision the foundational resources (Firestore, Storage, Secret Manager, Service Accounts, and Artifact Registry).
    ```bash
    cd terraform
    terraform init
    terraform apply -var="project_id=YOUR_PROJECT_ID"
    ```

2.  **Deploy Application (Manual CI/CD Trigger):**
    Once the base infrastructure exists, use Cloud Build to build the Docker images and deploy them to Cloud Run. The build script automatically links the deployed services to the strict Service Accounts created by Terraform.
    ```bash
    cd ..
    PROJECT_ID=YOUR_PROJECT_ID ./deploy.sh
    ```
    *Note: In a true production environment, `cloudbuild.yaml` would be triggered automatically by a GitHub push rather than `deploy.sh`.*

## Code Quality
To run the offline Python test suite and enforce formatting:
```bash
uv run pytest tests/
uv run ruff check --fix .
uv run ruff format .
```
