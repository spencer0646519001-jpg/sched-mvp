# app/generate_month.py
# --------------------------------------------------------
# 產生整個月的班表（A+ 版本）
# 用法：
#   python -m app.generate_month 2025-11
# --------------------------------------------------------

import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Dict, Any

from app.generate_week import generate_week  # ✅ 以「週」為單位排，再拼成一個月

# 專案根目錄，用來存 month_2025-11.json
ROOT_DIR = Path(__file__).resolve().parents[1]


def _month_range(year_month: str) -> tuple[date, date]:
    """
    給 'YYYY-MM'，回傳這個月的 (第一天, 最後一天)。
    """
    year, month = map(int, year_month.split("-"))
    start = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    end = next_month - timedelta(days=1)
    return start, end


def _iter_week_chunks(start: date, end: date):
    """
    把 [start, end] 這段日期切成數個 week chunk：
    每個 chunk 是 (週起始日, 這週要排幾天)。
    不強求一定從星期一開始，以月份第一天為切割起點即可。
    """
    cur = start
    while cur <= end:
        remaining = (end - cur).days + 1
        num_days = min(7, remaining)
        yield cur, num_days
        cur = cur + timedelta(days=num_days)


def generate_month(year_month: str) -> Dict[str, Any]:
    """
    以「週」為單位，多次呼叫 generate_week，並且跨週承接 state，
    讓連續上班天數不會因為進入新的一週就歸零。
    """
    month_plan: Dict[str, Any] = {}

    first_day, last_day = _month_range(year_month)

    print(f"\n[GENERATING MONTH (by week)] {year_month}\n")

    prev_state: dict | None = None

    for week_start, num_days in _iter_week_chunks(first_day, last_day):
        start_str = week_start.isoformat()
        print(f"  - Generating week from {start_str} for {num_days} days ...")

        week_state = generate_week(start_str, num_days=num_days, prev_state=prev_state)

        # 合併這一週的結果進 monthly 計畫
        for d, plan in week_state["week_plan"].items():
            month_plan[d] = plan

        # 這一週的 state（包含更新後的 consecutive_days）留給下一週用
        prev_state = week_state

    return month_plan


def summarize_month(month_plan: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """
    統計每個人整個月的「上班天數」與「總工時」。
    依據 daily_result["hours_estimate"] 來累計。
    """
    summary: Dict[str, Dict[str, float]] = {}

    for date_str, info in month_plan.items():
        hours_estimate = info.get("hours_estimate", {}) or {}
        for name, h in hours_estimate.items():
            if name not in summary:
                summary[name] = {"days": 0, "hours": 0.0}
            if h > 0:
                summary[name]["days"] += 1
                summary[name]["hours"] += float(h)

    return summary


def save_month_json(
    year_month: str, month_plan: Dict[str, Any], summary: Dict[str, Dict[str, float]]
) -> Path:
    """
    將整月排班結果 + 總結輸出成 JSON 檔：
      month_2025-11.json
    存在專案根目錄。
    """
    out_obj = {
        "month": year_month,
        "days": month_plan,
        "summary": summary,
    }

    out_path = ROOT_DIR / f"month_{year_month}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_obj, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {out_path} !\n")
    return out_path


def print_month_summary(year_month: str, summary: Dict[str, Dict[str, float]]) -> None:
    """
    在 Terminal 印出簡單的整月總結（類似 WEEK_STATE_SUMMARY 風格）。
    """
    print("[MONTH_STATE_SUMMARY]")
    print(f"\n=== Month summary for {year_month} ===")
    for name, stats in sorted(
        summary.items(), key=lambda kv: kv[1]["hours"], reverse=True
    ):
        days = stats["days"]
        hours = stats["hours"]
        print(f"  - {name}: worked={days} days, hours={hours:.1f}h")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("year_month", help="例如：2025-11")
    args = parser.parse_args()

    year_month = args.year_month

    month_plan = generate_month(year_month)
    summary = summarize_month(month_plan)
    save_month_json(year_month, month_plan, summary)
    print_month_summary(year_month, summary)


if __name__ == "__main__":
    main()
