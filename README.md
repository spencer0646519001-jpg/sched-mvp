# Sched MVP — Explainable Kitchen Scheduling Engine

**Sched MVP** is a working engineering MVP for an **explainable staff scheduling engine** designed for professional pastry kitchens.

Instead of focusing on UI polish or heavy optimization, this project prioritizes:

- **correctness**
- **traceability**
- **explainability of scheduling decisions**

It serves as a solid technical foundation for future AI-assisted scheduling systems.

---

## Architecture Truth (Current)

- Canonical backend runtime: Django (`manage.py`, `config.asgi`, `config.wsgi`)
- Main monthly demo/review path: `GET /ui/monthly`
- Canonical demo scheduler input source of truth: `data/workers.json`, `data/rules.json`, `data/shifts.json`, `data/calendar.json`
- Current monthly demo input assembly: JSON engine inputs plus DB-backed overlays/read-path support plus request-scoped leave/refine state
- Current tenant support: canonical scheduling input resolution supports only `demo_kitchen`; other tenant names fail fast instead of reusing demo fixtures
- Current DB role: Django models/admin, metadata overlays, persisted daily run outputs, and selected read-path support; the monthly demo flow is still request-scoped preview/export, not DB-backed monthly plan persistence
- Legacy/non-canonical runtime: `app/main.py` plus `app/api_*.py` FastAPI routes are rollback-only
- Migration/parity surfaces: several Django `*_mirror` endpoints preserve older route shapes while Django is canonical
- Determinism claim scope: the canonical daily scheduler core and the canonical Django monthly preview path are reproducible for identical inputs

See `docs/architecture.md` and `docs/adr/0001_demo_scheduler_source_of_truth.md` for the short architecture walkthrough and current scheduler source-of-truth decision.

---

## Project Overview

In real pastry kitchens:

- staff rotate between stations
- skill distribution is uneven
- absences and constraints are common
- fallback assignments are sometimes unavoidable

Sched MVP makes these trade-offs **explicit and auditable**, rather than hiding them inside opaque logic or heuristics.

The goal is not to claim “optimal schedules”, but to clearly answer:

> *Why was this person assigned here, and what constraints influenced that decision?*

---

## Key Capabilities

### Daily Station Assignment
- skill-aware
- absence-aware
- rule-driven (greedy engine)
- deterministic and reproducible for the canonical daily scheduler path and canonical monthly preview path when called with the same inputs

### Explainable Decisions
- step-by-step decision trace
- per-station explanations
- summary metrics (fallback usage, missing skills, coverage gaps)

### Data-Driven Configuration
- no hard-coded stations or staff
- demo scheduler engine inputs are JSON-canonical today and still loaded from `data/*.json`
- canonical tenant-scoped scheduling currently supports only the `demo_kitchen` demo fixture tenant
- Django Admin / SQLite currently back models, metadata overlays, and persisted run outputs

### Minimal Demo UI
- API driver only
- intended for testing and inspection
- full JSON output visibility

---

## Tech Stack

- Python 3.13 (default CI/test target)
- Django (API + Admin)
- LangGraph (decision flow & explainability)
- SQLite (local development)
- JSON fixtures are the canonical demo scheduler inputs today

---

## Quick Start (Canonical: Django API)

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py migrate
```

### Fresh-checkout default test path

This is the default local test path and the same path exercised by CI.

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py migrate
python -m pytest -q
```

### Run locally (development)

```bash
python manage.py runserver 0.0.0.0:8000
```

Server will be available at:

```text
http://127.0.0.1:8000/
```

### Run with Docker (canonical container entrypoint)

```bash
docker compose up --build
```

Server will be available at:

```text
http://127.0.0.1:8000/
```

### Runtime entrypoints (deployment)

Use Django as the canonical API/runtime entrypoint:

- **ASGI**:
  ```bash
  uvicorn config.asgi:application --host 0.0.0.0 --port 8000
  ```
- **WSGI**:
  ```bash
  gunicorn config.wsgi:application --bind 0.0.0.0:8000
  ```

---

## Emergency rollback only: Legacy FastAPI runtime

The rollback-only FastAPI runtime lives in `app/main.py` and `app/api_*.py`.

The rest of `app/` still contains shared scheduling code used by Django, so `app/` should not be read as "all legacy."

- **Default policy**: disabled
- **Enable switch**: `ENABLE_LEGACY_FASTAPI_RUNTIME=1`
- **Canonical runtime remains Django** (runserver / ASGI / WSGI above)

