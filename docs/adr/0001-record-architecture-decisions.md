# 0001. Record architecture decisions

- Status: Accepted
- Date: 2026-10-17

## Context
We need a lightweight way to record significant technical decisions and their reasons,
readable by anyone working on this repository.

## Decision
We record Architecture Decision Records in `docs/adr/`, numbered sequentially, using the
lightweight MADR-style template. Accepted ADRs are not rewritten; new ADRs supersede them.

## Consequences
- Decisions and trade-offs are discoverable next to the code.
- Contributors can follow past decisions instead of re-deciding them.
