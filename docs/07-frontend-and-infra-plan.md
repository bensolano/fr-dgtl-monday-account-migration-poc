# Frontend and Infrastructure Plan

## 1. Objective
Transition the current CLI-based Monday.com migration POC into a production-ready microservice architecture. This includes introducing a lightweight, modern frontend for users to enter API keys and download reports, exposing the existing Python logic via a REST API, and defining the GCP cloud infrastructure components required for deployment.

## 2. Architecture & Components

### 2.1. Frontend (The Portal)
*   **Recommendation:** React + Vite (TypeScript) with Vanilla CSS.
*   **Why:** In a production microservice architecture, decoupling the frontend from the backend is best practice. React + Vite is significantly lighter than Angular, offers rapid development, compiles down to static assets, and is trivial to host in a container or static storage.
*   **Responsibilities:**
    *   Present a simple UI to capture the Source and Destination Monday.com API keys.
    *   Trigger the Discovery Job via the Backend API.
    *   Poll for job status.
    *   Display a summary of the report and provide a download link (PDF/Markdown/CSV).

### 2.2. Backend API (The Orchestrator/Gateway)
*   **Technology:** Python (FastAPI).
*   **Responsibilities:**
    *   Expose a RESTful API (`/api/v1/jobs`, `/api/v1/jobs/{id}/status`, `/api/v1/jobs/{id}/report`).
    *   Handle incoming requests from the Portal.
    *   Trigger the asynchronous Cloud Run Job for the Discovery phase using the Google Cloud SDK.
    *   Serve as the intermediary between the Frontend, the State Store (Firestore), and the Jobs.

### 2.3. Asynchronous Workers
*   **Discovery Job:** Cloud Run Job (Python). Contains the existing `src/discovery.py`, `src/classification.py`, and `src/report_generator.py` logic. It reads credentials securely, paginates the source account, and saves the report to Cloud Storage.

## 3. GCP Infrastructure (Full Architecture)
We will target a robust, Terraform-ready GCP architecture:

1.  **Cloud Run Services:**
    *   `migration-portal`: Hosts the React frontend (NGINX container serving static files).
    *   `migration-api`: Hosts the FastAPI backend.
2.  **Cloud Run Jobs:**
    *   `migration-discovery-job`: Executes the heavy, long-running discovery process.
3.  **Storage & State:**
    *   **Secret Manager:** Stores the user-provided API keys temporarily, scoped by `job_id`.
    *   **Firestore:** Stores job state (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`).
    *   **Cloud Storage:** Stores the generated reports for download.
    *   **Authentication:** Application Default Credentials (ADC) will be used exclusively for all GCP interactions, both locally and in deployed environments.
4.  **Future Execution Phase (Not built yet, but planned for):**
    *   **Cloud Tasks:** For rate-limited execution of the actual migration writes.

## 4. Implementation Steps

1.  **Step 1: Backend API Refactor (FastAPI)**
    *   Add `fastapi` and `uvicorn` to the project.
    *   Create `src/api/routes.py` to handle job creation and status polling.
    *   Abstract the existing `main.py` logic so it can be invoked via CLI (for the Cloud Run Job) or triggered via the API.
2.  **Step 2: Frontend Scaffold (React + Vite)**
    *   Initialize a new Vite project in a `frontend/` directory.
    *   Build a simple form component for API key entry.
    *   Build a status polling component and report download link.
3.  **Step 3: State Management & Storage Integration**
    *   Implement basic Firestore read/write logic for job tracking.
    *   Implement basic Cloud Storage upload logic for the generated reports.
4.  **Step 4: Infrastructure as Code (Terraform Prep)**
    *   Ensure all components are Dockerized (`Dockerfile.frontend`, `Dockerfile.api`, `Dockerfile.job`).
    *   Define the required environment variables and service accounts needed for the Terraform deployment.

## 5. Verification
*   **Local E2E:** Run the React dev server and FastAPI server locally. Enter keys in the UI, verify that FastAPI creates a job record, simulates the Discovery job, and returns a downloadable report.
*   **Docker:** Build and run all components via `docker-compose` locally to verify container boundaries before GCP deployment.
