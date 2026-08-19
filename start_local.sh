#!/usr/bin/env bash
set -e

echo "=================================================="
echo " Starting Monday.com Migration POC Locally        "
echo "=================================================="

# Provide default mock values for local development if they aren't already set.
# In a deployed environment, these are injected automatically by Cloud Run
# based on our Terraform configuration (see terraform/main.tf).
export PROJECT_ID="${PROJECT_ID:-local-dev-project}"
export REPORTS_BUCKET="${REPORTS_BUCKET:-local-dev-reports-bucket}"

echo "Environment Variables (Simulating Cloud Run env):"
echo "  PROJECT_ID     = $PROJECT_ID"
echo "  REPORTS_BUCKET = $REPORTS_BUCKET"
echo ""
echo "Note: If you want to interact with actual GCP services (Firestore, GCS),"
echo "ensure you have run 'gcloud auth application-default login'."
echo "=================================================="

# 1. Start the FastAPI backend in the background
echo "Starting FastAPI backend on http://localhost:8000 ..."
uv run uvicorn src.api.routes:app --reload --port 8000 &
BACKEND_PID=$!

# Wait a brief moment for backend to initialize
sleep 2

# 2. Start the React frontend in the background
echo "Starting React frontend on http://localhost:5173 ..."
cd frontend && npm run dev &
FRONTEND_PID=$!

# 3. Handle graceful shutdown
cleanup() {
    echo ""
    echo "Shutting down services..."
    kill $BACKEND_PID
    kill $FRONTEND_PID
    exit 0
}

# Trap SIGINT (Ctrl+C) and SIGTERM to run the cleanup function
trap cleanup SIGINT SIGTERM

echo ""
echo "Services are running. Press Ctrl+C to stop."
echo "Frontend Portal: http://localhost:5173"
echo "Backend API:     http://localhost:8000/docs"
echo ""

# Wait for background processes to keep the script running
wait
