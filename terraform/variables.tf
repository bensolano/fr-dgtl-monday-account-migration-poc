variable "project_id" {
  description = "The GCP Project ID"
  type        = string
  default     = "sandbox-bsolano"
}

variable "region" {
  description = "The GCP region to deploy resources to"
  type        = string
  default     = "europe-west1"
}
