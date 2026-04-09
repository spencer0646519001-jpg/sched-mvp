# Sched MVP

Sched MVP is a Django-based restaurant scheduling MVP focused on deterministic scheduling, explainable daily runs, and a reviewable monthly workflow.

The repo is intentionally honest about its current shape:

- Django is the canonical runtime and API surface.
- The demo scheduler is JSON-canonical today.
- The database is real, but it is not yet the canonical scheduler input source.
- FastAPI remains in the repo only as a legacy rollback surface.

## What This Project Does

- Generates daily station assignments from demo scheduler inputs in `data/*.json`.
- Persists daily run history to Django models so runs can be inspected later without overwriting prior same-day runs.
- Exposes a graph-backed daily explain path that returns assignments, decision trace, explanations, and metrics.
- Supports monthly preview, refine, save, auto-restore, and CSV export flows through Django APIs and a lightweight server-rendered UI.
- Uses Django Admin for tenant-scoped modeling and metadata management such as employees, stations, skills, and shift display metadata.

The main reviewer/demo path today is `/ui/monthly`.

## Current Architecture Truth

- Canonical runtime: Django via `manage.py`, `config.asgi`, and `config.wsgi`.
- Legacy runtime: `app/main.py` and `app/api_*.py` FastAPI routes are rollback-only and feature-frozen.
- Canonical Django routes stay under `/api/...`; retained Django compatibility/parity routes are grouped under `/api/legacy/...`.
- Canonical scheduler inputs: the demo scheduler still resolves engine inputs from `data/workers.json`, `data/rules.json`, `data/shifts.json`, and `data/calendar.json`.
- Database role: admin/modeling, metadata overlays, immutable daily run history, and selected read-path support.
- Not true today: a fully DB-backed scheduler input pipeline.
- Monthly scheduling model: `JSON engine inputs + DB overlays + persisted monthly workspace state`.
- Monthly persistence truth: the monthly UI persists a tenant/month workspace document for save/restore behavior, but it does not make the database the canonical scheduler input source.
- Tenant truth: canonical scheduling currently supports only `demo_kitchen`; unsupported tenants fail fast instead of silently reusing demo fixtures.
- UI truth: the monthly UI is intentionally thin and server-rendered. It reuses Django API views in-process rather than hiding the flow behind a separate frontend runtime.

If you want the short architecture walk-through and source-of-truth decision, see:

- `docs/architecture.md`
- `docs/adr/0001_demo_scheduler_source_of_truth.md`

### Intentional Tradeoffs

- JSON remains canonical because it keeps the demo scheduler reproducible and avoids pretending a DB-backed scheduler migration is done when it is not.
- The database is used where it already adds value: admin surfaces, metadata overlays, daily run persistence, and selected reads.
- Monthly persistence stays workspace-scoped: the current working document is durable, while scheduler inputs remain JSON-canonical and monthly cells are not normalized into relational rows.
- FastAPI is still present to reduce migration risk, but it is explicitly not the forward path.
- The project prioritizes explainability, determinism, and inspectability over optimizer sophistication or polished product surfaces.

## Key Engineering Cleanup Highlights

- Deterministic scheduling and reproducibility: repeated daily runs and repeated monthly preview requests are covered by tests for stable output under identical inputs.
- Immutable daily run history: `ScheduleRun` and `Assignment` writes are scoped per run, so newer same-day runs do not overwrite earlier history.
- Honest tenant semantics: canonical scheduling input resolution now rejects unsupported tenants instead of silently falling back to demo fixtures.
- Graph metrics correctness: the LangGraph explain path has direct test coverage for metric accumulation from real trace items.
- Monthly orchestration extraction: request-scoped monthly preview/export behavior is pulled into `core/monthly_workspace_service.py` instead of staying embedded in Django views.
- Monthly refine-stack extraction: parser and apply logic are separated into `core/monthly_refine_parser.py` and `core/monthly_refine_apply.py`.
- Reproducible test and CI story: the default pytest path is explicit, legacy parity tests are marked separately, and CI runs the default suite in a fresh environment.
- Source-of-truth clarity: the repo now documents, tests, and names the JSON-canonical scheduler path and the narrower role of the database more explicitly.

