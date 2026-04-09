# app/generate_month.py
# --------------------------------------------------------
# Month-level schedule generator that composes weekly chunks.
# Usage:
#   python -m app.generate_month 2025-11
# --------------------------------------------------------

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict

from app.generate_week import generate_week

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MONTH_OUTPUT_DIR = ROOT_DIR / "state"


def _month_range(year_month: str) -> tuple[date, date]:
    year, month = map(int, year_month.split("-"))
    start = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    end = next_month - timedelta(days=1)
    return start, end


def _iter_week_chunks(start: date, end: date):
    cur = start
    while cur <= end:
        remaining = (end - cur).days + 1
        num_days = min(7, remaining)
        yield cur, num_days
        cur = cur + timedelta(days=num_days)


def generate_month(year_month: str) -> Dict[str, Any]:
    month_plan: Dict[str, Any] = {}

    first_day, last_day = _month_range(year_month)

    print(f"\n[GENERATING MONTH (by week)] {year_month}\n")

    prev_state: dict | None = None

    for week_start, num_days in _iter_week_chunks(first_day, last_day):
        start_str = week_start.isoformat()
        print(f"  - Generating week from {start_str} for {num_days} days ...")

        week_state = generate_week(start_str, num_days=num_days, prev_state=prev_state)

        for date_str, plan in week_state["week_plan"].items():
            month_plan[date_str] = plan

        prev_state = week_state

    return month_plan


def summarize_month(month_plan: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    summary: Dict[str, Dict[str, float]] = {}

    for date_str, info in month_plan.items():
        hours_estimate = info.get("hours_estimate", {}) or {}
        for name, hours in hours_estimate.items():
            if name not in summary:
                summary[name] = {"days": 0, "hours": 0.0}
            if hours > 0:
                summary[name]["days"] += 1
                summary[name]["hours"] += float(hours)

    return summary


def save_month_json(
    year_month: str,
    month_plan: Dict[str, Any],
    summary: Dict[str, Dict[str, float]],
    out_path: str | Path | None = None,
) -> Path:
    out_obj = {
        "month": year_month,
        "days": month_plan,
        "summary": summary,
    }

    out_path = (
        Path(out_path)
        if out_path is not None
        else DEFAULT_MONTH_OUTPUT_DIR / f"month_{year_month}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(out_obj, handle, ensure_ascii=False, indent=2)

    print(f"\nSaved {out_path} !\n")
    return out_path


def print_month_summary(year_month: str, summary: Dict[str, Dict[str, float]]) -> None:
    print("[MONTH_STATE_SUMMARY]")
    print(f"\n=== Month summary for {year_month} ===")
    for name, stats in sorted(
        summary.items(), key=lambda item: item[1]["hours"], reverse=True
    ):
        days = stats["days"]
        hours = stats["hours"]
        print(f"  - {name}: worked={days} days, hours={hours:.1f}h")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("year_month", help="Month in YYYY-MM format, e.g. 2025-11")
    parser.add_argument(
        "--out",
        help="Output JSON path (default: state/month_YYYY-MM.json)",
    )
    args = parser.parse_args()

    year_month = args.year_month

    month_plan = generate_month(year_month)
    summary = summarize_month(month_plan)
    save_month_json(year_month, month_plan, summary, out_path=args.out)
    print_month_summary(year_month, summary)


if __name__ == "__main__":
    main()
