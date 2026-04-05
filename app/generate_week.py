# app/generate_week.py
# -----------------------------------------------
# Week-level schedule generator based on generate_day.greedy_assign().
# Supports continuity by carrying selected state across week boundaries.
# -----------------------------------------------

import json
import argparse
from datetime import timedelta
from dateutil import parser as dtparser
from typing import TYPE_CHECKING, Dict, List

# Use generate_day utilities for day planning.
from . import generate_day as gd
from app.week_utils import pick_chefs_for_day, CHEF_LIST
from app.infra.engine_inputs import build_inputs_from_json

import csv
from pathlib import Path

if TYPE_CHECKING:
    from app.generate_day import EngineInputs


def load_rules():
    rules_file = Path(__file__).parent.parent / "data" / "rules.json"
    if not rules_file.exists():
        return {}
    with open(rules_file, encoding="utf-8") as f:
        return json.load(f)


# -------- Week State Initialization --------
def init_week_state(people: List[dict]) -> dict:
    """
    Build an empty week state:
      - days_worked: number of worked days per person
      - days_off: number of off days per person
      - consecutive_days: current consecutive-workday streak
      - weekly_hours: accumulated weekly hours
      - shift_count: per-shift counter placeholder
      - week_plan: date_str -> day plan
    """
    names = [p["name"] for p in people]

    return {
        "days_worked": {n: 0 for n in names},
        "days_off": {n: 0 for n in names},
        "consecutive_days": {n: 0 for n in names},
        "weekly_hours": {n: 0.0 for n in names},
        "shift_count": {
            n: {"A": 0, "D": 0, "1": 0, "2": 0, "3": 0, "4": 0} for n in names
        },
        "week_plan": {},  # date_str -> plan
    }


# -------- Week State Update After Each Day --------
def update_week_state(state: dict, day_result: dict) -> None:
    """
    Merge one day result into week state:
      - days_worked / days_off
      - consecutive_days
      - weekly_hours
    """
    assignments: Dict[str, List[dict]] = day_result.get("assignments", {})
    hours_estimate: Dict[str, float] = day_result.get("hours_estimate", {})

    # Regular station assignments (with estimated hours)
    worked_today = set()
    for station_recs in assignments.values():
        for rec in station_recs:
            name = rec["name"]
            worked_today.add(name)

            state["days_worked"][name] += 1
            state["consecutive_days"][name] += 1

            h = float(hours_estimate.get(name, 0.0))
            state["weekly_hours"][name] += h

    # Chef attendance tracked separately
    chefs_today = day_result.get("chefs_present", [])
    for name in chefs_today:
        state["days_worked"][name] += 1
        state["consecutive_days"][name] += 1
        # Current policy: each chef day contributes 10 hours
        state["weekly_hours"][name] += 10.0
        worked_today.add(name)

    # Everyone not marked as worked today is treated as off
    everyone = set(state["days_worked"].keys())
    absent_today = everyone - worked_today
    for name in absent_today:
        state["days_off"][name] += 1
        state["consecutive_days"][name] = 0


