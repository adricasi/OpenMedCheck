# openmedcheck

TODO: one-line description of openmedcheck.

## Getting started
```bash
uv sync                                  # install / update the environment
uv run pytest --cov                      # tests with coverage
uv run ruff check --fix . && uv run ruff format .   # lint + format
uv run mypy src                          # type check
uv run pip-audit                         # dependency vulnerabilities
```

```bash
cd infra
terraform fmt -recursive && terraform init -backend=false && terraform validate
tflint --init && tflint --recursive
checkov -d . --quiet
# Plan (human, read-only identity):
terraform plan -lock=false -var-file=envs/dev.tfvars -out=tfplan && terraform show -json tfplan > plan.json
# Review: read plan.json and fix every finding before anyone applies.
# Apply: humans only, after review.
```

## Development workflow (spec-driven)
The specification in `docs/spec/` is the source of truth; each task is implemented from it with tests named after the acceptance criteria.
Commits run pre-commit (formatters, linters, gitleaks); a human reviews and merges pull requests.

## Specification
See [docs/spec](docs/spec/): product, requirements, design and task plan.

## Architecture decisions
See [docs/adr](docs/adr/).
