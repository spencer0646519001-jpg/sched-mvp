# ADR 0001: Demo Scheduler Source of Truth

## Status

Accepted

## Context

This repository contains real Django models, admin surfaces, metadata overlays,
and persisted daily run history. That can make the current scheduler input
source of truth easy to overread.

For the current demo scheduler, the important question is narrower: what is the
canonical input source for scheduling engine runs today?

## Decision

- The demo scheduler is JSON-canonical today.
- Canonical demo scheduler engine inputs come from `data/*.json`.
- The current monthly demo flow should be read as JSON engine inputs plus
  DB-backed overlays/read-path support plus request-scoped leave/refine state.
- The database is currently used for admin/modeling, metadata overlays,
  selected read-path support, and daily run history.
- This ADR does not introduce a DB migration, scheduler replatform, or monthly
  persistence change.

## Consequences

- Code, docs, and naming should not imply that DB-backed scheduler inputs are
  already canonical when they are not.
- DB-backed helpers may remain in the repo, but they should be described
  honestly as overlays, read helpers, admin/modeling support, or non-canonical
  helper paths until a real scheduler-input migration happens.
