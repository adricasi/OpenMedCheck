provider "google" {
  project = var.project_id
  region  = var.region

  # Applied to every resource that supports labels.
  default_labels = local.common_labels
}
