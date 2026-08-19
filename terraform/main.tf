# Enable required APIs
resource "google_project_service" "services" {
  for_each = toset([
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "firestore.googleapis.com",
    "storage.googleapis.com",
    "cloudbuild.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
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


# --- Cloud Run Job (Discovery) ---
resource "google_cloud_run_v2_job" "discovery_job" {
  name     = "migration-discovery-job"
  location = var.region

  template {
    template {
      service_account = google_service_account.job_sa.email
      containers {
        image = var.job_image
        env {
          name  = "PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "REPORTS_BUCKET"
          value = google_storage_bucket.reports_bucket.name
        }
        # In Cloud Run Jobs, we will pass JOB_ID as an execution environment variable
      }
    }
  }
  depends_on = [google_project_service.services]
}


# --- Cloud Run Service (API) ---
resource "google_cloud_run_v2_service" "api_service" {
  name     = "migration-api"
  location = var.region
  
  template {
    service_account = google_service_account.api_sa.email
    containers {
      image = var.api_image
      
      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "REGION"
        value = var.region
      }
      env {
        name  = "REPORTS_BUCKET"
        value = google_storage_bucket.reports_bucket.name
      }
      env {
        name  = "DISCOVERY_JOB_NAME"
        value = google_cloud_run_v2_job.discovery_job.name
      }
    }
  }
  depends_on = [google_project_service.services]
}

# Make API publicly accessible (or restrict via IAM depending on requirements)
resource "google_cloud_run_v2_service_iam_member" "api_public" {
  name     = google_cloud_run_v2_service.api_service.name
  location = google_cloud_run_v2_service.api_service.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Cloud Run Service (Portal Frontend) ---
resource "google_cloud_run_v2_service" "portal_service" {
  name     = "migration-portal"
  location = var.region
  
  template {
    containers {
      image = var.portal_image
      
      # Since it's a frontend, the API URL needs to be injected or proxied
      # For a static React build, we might need a small NGINX replacement logic 
      # or configure CORS properly on the API.
    }
  }
  depends_on = [google_project_service.services]
}

resource "google_cloud_run_v2_service_iam_member" "portal_public" {
  name     = google_cloud_run_v2_service.portal_service.name
  location = google_cloud_run_v2_service.portal_service.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}
