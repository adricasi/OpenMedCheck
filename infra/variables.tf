variable "project_id" {
  type        = string
  description = "GCP project ID to deploy into."

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid GCP project ID."
  }
}

variable "region" {
  type        = string
  description = "Default GCP region."
  default     = "europe-southwest1"
}

variable "env" {
  type        = string
  description = "Environment name."

  validation {
    condition     = contains(["dev", "staging", "prod"], var.env)
    error_message = "env must be one of: dev, staging, prod."
  }
}

variable "owner" {
  type        = string
  description = "Owner label (team or person), lowercase."
}
