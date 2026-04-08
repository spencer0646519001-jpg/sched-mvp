# Architecture Truth

## Purpose

This repository is a hiring-portfolio scheduling MVP for explainable kitchen staffing. The goal is to make the current system shape reviewable, not to present a finished platform.

## Canonical Backend Runtime Today

- The canonical backend runtime is Django.
- The live entrypoints are `manage.py`, `config/asgi.py`, and `config/wsgi.py`.
- Django routes are wired through `config/urls.py` into `core/api_views.py` and `core/ui_views.py`.

## Main Monthly Demo Flow Today

The main reviewer/demo path is `/ui/monthly`.

That page is a server-rendered Django form that internally calls these Django API views:

- `POST /api/monthly/preview`
- `POST /api/monthly/refine`
- `POST /api/monthly/export.csv`
- `POST /api/monthly/transcribe`

Current flow:

1. `core/ui_views.py` builds a request payload from `year_month`, `language`, `leave_requests`, and optional `refine_text`.
2. The page uses `RequestFactory` to call the monthly Django API views in-process.
3. `core/api_views.py` builds a month preview from a shared monthly input contract, then chunks through `app/generate_week.py`, which in turn calls `app/generate_day.py`.
4. `refine` produces a preview diff and a preview grid only.
5. The current `Apply / Save` action in the UI does not persist a monthly plan to the database. It only promotes the refine preview into the page state used for display/export.

## Scheduling Input Reality Today

- The demo scheduler's canonical engine input source of truth is still `data/*.json`.
- In practice that means `workers.json`, `rules.json`, `shifts.json`, and `calendar.json` still drive the daily, graph, weekly, and monthly scheduling paths.
- Canonical daily, graph, and monthly demo scheduling paths now resolve those inputs through `app/infra/engine_input_resolver.py`.
- The resolver is intentionally honest: `demo_kitchen` is the only supported canonical scheduling tenant today, and unsupported tenant names fail instead of silently reusing demo fixtures.
- `app/infra/monthly_scheduling_inputs.py` assembles the monthly demo input contract as JSON engine inputs plus DB-backed overlays/read-path support plus request-scoped leave/refine state.
- Raw JSON loading still lives in `app/infra/engine_inputs.py`, with some direct `load_json(...)` calls remaining in legacy/parity helpers and non-scheduling UI lookup helpers.
- Leave requests in the monthly demo are request-scoped input layered on top of those JSON fixtures.
- Natural-language monthly refine also operates on the request-scoped preview; it is not a persisted monthly planning workflow yet.

## DB vs JSON Today

- Django models and SQLite are real and in active use.
- The database currently provides:
  - runtime shell and routing through Django
  - admin-managed entities such as tenants, employees, stations, and skills
  - metadata overlays and selected read-path support for monthly/demo surfaces
  - persisted daily run outputs via `ScheduleRun` and `Assignment`
- The database is not yet the canonical source of scheduler engine inputs for the current monthly demo flow.
- There are DB loader/adaptor modules in the repo, but they currently support overlays, admin-backed reads, or non-canonical helpers; the canonical scheduling paths still call the JSON-backed input builder today.

## Legacy, Deprecated, Or Non-Canonical Areas

- `app/main.py` plus `app/api_week.py`, `app/api_calendar.py`, and `app/api_llm_patch.py` are the rollback-only legacy FastAPI runtime.
- `app/` is not wholly legacy. Most of the shared scheduling engine still lives there and is used by the canonical Django runtime.
- Several Django `*_mirror` endpoints in `core/api_views.py` and `core/api_urls.py` are migration/parity surfaces that preserve older route shapes while Django is the canonical runtime.
- `docs/fastapi_drf_migration_survey.md` is migration context, not the source of truth for current runtime behavior.

## Near-Term Direction

- Keep Django as the only canonical runtime surface.
- Keep the repo explicit that the demo scheduler is JSON-canonical until a real scheduler-input migration happens.
- Continue shrinking or labeling parity/legacy HTTP surfaces instead of presenting them as a clean target architecture.
- Either move canonical engine inputs onto DB-backed loaders or continue to treat `data/*.json` as explicit demo fixtures until that migration is actually complete.
- Keep the monthly demo flow honest: request-scoped preview/refine/export first, persistence later if and when it is really implemented.