```bash
ENABLE_LEGACY_FASTAPI_RUNTIME=1 uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Legacy runtime runbook (short)

Use legacy FastAPI only when all below are true:

1. Django runtime has a production-blocking incident.
2. You need temporary service continuity while incident mitigation is in progress.
3. You have an explicit rollback decision recorded by the on-call/owner.

Turn legacy runtime off after incident mitigation:

1. Stop legacy FastAPI process.
2. Remove `ENABLE_LEGACY_FASTAPI_RUNTIME` from runtime environment.
3. Start Django runtime again (`python manage.py runserver` or `uvicorn config.asgi:application`).

---


## Legacy FastAPI Freeze Policy

Legacy FastAPI runtime code (`app/main.py` and `app/api_*.py`) is now **frozen**:

- **Rollback-only** runtime for emergency continuity.
- **Do not add new features** to FastAPI routes.
- Only emergency fixes are allowed while Django remains the canonical runtime.

### Test policy

- Daily/default test run (CI/local):
  ```bash
  python -m pytest -q
  ```

- Manual/release-only legacy parity check:
  ```bash
  python -m pytest -q -m legacy
  ```

> Note: `python -m pytest -q` intentionally excludes legacy parity tests and is the only test command run in default CI.
> For manual/release parity verification, run `python -m pytest -q -m legacy`.
> The legacy parity path is offline-safe in a narrow way: if the rollback-only LLM patch parser cannot run because OpenAI credentials, the LangChain OpenAI package, or network access are unavailable, it returns a deterministic non-adjust result instead of silently succeeding.
> FastAPI DeprecationWarning messages are accepted in legacy code and will be addressed when the legacy runtime is removed.

## Entry Points

### 1) Django Admin (Data Setup)

- `http://127.0.0.1:8000/admin/`

Used to manage:

- Tenants
- Employees
- Stations
- Employee–Station skills

These models are real and used for admin/modeling, metadata overlays, and persistence, but they are not yet the canonical scheduler input source for the current demo flow.

### 2) Simple UI (API Driver / Demo)

- `http://127.0.0.1:8000/api/ui/`
- `http://127.0.0.1:8000/ui/monthly`

Purpose:

- `GET /ui/monthly` is the main monthly reviewer/demo flow today
- preview and CSV export use the same request payload
- refine/apply is preview-only and does not persist a monthly plan

### 3) Scheduling API (Graph-Based Engine)

- `POST /api/tenants/demo_kitchen/daily-runs-graph/`

Example request body:

```json
{
  "date": "2026-01-06",
  "absent": ["Kim", "Spencer"]
}
```

Response includes:

- `out` — final station assignments
- `decision_trace` — engine decision steps
- `explanations` — human-readable reasoning
- `metrics` — high-level summary signals

---

### Current input reality

- this endpoint is served by Django
- the graph/explanation path resolves JSON-canonical demo engine inputs through the shared demo-only resolver and still builds those inputs from `data/*.json`
- `demo_kitchen` is the only supported canonical scheduling tenant today; unsupported tenant names return a truthful error instead of silently using demo data
- successful daily runs are then persisted to `ScheduleRun` / `Assignment`

## Project Structure (Simplified)

Read this structure with two caveats:

- `app/` mixes shared engine code with the rollback-only FastAPI wrapper; it is not all legacy.
- `data/` is still the canonical demo scheduler input source for the main demo paths.

```text
sched-mvp/
├── app/
│   ├── generate_day.py        # core scheduling logic
│   ├── generate_week.py       # week planner
│   ├── generate_month.py      # month planner
│   ├── langgraph_flow.py      # graph + explanation nodes
│   └── ...
├── core/
│   ├── models.py              # Django models
│   ├── api_views.py           # API endpoints
│   ├── admin.py               # Admin configuration
│   └── ui_views.py            # minimal UI
├── graph/
│   └── state.py / nodes/      # LangGraph state & nodes
├── config/
│   └── urls.py / settings.py
└── README.md
```

---

## Why Explainability Matters

Fallback assignments and suboptimal decisions are inevitable in real-world operations.

This MVP ensures that:

- every assignment can be explained
- missing skills are visible
- trade-offs are measurable

Explainability is essential for:

- operational trust
- debugging rules
- future AI assistance
- safe automation

---

## Current Status

✅ Daily scheduling engine

✅ Explainable decision trace & metrics

✅ Django Admin for configuration

✅ Minimal UI for demo

Planned (future):

⏳ Advanced optimization models

⏳ LLM-assisted rule editing

⏳ Rich web UI

---

## Disclaimer

This repository represents a working engineering MVP, not a final product.

Design choices intentionally favor:

- clarity over complexity
- explainability over optimization
- correctness over UI completeness
