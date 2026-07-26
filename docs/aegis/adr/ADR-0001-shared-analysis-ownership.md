# ADR-0001 - Shared Analysis Ownership and Recovery

Status: `recorded-from-work`
Date: `2026-07-20`

## Source Evidence

- Tasks 3-14 implementation and PostgreSQL/Redis/E2E verification

## Context

A shared public analysis service requires one durable owner for each Bilibili target and analysis version across API, dispatcher, Redis delivery, and workers.

## Decision

PostgreSQL owns targets, attempts, result authority, declarations, generations, dispatch epochs, leases, and the reliable outbox. Redis provides rebuildable delivery acceleration and rate-limit counters. Completion is fenced by target owner, desired analysis version, generation, and live lease. Declarations and analysis results remain independent records.

## Alternatives Considered

- Redis as task authority; per-installation result ownership; coupled declaration and score records; direct unfenced worker upserts.

## Consequences

- Concurrent clients share one execution, Redis loss converges by reconciliation, stale workers cannot overwrite newer results, and PostgreSQL backup is sufficient for durable service state. Delivery remains at-least-once and workers must honor idempotency and fencing.
## Compatibility Boundary

Public API remains keyed by bvid and positive cid; feed lookup remains read-only; Redis data and temporary media are disposable; PostgreSQL schema and migration are the durable compatibility boundary.

## Retirement Impact

No legacy owner is retained. Redis-authoritative task state, per-client results, and media persistence are excluded paths.

## Baseline Sync

- Needed: not-needed
- Target: docs/aegis/specs/2026-07-20-desktop-ai-video-identification-design.md and CONTEXT.md
- Action: cite unchanged
- Reason: The accepted design already specifies these owner boundaries; the ADR records executed rationale and evidence without changing product semantics.

## Evidence References

- task13-final-resource-performance-gates
- task14-e2e-recovery-gates
- task14-release-gates

## Boundary

This ADR is an advisory Aegis Method Pack record. It does not grant completion authority or replace project-authoritative architecture sources.