# -------- Week Generation --------
def generate_week(
    start_date_str: str,
    num_days: int = 7,
    prev_state: dict | None = None,
    leave_by_date: dict[str, list[str]] | None = None,
    inputs: "EngineInputs" = None,
) -> dict:
    """
    Generate a schedule from start_date for num_days using greedy assignment.
    State is carried forward to preserve continuity across weekly chunks.

    Continuity behavior:
      - If prev_state is provided, consecutive_days is inherited so streak-based
        constraints are not reset at each 7-day boundary.
      - days_worked / days_off / weekly_hours are tracked per generated chunk.
        Chef max-days checks are handled by helper utilities.
    """

    # 1) Load normalized inputs (people, shifts, rules)
    inputs = inputs or build_inputs_from_json()
    people = inputs.people
    names = [p["name"] for p in people]
    rules = inputs.rules
    max_consec_days = rules.get("max_consecutive_days", 4)

    # 2) Initialize week state, optionally inheriting continuity fields
    state = init_week_state(people)

    if prev_state is not None:
        # Carry over consecutive-day counters from previous chunk
        prev_consec = prev_state.get("consecutive_days", {})
        for n in names:
            if n in prev_consec:
                state["consecutive_days"][n] = prev_consec[n]
        # Keep days_worked / weekly_hours local to this generated chunk

    # 3) Weekly continuity is passed explicitly into the daily engine.

    # 4) Build target date list for this chunk
    start_date = dtparser.parse(start_date_str).date()
    days: List[str] = [
        (start_date + timedelta(days=i)).isoformat() for i in range(num_days)
    ]

    # 5) Iterate day by day and assign shifts
    leave_by_date = leave_by_date or {}
    for date_str in days:
        # 5-1) Auto-rest non-chef staff at max consecutive-day limit
        forced_rest = [
            name
            for name, consec in state["consecutive_days"].items()
            if consec >= max_consec_days and name not in CHEF_LIST
        ]

        # 5-2) Merge auto-rest and leave requests into absent list
        absent_today = list(dict.fromkeys((forced_rest or []) + leave_by_date.get(date_str, [])))
        day_plan = gd.greedy_assign_with_inputs(
            date_str,
            absent=absent_today,
            inputs=inputs,
            weekly_context=state,
        )

        day_plan.setdefault("warnings", [])

        if forced_rest:
            day_plan["warnings"].append("AUTO_REST:" + ",".join(forced_rest))

        # 5-3) Select chefs present for the day
        is_holiday = day_plan.get("is_holiday", False)
        chefs_present, chef_warnings = pick_chefs_for_day(
            is_holiday=is_holiday,
            state=state,
            all_chefs=CHEF_LIST,
            max_days_per_week=5,  # Current policy: chef max working days per week
        )

        day_plan["chefs_present"] = chefs_present
        day_plan["warnings"].extend(chef_warnings)

        # 5-4) Store daily plan
        state["week_plan"][date_str] = day_plan

        # 5-5) Update cumulative week state
        update_week_state(state, day_plan)

    return state


# -------- Weekly Summary --------

from typing import Dict


def summarize_week(state: dict) -> Dict[str, dict]:
    """
    Build per-person summary payload for API responses.
    Example:
    {
        "Spencer": {"days": 5, "hours": 45.0},
        "Ishikawa": {"days": 6, "hours": 52.0},
        ...
    }
    """
    days_worked = state["days_worked"]
    weekly_hours = state["weekly_hours"]

    summary: Dict[str, dict] = {}
    for name in days_worked.keys():
        summary[name] = {
            "days": days_worked[name],
            "hours": float(weekly_hours[name]),
        }
    return summary


def print_week_summary(state: dict, start_date_str: str, num_days: int) -> None:
    print(f"\n=== Week summary from {start_date_str} for {num_days} days ===")

    days_worked = state["days_worked"]
    days_off = state["days_off"]
    consec = state["consecutive_days"]
    weekly_hours = state["weekly_hours"]

    names_sorted = sorted(
        weekly_hours.keys(),
        key=lambda n: (-weekly_hours[n], n),
    )

    for name in names_sorted:
        print(
            f"  - {name}: "
            f"worked={days_worked[name]} days, "
            f"off={days_off[name]} days, "
            f"consecutive={consec[name]} days, "
            f"hours={weekly_hours[name]}h"
        )


def save_week_csv(state: dict, out_path="week.csv"):
    rows = []
    for date, plan in state["week_plan"].items():
        for station, assignments in plan["assignments"].items():
            for rec in assignments:
                rows.append(
                    {
                        "date": date,
                        "station": station,
                        "name": rec["name"],
                        "shift": rec["shift"],
                        "shift_hours": plan["hours_estimate"].get(rec["name"], 0),
                        "chef_present": ",".join(plan["chefs_present"]),
                    }
                )

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "date",
                "station",
                "name",
                "shift",
                "shift_hours",
                "chef_present",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


# -------- CLI --------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("start_date", help="Start date in YYYY-MM-DD format, e.g. 2025-11-10")
    ap.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to generate (default: 7)",
    )
    args = ap.parse_args()

    week_state = generate_week(args.start_date, num_days=args.days, prev_state=None)
    save_week_csv(week_state, out_path="week.csv")
    print("Saved week.csv !")

    print(json.dumps(week_state["week_plan"], ensure_ascii=False, indent=2))

    print("\n[WEEK_STATE_SUMMARY]")
    print_week_summary(week_state, args.start_date, args.days)
