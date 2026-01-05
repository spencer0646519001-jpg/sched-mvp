# app/plan_store.py
import json
import os
import uuid
from typing import Any, Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # 專案根目錄（sched-mvp）
PLANS_DIR = os.path.join(BASE_DIR, "state", "plans")


def _ensure_dirs() -> None:
    os.makedirs(PLANS_DIR, exist_ok=True)


def new_plan_id() -> str:
    return uuid.uuid4().hex[:12]


def plan_path(plan_id: str) -> str:
    _ensure_dirs()
    return os.path.join(PLANS_DIR, f"{plan_id}.json")


def save_plan(plan_id: str, plan: Dict[str, Any]) -> None:
    path = plan_path(plan_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

def plan_exists(plan_id: str) -> bool:
    path = plan_path(plan_id)
    return os.path.exists(path)

def load_plan(plan_id: str) -> Dict[str, Any]:
    path = plan_path(plan_id)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Plan not found: {plan_id}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def list_plans() -> List[Dict[str, Any]]:
    """
    列出目前 state/plans 底下所有 plan_id + date。
    """
    _ensure_dirs()
    results = []

    for filename in os.listdir(PLANS_DIR):
        if not filename.endswith(".json"):
            continue

        plan_id = filename[:-5]
        path = os.path.join(PLANS_DIR, filename)

        try:
            with open(path, "r", encoding="utf-8") as f:
                plan = json.load(f)
        except Exception:
            continue

        results.append({
            "plan_id": plan_id,
            "date": plan.get("date"),
        })

    results.sort(key=lambda x: (x.get("date") or "", x["plan_id"]))
    return results
def delete_plan_file(plan_id: str) -> bool:
    path = plan_path(plan_id)
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True
