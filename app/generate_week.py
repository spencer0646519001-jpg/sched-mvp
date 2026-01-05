# app/generate_week.py
# -----------------------------------------------
# 一週排班：呼叫現有的 greedy_assign() 跑連續多天
# A+ 版本：支援「從上一週承接連續上班天數」
# -----------------------------------------------

import json
import argparse
from datetime import timedelta
from dateutil import parser as dtparser
from typing import Dict, List

# 從單日排班引擎匯入：沿用你現在穩定的 generate_day 邏輯
from . import generate_day as gd
from app.week_utils import pick_chefs_for_day, CHEF_LIST

import csv
from pathlib import Path

def load_rules():
    rules_file = Path(__file__).parent.parent / "data" / "rules.json"
    if not rules_file.exists():
        return {}
    with open(rules_file, encoding="utf-8") as f:
        return json.load(f)


# -------- 一週狀態初始化 --------
def init_week_state(people: List[dict]) -> dict:
    """
    週狀態（state）包含：
      - days_worked: 每個人本「週」已上班天數
      - days_off: 每個人本「週」已休假天數
      - consecutive_days: 連續上班天數（A+：支援跨週延續）
      - weekly_hours: 本週累積工時
      - shift_count: 班別使用次數（目前還沒用到，但保留）
      - week_plan: 每天的排班結果（date_str -> plan）
    """
    names = [p["name"] for p in people]

    return {
        "days_worked": {n: 0 for n in names},
        "days_off": {n: 0 for n in names},
        "consecutive_days": {n: 0 for n in names},
        "weekly_hours": {n: 0.0 for n in names},

        "shift_count": {
            n: {"A": 0, "D": 0, "1": 0, "2": 0, "3": 0, "4": 0}
            for n in names
        },

        "week_plan": {},  # date_str -> plan
    }


# -------- 根據單日結果更新一週狀態 --------
def update_week_state(state: dict, day_result: dict) -> None:
    """
    根據某一天的排班結果，更新：
      - days_worked / days_off
      - consecutive_days
      - weekly_hours
    """
    assignments: Dict[str, List[dict]] = day_result.get("assignments", {})
    hours_estimate: Dict[str, float] = day_result.get("hours_estimate", {})

    # 今天有出勤的人（員工）
    worked_today = set()
    for station_recs in assignments.values():
        for rec in station_recs:
            name = rec["name"]
            worked_today.add(name)

            state["days_worked"][name] += 1
            state["consecutive_days"][name] += 1

            h = float(hours_estimate.get(name, 0.0))
            state["weekly_hours"][name] += h

    # 今天有出勤的主廚
    chefs_today = day_result.get("chefs_present", [])
    for name in chefs_today:
        state["days_worked"][name] += 1
        state["consecutive_days"][name] += 1
        # 主廚工時先固定 10 小時（之後若要細修再說）
        state["weekly_hours"][name] += 10.0
        worked_today.add(name)

    # 沒有出勤的人：視為休假一天，連續上班歸零
    everyone = set(state["days_worked"].keys())
    absent_today = everyone - worked_today
    for name in absent_today:
        state["days_off"][name] += 1
        state["consecutive_days"][name] = 0


# -------- 一週排班主流程（A+：可以接上一週的 state） --------
def generate_week(
    start_date_str: str,
    num_days: int = 7,
    prev_state: dict | None = None,
) -> dict:
    """
    從 start_date 起算 num_days 天，逐日呼叫 greedy_assign 產生排班，
    同時維護一週的統計狀態。

    A+ 重點：
      - 若有 prev_state，會「承接前一週的 consecutive_days」，
        讓跨週的連續上班天數不會被歸零，避免連上 7 天。
      - days_worked / days_off / weekly_hours 在每一週內還是重新計算，
        保持原本「一週為單位」的邏輯（例如主廚 max_days_per_week）。
    """

    # 1) 載入人員資料（沿用 workers.json）
    people = gd.load_json("workers.json")["people"]
    names = [p["name"] for p in people]
    rules = load_rules()
    max_consec_days = rules.get("max_consecutive_days", 4)

    # 2) 初始化一週狀態，若有上一週則承接「連續上班天數」
    state = init_week_state(people)

    if prev_state is not None:
        # 承接跨週的 consecutive_days
        prev_consec = prev_state.get("consecutive_days", {})
        for n in names:
            if n in prev_consec:
                state["consecutive_days"][n] = prev_consec[n]
        # 其他例如 days_worked / weekly_hours 維持「本週重新起算」

    # 3) 幫 generate_day 準備好全域 shifts_map & week_state
    globals_shifts = gd.load_json("shifts.json")
    shifts_map, _ = gd.build_shift_maps(globals_shifts)
    gd.shifts_map = shifts_map
    gd.week_state = state  # greedy_assign 裡的 weekly_penalty 用得到

    # 4) 建立日期清單：連續 num_days 天
    start_date = dtparser.parse(start_date_str).date()
    days: List[str] = [
        (start_date + timedelta(days=i)).isoformat()
        for i in range(num_days)
    ]

    # 5) 主迴圈：逐日呼叫 greedy_assign
    for date_str in days:
        # 5-1) 員工強制休息（不包含主廚）
        forced_rest = [
        name
        for name, consec in state["consecutive_days"].items()
        if consec >= max_consec_days and name not in CHEF_LIST
]


        # 5-2) 先讓 greedy_assign 根據 absent 生成人員與站位（不含主廚）
        day_plan = gd.greedy_assign(date_str, absent=forced_rest)

        day_plan.setdefault("warnings", [])

        if forced_rest:
            day_plan["warnings"].append("AUTO_REST:" + ",".join(forced_rest))

        # 5-3) 根據今天是不是假日，決定主廚 present
        is_holiday = day_plan.get("is_holiday", False)
        chefs_present, chef_warnings = pick_chefs_for_day(
            is_holiday=is_holiday,
            state=state,
            all_chefs=CHEF_LIST,
            max_days_per_week=5,   # 一週最多 5 天（仍以「這週」為單位）
        )

        day_plan["chefs_present"] = chefs_present
        day_plan["warnings"].extend(chef_warnings)

        # 5-4) 存進週計畫
        state["week_plan"][date_str] = day_plan

        # 5-5) 更新週統計
        update_week_state(state, day_plan)

    return state


# -------- 簡單週總結（方便人眼檢查） --------

from typing import Dict

def summarize_week(state: dict) -> Dict[str, dict]:
    """
    給 API 用的「一週 summary」：
    回傳格式：
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
                rows.append({
                    "date": date,
                    "station": station,
                    "name": rec["name"],
                    "shift": rec["shift"],
                    "shift_hours": plan["hours_estimate"].get(rec["name"], 0),
                    "chef_present": ",".join(plan["chefs_present"])
                })

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "date", "station", "name", "shift", "shift_hours", "chef_present"
        ])
        writer.writeheader()
        writer.writerows(rows)


# -------- CLI 入口 --------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("start_date", help="週開始日期 YYYY-MM-DD，例如 2025-11-10")
    ap.add_argument(
        "--days",
        type=int,
        default=7,
        help="要產生的天數（預設 7 天，一週）",
    )
    args = ap.parse_args()

    week_state = generate_week(args.start_date, num_days=args.days, prev_state=None)
    save_week_csv(week_state, out_path="week.csv")
    print("Saved week.csv !")

    print(json.dumps(week_state["week_plan"], ensure_ascii=False, indent=2))

    print("\n[WEEK_STATE_SUMMARY]")
    print_week_summary(week_state, args.start_date, args.days)
