# Sched MVP — Explainable Kitchen Scheduling Engine

**Sched MVP** is a working engineering MVP for an **explainable staff scheduling engine** designed for professional pastry kitchens.

Instead of focusing on UI polish or heavy optimization, this project prioritizes:

- **correctness**
- **traceability**
- **explainability of scheduling decisions**

It serves as a solid technical foundation for future AI-assisted scheduling systems.

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
- all configuration managed via **Django Admin**
- easy to adapt to different kitchens

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
- JSON-based rules & constraints

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

FastAPI implementation remains in `app/` as a **rollback-only legacy runtime**.

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

Legacy FastAPI code under `app/` is now **frozen**:

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

All scheduling logic depends on this data. No station names or assignments are hard-coded.

### 2) Simple UI (API Driver / Demo)

- `http://127.0.0.1:8000/api/ui/`
- `http://127.0.0.1:8000/ui/monthly`

Purpose:

- trigger daily scheduling
- preview JSON output
- inspect engine behavior without external tools

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

## Project Structure (Simplified)

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
