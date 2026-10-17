# Design: openmedcheck

- Status: Draft <!-- Draft | In review | Approved -->
- Last updated: 2026-10-17
- Implements: requirements.md (REQ-*, NFR-*)

## Overview
<!-- One paragraph + a diagram (Mermaid) of the main components and data flow. -->
```mermaid
flowchart LR
  user[User] --> api[Service]
```

## Options considered
<!-- 2–3 architecture options with trade-offs; the chosen one links to its ADR. -->

## Components
| Component | Responsibility | Tech / GCP service | Requirements |
|---|---|---|---|

## Data model
<!-- Entities, key fields, ownership, retention, data classification. -->

## Interfaces
<!-- APIs (endpoints, events, CLI), request/response shapes, errors, versioning. -->

## Security design
- Identities: <!-- service accounts per workload, human access -->
- IAM (least privilege):
- Secrets: <!-- Secret Manager, which secrets, who accesses -->
- Network exposure: <!-- public endpoints, ingress protection -->
- Data protection: <!-- encryption, PII handling -->
- Threats considered: <!-- top risks and mitigations -->

## Reliability and operations
- Failure modes and handling:
- Observability: <!-- logs, metrics, alerts, SLO dashboards -->
- Backups / recovery:

## Environments and deployment
<!-- dev/prod projects, CI/CD, rollout and rollback strategy. -->

## Testing strategy
<!-- Unit / integration / e2e: what each level covers; how ACs map to tests. -->

## Cost estimate
<!-- Main cost drivers and a rough monthly range (label as estimate). -->

## Decisions
| ID | Decision | ADR |
|---|---|---|
| D-1 | | docs/adr/000N-... |

## Traceability
| Requirement | Design section(s) |
|---|---|
