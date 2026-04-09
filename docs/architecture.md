# Architecture Truth

## Purpose

This repository is a hiring-portfolio scheduling MVP for explainable kitchen staffing. The goal is to make the current system shape reviewable, not to present a finished platform.

## Canonical Backend Runtime Today

- The canonical backend runtime is Django.
- The live entrypoints are `manage.py`, `config/asgi.py`, and `config/wsgi.py`.
- The canonical container server path now runs `uvicorn config.asgi:application` against Django's ASGI app.
- Runtime defaults are intentionally small and env-driven from one settings module: `DJANGO_DEBUG`, `DJANGO_SECRET_KEY`, and `DJANGO_ALLOWED_HOSTS`.
- Django routes are wired through `config/urls.py` into canonical `core/api_urls.py`, quarantined legacy `core/api_urls_legacy.py`, and `core/ui_views.py`.
- In debug/demo mode, `config/asgi.py` wraps Django with the built-in ASGI static-files handler so `/ui/monthly` and admin assets still render under `uvicorn` without adding a production static stack.

## Main Monthly Demo Flow Today

The main reviewer/demo path is `/ui/monthly`.

That page is a server-rendered Django form. The monthly UI and monthly API adapters
now share the same request-free orchestration for these backend operations:

- `POST /api/monthly/preview`
- `POST /api/monthly/refine`
- `POST /api/monthly/export.csv`
- `POST /api/monthly/transcribe`

Current flow:

1. `core/ui_views.py` builds a request payload from `year_month`, `leave_requests`, and optional `refine_text`.
2. `core/ui_views.py` and `core/api_views_monthly.py` both call the same monthly orchestration helpers instead of the UI self-calling Django API views in-process.
3. `core/api_views_monthly.py` builds a month preview from a shared monthly input contract, then chunks through `app/generate_week.py`, which in turn calls `app/generate_day.py`.
4. `refine` produces a preview diff and a preview grid only.
5. `Apply` updates the current in-page working state used for display/export.
6. `Save` persists the current monthly workspace document for the tenant/month.
7. Opening `/ui/monthly` for a month with a saved workspace auto-hydrates the page from that persisted workspace state.

## Scheduling Input Reality Today

- The demo scheduler's canonical engine input source of truth is still `data/*.json`.
- In practice that means `workers.json`, `rules.json`, `shifts.json`, and `calendar.json` still drive the daily, graph, weekly, and monthly scheduling paths.
- Canonical daily, graph, and monthly demo scheduling paths now resolve those inputs through `app/infra/engine_input_resolver.py`.
- The resolver is intentionally honest: `demo_kitchen` is the only supported canonical scheduling tenant today, and unsupported tenant names fail instead of silently reusing demo fixtures.
- `app/infra/monthly_scheduling_inputs.py` assembles the monthly demo input contract as JSON engine inputs plus DB-backed overlays/read-path support plus request leave state.
- Reviewer-facing monthly/demo language behavior is intentionally English-only; legacy `language` request fields are ignored rather than persisted or treated as real multilingual support.
- Raw JSON loading still lives in `app/infra/engine_inputs.py`, with some direct `load_json(...)` calls remaining in legacy/parity helpers and non-scheduling UI lookup helpers.
- Leave requests in the monthly demo are still request payload input layered on top of those JSON fixtures and persisted only as part of the monthly workspace document when the user saves.
- Natural-language monthly refine now operates on the current working state when one exists, but that still does not make monthly scheduling DB-canonical.

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
- Several Django `*_mirror` endpoints are migration/parity surfaces that preserve older route shapes while Django is the canonical runtime.
- Those Django compatibility routes are intentionally quarantined under `/api/legacy/...` via `core/api_urls_legacy.py` so `core/api_urls.py` stays the canonical public API map.
- `docs/fastapi_drf_migration_survey.md` is migration context, not the source of truth for current runtime behavior.

## Near-Term Direction

- Keep Django as the only canonical runtime surface.
- Keep runtime hardening honest: env-driven defaults and an ASGI container path are in scope; reverse proxies, cloud infra, and production-theater settings are not.
- Keep the repo explicit that the demo scheduler is JSON-canonical until a real scheduler-input migration happens.
- Continue shrinking or labeling parity/legacy HTTP surfaces instead of presenting them as a clean target architecture.
- Either move canonical engine inputs onto DB-backed loaders or continue to treat `data/*.json` as explicit demo fixtures until that migration is actually complete.
- Keep the monthly demo flow honest: persisted monthly workspace state is real now, but scheduler engine inputs remain JSON-canonical until a separate migration actually happens.
