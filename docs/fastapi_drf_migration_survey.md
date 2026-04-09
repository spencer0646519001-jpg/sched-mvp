# FastAPI usage survey and DRF migration plan input

This document is a historical FastAPI inventory, not the source of truth for the current Django route map.
Canonical Django routes live under `/api/...` in `core/api_urls.py`, while retained Django parity routes now live under `/api/legacy/...` in `core/api_urls_legacy.py`.

Canonical baseline commit used for this survey: `90f09944170679d5385de7aa6470ac5c9da274c3`.

## FastAPI app instantiation
- `app/main.py`
  - `app = FastAPI(...)`
  - CORS middleware setup via `CORSMiddleware`
  - startup hook `init_globals`
  - includes routers: `week_router`, `calendar_router` (prefix `/api`), `llm_patch_router` (prefix `/api`)

## FastAPI routes and handlers inventory

### `app/main.py`
1. `GET /`
   - Handler: `healthcheck`
   - Returns: `{"status": "ok"}`
   - Calls: none
   - ORM use: no

2. `GET /generate/day/{date}`
   - Handler: `generate_day_api`
   - Returns: output of `gd.greedy_assign(date, absent_list)`
   - Calls: `app.generate_day.greedy_assign`
   - ORM use: indirect only through engine infra if configured; handler itself does not use Django ORM directly

### `app/api_week.py`
3. `GET /api/week`
   - Handler: `get_week`
   - Returns: `week_state["week_plan"]`
   - Calls: `generate_week`
   - ORM use: no direct ORM call in handler

4. `GET /api/week/summary`
   - Handler: `get_week_summary`
   - Returns: `summarize_week(week_state)` map by person
   - Calls: `generate_week`, `summarize_week`
   - ORM use: no direct ORM call in handler

5. `GET /api/week_csv`
   - Handler: `get_week_csv`
   - Returns: FastAPI `StreamingResponse` CSV
   - Calls: `generate_week`
   - ORM use: no direct ORM call in handler

6. `GET /api/month`
   - Handler: `get_month`
   - Returns: month state dict (`month_start`, `month_end`, `plan`, `summary`, `overtime`)
   - Calls: local helper `_generate_month_state`; internally uses `generate_week` and `summarize_week`
   - ORM use: no direct ORM call in handler

7. `GET /api/month_csv`
   - Handler: `api_month_csv`
   - Returns: FastAPI `StreamingResponse` CSV
   - Calls: local helper `_generate_month_state`
   - ORM use: no direct ORM call in handler

### `app/api_calendar.py` (mounted with `/api` prefix from `app/main.py`)
8. `GET /api/calendar/month`
   - Handler: `api_calendar_month`
   - Returns: `build_month(start_date)` payload
   - Calls: `app.month_service.build_month`
   - ORM use: no direct ORM in handler

9. `GET /api/calendar/month_csv`
   - Handler: `api_calendar_month_csv`
   - Returns: FastAPI `Response` CSV or text error payload on failure
   - Calls: `build_month(start_date)`
   - ORM use: no direct ORM in handler

### `app/api_llm_patch.py` (mounted with `/api` prefix from `app/main.py`)
10. `POST /api/plan/create`
    - Handler: `api_plan_create`
    - Returns: result from `create_plan`
    - Calls: `app.plan_service.create_plan`
    - ORM use: none

11. `POST /api/plan/patch_preview`
    - Handler: `api_plan_patch_preview`
    - Returns: result from `patch_preview`
    - Calls: `app.plan_service.patch_preview`
    - ORM use: none

12. `POST /api/plan/patch_apply`
    - Handler: `api_plan_patch_apply`
    - Returns: result from `patch_apply`
    - Calls: `app.plan_service.patch_apply`
    - ORM use: none

13. `GET /api/plan/get`
    - Handler: `api_plan_get`
    - Returns: plan payload from `get_plan` or raises HTTP exceptions
    - Calls: `app.plan_service.get_plan`
    - ORM use: none

14. `GET /api/plan/list`
    - Handler: `api_plan_list`
    - Returns: list from `list_all_plans`
    - Calls: `app.plan_service.list_all_plans`
    - ORM use: none

15. `DELETE /api/plan/delete`
    - Handler: `api_plan_delete`
    - Returns: delete result from `delete_plan` or raises HTTP exceptions
    - Calls: `app.plan_service.delete_plan`
    - ORM use: none

## FastAPI-specific imports (full repository scope)
- `app/main.py`: `FastAPI`, `HTTPException`, `CORSMiddleware`
- `app/api_week.py`: `APIRouter`, `Query`, `StreamingResponse`
- `app/api_calendar.py`: `APIRouter`, `Response`
- `app/api_llm_patch.py`: `APIRouter`, `HTTPException`

## FastAPI-specific tests
- Survey note (time-bounded): this section was accurate at the baseline commit above, but is now outdated.
- Current repository has FastAPI-vs-Django parity coverage in `test/test_api_parity.py` (imports `app.main` and uses FastAPI `TestClient`).