## Local Development

### Canonical Django Path

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver 0.0.0.0:8000
```

Notes:

- `seed_demo` idempotently creates the `demo_kitchen` tenant plus the minimal canonical persistence fixtures used by the daily-run history path: 4 stations and the 12-person demo roster from `data/workers.json`.
- The monthly demo flow is JSON-canonical, so it does not depend on the database being the scheduler source of truth.
- The persisted daily-run write path is still driven by JSON-backed scheduler inputs; `seed_demo` only bootstraps the DB rows that path needs to save immutable run history on a fresh database.
- If you want to inspect admin-backed overlays and history through Django Admin, create a superuser with `python manage.py createsuperuser`.

Useful URLs:

- `http://127.0.0.1:8000/ui/monthly` - main monthly demo/review flow
- `http://127.0.0.1:8000/api/tenants/demo_kitchen/daily-runs/` - canonical persisted daily run API
- `http://127.0.0.1:8000/api/tenants/demo_kitchen/daily-runs-graph/` - graph/explain daily run API
- `http://127.0.0.1:8000/admin/` - admin/modeling surfaces

### Docker

```bash
docker compose up --build
```

Docker is for local dev/demo runtime. The Dockerfile uses Python 3.13 and the same Django path as local development: migrate, seed the demo tenant, then run `manage.py runserver`.

### Legacy FastAPI Surface

FastAPI is not the normal development path. It exists only as a rollback surface and is guarded behind `ENABLE_LEGACY_FASTAPI_RUNTIME=1`.

Django also keeps a small compatibility/parity surface for review and rollback support. Those Django compatibility routes live under `/api/legacy/...` so the main `/api/...` route map stays canonical and reviewer-readable.

## Testing And CI

Default local test path:

```bash
python -m pytest -q
```

Legacy parity tests:

```bash
python -m pytest -q -m legacy
```

Testing notes:

- `python -m pytest -q` is the default suite and the recommended day-to-day path.
- `python -m pytest -q -m legacy` is for manual or release-time parity checks against the legacy FastAPI surface.
- `pytest.ini` excludes legacy tests from the default run.
- CI runs the default suite in a fresh environment after installing dependencies and applying migrations.

Current CI path in `.github/workflows/tests.yml`:

1. Set up Python 3.13.
2. Install `requirements.txt`.
3. Run `python manage.py migrate --noinput`.
4. Run `python test/bootstrap_smoke.py`.
5. Run `python -m pytest -q`.

## What This Project Is / Is Not

This project is:

- a demo-first engineering MVP for explainable restaurant scheduling
- a Django-first backend with a shared scheduling engine
- a repo that shows runtime migration cleanup, determinism work, API boundary cleanup, and testability improvements
- partially DB-integrated in an honest way: admin, overlays, history, and selected reads are real even though scheduler inputs are still JSON-canonical

This project is not:

- a fully productionized scheduling platform
- a fully DB-backed scheduler
- a true multi-tenant scheduling system beyond the `demo_kitchen` demo tenant
- a DB-canonical monthly planning system
- a polished frontend product or optimization-heavy solver

## Repo Structure

- `core/` - Django models, admin, API views, UI views, monthly workspace/refine modules
- `app/` - shared scheduling engine, graph flow, infrastructure adapters, legacy FastAPI wrapper
- `data/` - canonical demo scheduler inputs
- `test/` - pytest coverage for canonical flows and separate legacy parity coverage
- `docs/` - architecture notes and ADRs describing current source-of-truth decisions

## Current Limitations

- The canonical scheduler input path is still JSON-backed, so admin data does not yet replace `data/*.json` as the engine source of truth.
- Monthly persistence covers the current workspace document only; it does not imply DB-canonical scheduler inputs or relational monthly planning.
- Legacy mirror and parity endpoints still exist because the runtime migration is not fully pruned, but Django now quarantines them under `/api/legacy/...`.
- The strongest tenant semantics today are honesty, not breadth: unsupported tenants fail fast instead of pretending to be supported.
