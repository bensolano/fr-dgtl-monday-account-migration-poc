# Enable required APIs
resource "google_project_service" "services" {
  for_each = toset([
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "firestore.googleapis.com",
    "storage.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudtasks.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

# --- Cloud Tasks Queues ---
# Dedicated queues per stage to allow distinct rate limiting and scaling

resource "google_cloud_tasks_queue" "workspaces_queue" {
  name     = "migration-workspaces"
  location = var.region

  rate_limits {
    max_dispatches_per_second = 10
    max_concurrent_dispatches = 10
  }

  retry_config {
    max_attempts = -1 # Let application logic or DLQ handle exact cutoff
    min_backoff  = "1s"
    max_backoff  = "3600s"
  }

  depends_on = [google_project_service.services]
}

resource "google_cloud_tasks_queue" "boards_queue" {
  name     = "migration-boards"
  location = var.region

  rate_limits {
    max_dispatches_per_second = 5
    max_concurrent_dispatches = 5
  }

  retry_config {
    max_attempts = -1
    min_backoff  = "1s"
    max_backoff  = "3600s"
  }

  depends_on = [google_project_service.services]
}

resource "google_cloud_tasks_queue" "groups_queue" {
  name     = "migration-groups"
  location = var.region

  rate_limits {
    max_dispatches_per_second = 10
    max_concurrent_dispatches = 10
  }

  retry_config {
    max_attempts = -1
    min_backoff  = "1s"
    max_backoff  = "3600s"
  }

  depends_on = [google_project_service.services]
}

resource "google_cloud_tasks_queue" "columns_queue" {
  name     = "migration-columns"
  location = var.region

  rate_limits {
    max_dispatches_per_second = 15
    max_concurrent_dispatches = 15
  }

  retry_config {
    max_attempts = -1
    min_backoff  = "1s"
    max_backoff  = "3600s"
  }

  depends_on = [google_project_service.services]
}

resource "google_cloud_tasks_queue" "items_queue" {
  name     = "migration-items"
  location = var.region

  rate_limits {
    max_dispatches_per_second = 20
    max_concurrent_dispatches = 50
  }

  retry_config {
    max_attempts = -1
    min_backoff  = "1s"
    max_backoff  = "3600s"
  }

  depends_on = [google_project_service.services]
}

# --- Storage ---
# Bucket for generated reports
resource "google_storage_bucket" "reports_bucket" {
  name                        = "${var.project_id}-migration-reports"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true

  lifecycle_rule {
    condition {
      age = 30 # Auto-delete reports after 30 days
    }
    action {
      type = "Delete"
    }
  }
}

# --- Service Accounts ---
resource "google_service_account" "api_sa" {
  account_id   = "migration-api-sa"
  display_name = "Monday Migration API Service Account"
}

resource "google_service_account" "job_sa" {
  account_id   = "migration-job-sa"
  display_name = "Monday Migration Discovery Job Service Account"
}

# --- IAM Bindings for API ---
# API needs to trigger jobs, write to Firestore, generate signed URLs for GCS, create secrets
resource "google_project_iam_member" "api_datastore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

resource "google_project_iam_member" "api_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

resource "google_project_iam_member" "api_run_jobs_executor" {
  project = var.project_id
  role    = "roles/run.jobsExecutorWithOverrides"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

resource "google_project_iam_member" "api_secret_creator" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

resource "google_project_iam_member" "api_secret_manager" {
  project = var.project_id
  role    = "roles/secretmanager.admin"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

resource "google_project_iam_member" "api_cloud_tasks_enqueuer" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

resource "google_storage_bucket_iam_member" "api_storage_viewer" {
  bucket = google_storage_bucket.reports_bucket.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.api_sa.email}"
}

# --- IAM Bindings for Job ---
# Job needs to read secrets, write to Firestore, write to GCS
resource "google_project_iam_member" "job_datastore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.job_sa.email}"
}

resource "google_project_iam_member" "job_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.job_sa.email}"
}

resource "google_storage_bucket_iam_member" "job_storage_creator" {
  bucket = google_storage_bucket.reports_bucket.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.job_sa.email}"
}


# --- Artifact Registry ---
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "migration-repo"
  description   = "Docker repository for migration POC"
  format        = "DOCKER"
  depends_on    = [google_project_service.services]
}

# --- Cloud Build IAM ---
data "google_project" "project" {}

# Allow Cloud Build to deploy to Cloud Run
resource "google_project_iam_member" "cloudbuild_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}

# Allow Cloud Build to attach the API and Job service accounts to Cloud Run
resource "google_project_iam_member" "cloudbuild_sa_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}
