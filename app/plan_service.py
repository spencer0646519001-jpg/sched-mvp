# app/plan_service.py
from typing import Any, Dict, Tuple, Optional, List
from app.domain.normalize import normalize_engine_assignments
from app.domain.patch_guard import build_canonical_patch
from app.plan_store import load_plan, save_plan, new_plan_id, list_plans, plan_exists
from app.llm_parser import parse_request_to_patch
from app.generate_day import (
    greedy_assign,
    apply_manual_patch,
)
from app.infra.plan_data_provider import PlanDataProvider, default_plan_data_provider


def create_plan(date: str) -> Dict[str, Any]:
    absent = []
    base_plan = greedy_assign(date, absent)

    # normalize before save
    assignments = base_plan.get("assignments", {})
    norm, norm_errors = normalize_engine_assignments(assignments)
    base_plan["assignments"] = norm
    base_plan.setdefault("errors", [])
    # 你這裡 errors 原本可能是 list[str]，先把 normalize errors 轉成字串或直接 append dict
    # 建議：先直接 append dict（之後再統一 errors schema）
    base_plan["errors"].extend(norm_errors)

    pid = new_plan_id()
    save_plan(pid, base_plan)
    return {"plan_id": pid, "date": date, "plan": base_plan.get("assignments", {})}


def _compute_patch(
    base_plan: Dict[str, Any],
    date: str,
    text: str,
    provider: Optional[PlanDataProvider] = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], List[str]]:
    data = (provider or default_plan_data_provider).get()
    parsed = parse_request_to_patch(text)

    if parsed.get("intent") != "adjust_shift":
        return parsed, None, ["NOT_ADJUST_SHIFT"]

    # --- B3: guard & canonicalize patch BEFORE touching the engine ---
    people_names = [p.get("name", "") for p in data.people if isinstance(p, dict)]
    patch, guard_errors = build_canonical_patch(
        plan_date=date,  # date 永遠用 plan 的，不信任 LLM
        parsed=parsed,
        people_names=people_names,
    )
    if guard_errors:
        return parsed, None, guard_errors

    new_plan, errors = apply_manual_patch(
        base_plan,
        patch,
        data.rules,
        data.shifts_map,
        data.paid_hours_map,
        data.calendar,
        data.people,
    )

    # --- keep your post-normalize of plan assignments (optional but OK) ---
    if new_plan is not None:
        norm, norm_errors = normalize_engine_assignments(
            new_plan.get("assignments", {})
        )
        new_plan["assignments"] = norm
        errors = errors + [f"NORMALIZE:{e['type']}" for e in norm_errors]

    return parsed, new_plan, errors


def patch_preview(
    plan_id: str,
    text: str,
    provider: Optional[PlanDataProvider] = None,
) -> Dict[str, Any]:
    if not plan_id:
        return {
            "success": False,
            "errors": ["MISSING_PLAN_ID"],
        }

    if not plan_exists(plan_id):
        return {
            "plan_id": plan_id,
            "success": False,
            "errors": ["PLAN_NOT_FOUND"],
        }

    bad = _validate_plan_id(plan_id)
    if bad:
        return bad

    base_plan = load_plan(plan_id)
    date = base_plan.get("date") or "2025-11-10"  # 用 plan 的 date 當主

    parsed, new_plan, errors = _compute_patch(base_plan, date, text, provider=provider)

    # --- B3-4: expose LLM uncertainty (no decision yet) ---
    confidence_summary = {
        "name": parsed.get("name_confidence", 1.0) if isinstance(parsed, dict) else 1.0,
        "station": (
            parsed.get("station_confidence", 1.0) if isinstance(parsed, dict) else 1.0
        ),
        "shift": (
            parsed.get("shift_confidence", 1.0) if isinstance(parsed, dict) else 1.0
        ),
    }

    return {
        "plan_id": plan_id,
        "parsed": parsed,
        "confidence_summary": confidence_summary,  # ⭐ 新增但不影響流程
        "success": len(errors) == 0,
        "errors": errors,
        "before_plan": base_plan.get("assignments", {}),
        "after_plan": new_plan.get("assignments", {}) if new_plan is not None else {},
    }


def patch_apply(
    plan_id: str,
    text: str,
    provider: Optional[PlanDataProvider] = None,
) -> Dict[str, Any]:
    if not plan_id:
        return {
            "success": False,
            "errors": ["MISSING_PLAN_ID"],
        }

    if not plan_exists(plan_id):
        return {
            "plan_id": plan_id,
            "success": False,
            "errors": ["PLAN_NOT_FOUND"],
        }
    bad = _validate_plan_id(plan_id)
    if bad:
        return bad

    base_plan = load_plan(plan_id)
    date = base_plan.get("date") or "2025-11-10"  # 用 plan 的 date 當主
    parsed, new_plan, errors = _compute_patch(base_plan, date, text, provider=provider)

    saved = len(errors) == 0 and new_plan is not None

    if saved:
        save_plan(plan_id, new_plan)
    else:
        if len(errors) == 0 and new_plan is None:
            errors = errors + ["PATCH_RESULT_INVALID"]

    return {
        "plan_id": plan_id,
        "parsed": parsed,
        "success": len(errors) == 0,
        "errors": errors,
        "before_plan": base_plan.get("assignments", {}),
        "after_plan": new_plan.get("assignments", {}) if new_plan is not None else {},
        "saved": saved,
    }


def _validate_plan_id(plan_id: str) -> Optional[Dict[str, Any]]:
    if not plan_id:
        return {"success": False, "errors": ["MISSING_PLAN_ID"]}
    if not plan_exists(plan_id):
        return {"success": False, "errors": ["PLAN_NOT_FOUND"], "plan_id": plan_id}
    return None


def normalize_assignments_for_ui(assignments: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    把 engine-friendly 的 assignments 轉成 UI-friendly rows
    input:
      { "GATEAU": [{"name":"A","shift":"1"}], ... }
    output:
      [ {"station":"GATEAU","name":"A","shift":"1"}, ... ]
    """
    rows: List[Dict[str, Any]] = []
    for station, items in (assignments or {}).items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "station": station,
                    "name": item.get("name"),
                    "shift": item.get("shift"),
                }
            )
    return rows


def get_plan(plan_id: str) -> Dict[str, Any]:
    if not plan_id:
        return {"success": False, "errors": ["MISSING_PLAN_ID"]}

    if not plan_exists(plan_id):
        return {"plan_id": plan_id, "success": False, "errors": ["PLAN_NOT_FOUND"]}

    base_plan = load_plan(plan_id)

    return {
        "plan_id": plan_id,
        "date": base_plan.get("date"),
        "assignments": base_plan.get("assignments", {}),
        "success": True,
        "errors": [],
    }


def list_all_plans() -> List[Dict[str, Any]]:
    return list_plans()


from app.plan_store import delete_plan_file


def delete_plan(plan_id: str) -> dict:
    ok = delete_plan_file(plan_id)
    return {
        "plan_id": plan_id,
        "success": ok,
        "errors": [] if ok else ["PLAN_NOT_FOUND"],
    }
