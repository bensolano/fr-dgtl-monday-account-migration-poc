#!/usr/bin/env bash
set -e

if [ -z "$PROJECT_ID" ]; then
    echo "Error: PROJECT_ID environment variable is not set."
    echo "Usage: PROJECT_ID=my-project ./deploy.sh"
    exit 1
fi

REGION=${REGION:-europe-west1}

echo "=================================================="
echo " Submitting manual Cloud Build for Project: $PROJECT_ID "
echo " Region: $REGION "
echo "=================================================="

gcloud builds submit --config cloudbuild.yaml \
    --substitutions=_REGION=$REGION,COMMIT_SHA=$(git rev-parse --short HEAD) \
    --project=$PROJECT_ID .
