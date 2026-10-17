locals {
  app = "openmedcheck"

  common_labels = {
    app        = local.app
    env        = var.env
    owner      = var.owner
    managed-by = "terraform"
  }
}
