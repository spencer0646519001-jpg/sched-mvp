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
- Current scheduling inputs: `data/workers.json`, `data/rules.json`, `data/shifts.json`, `data/calendar.json`
- Current DB role: Django models/admin plus persisted daily run outputs; the monthly demo flow is still request-scoped preview/export, not DB-backed monthly plan persistence
- Legacy/non-canonical runtime: `app/main.py` plus `app/api_*.py` FastAPI routes are rollback-only
- Migration/parity surfaces: several Django `*_mirror` endpoints preserve older route shapes while Django is canonical

See `docs/architecture.md` for the short architecture walkthrough.

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
- deterministic and reproducible

### Explainable Decisions
- step-by-step decision trace
- per-station explanations
- summary metrics (fallback usage, missing skills, coverage gaps)

### Data-Driven Configuration
- no hard-coded stations or staff
- current engine inputs are still loaded from `data/*.json`
- Django Admin / SQLite currently back models and persisted run outputs

### Minimal Demo UI
- API driver only
- intended for testing and inspection
- full JSON output visibility

---

## Tech Stack

- Python 3.11+
- Django (API + Admin)
- LangGraph (decision flow & explainability)
- SQLite (local development)
- JSON fixtures currently drive scheduling inputs

---

## Quick Start (Canonical: Django API)

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate

pip install -r requirements.txt
python manage.py migrate
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
  pytest -q
  ```

- Manual/release-only legacy parity check:
  ```bash
  pytest -q -m legacy
  ```

> Note: `pytest -q` intentionally excludes legacy parity tests (Django is canonical; lower dual-runtime overhead). For manual/release parity verification, run `pytest -q -m legacy`.
> FastAPI DeprecationWarning messages are accepted in legacy code and will be addressed when the legacy runtime is removed.

## Entry Points

### 1) Django Admin (Data Setup)

- `http://127.0.0.1:8000/admin/`

Used to manage:

- Tenants
- Employees
- Stations
- Employee–Station skills

These models are real and used for admin/persistence, but they are not yet the canonical input source for the current monthly demo flow.

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
- the graph/explanation path still builds engine inputs from `data/*.json`
- successful daily runs are then persisted to `ScheduleRun` / `Assignment`

## Project Structure (Simplified)

Read this structure with two caveats:

- `app/` mixes shared engine code with the rollback-only FastAPI wrapper; it is not all legacy.
- `data/` is still the current source of scheduling inputs for the main demo paths.

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
