# Resources go here (or in topic files: network.tf, iam.tf, storage.tf ...).
#
# Example of the expected security baseline for a bucket:
#
# resource "google_storage_bucket" "artifacts" {
#   name                        = "${var.project_id}-${local.app}-artifacts"
#   location                    = var.region
#   uniform_bucket_level_access = true
#   public_access_prevention    = "enforced"
#
#   versioning {
#     enabled = true
#   }
#
#   lifecycle {
#     prevent_destroy = true
#   }
# }
