variable "project_id" {
  description = "The GCP Project ID"
  type        = string
}

variable "region" {
  description = "The GCP region to deploy resources to"
  type        = string
  default     = "europe-west1"
}

variable "portal_image" {
  description = "Container image URL for the React frontend portal"
  type        = string
}

variable "api_image" {
  description = "Container image URL for the FastAPI backend"
  type        = string
}

variable "job_image" {
  description = "Container image URL for the Discovery Cloud Run Job"
  type        = string
}
