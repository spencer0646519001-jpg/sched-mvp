"""
FROZEN LEGACY FASTAPI ROUTES
- Rollback-only runtime surface.
- Canonical runtime is Django.
- Do not add new features; only emergency patching is allowed.
"""

# app/api_week.py
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from datetime import date, timedelta
from dateutil import parser as dtparser
from io import StringIO
import csv
import io

# 從一週排班引擎匯入
from app.generate_week import generate_week, summarize_week

# ✅ 改成 Router，而不是 FastAPI()
router = APIRouter()


@router.get("/api/week")
def get_week(
    start_date: str = Query("2025-11-10", description="週開始日期 YYYY-MM-DD"),
    days: int = Query(7, ge=1, le=31, description="要產生幾天的排班（預設 7）"),
):
    """
    回傳一週（或多天）排班結果。
    目前直接呼叫 generate_week()，把 state['week_plan'] 當作 JSON 回傳。
    """
    week_state = generate_week(
        start_date_str=start_date,
        num_days=days,
        prev_state=None,  # 之後要接跨週狀態時可以再打開
    )
    return week_state["week_plan"]


@router.get("/api/week/summary")
def get_week_summary(
    start_date: str = Query("2025-11-10", description="週開始日期 YYYY-MM-DD"),
    days: int = Query(7, ge=1, le=31, description="要產生幾天的排班（預設 7）"),
):
    """
    給前端或之後報表用的「一週 summary」：
    {
        "Spencer": {"days": 5, "hours": 45.0},
        ...
    }
    """
    week_state = generate_week(
        start_date_str=start_date,
        num_days=days,
        prev_state=None,
    )
    return summarize_week(week_state)


@router.get("/api/week_csv")
def get_week_csv(
    start_date: str = Query(..., description="週開始日期 YYYY-MM-DD，例如 2025-11-15"),
    days: int = Query(7, description="要產生的天數（預設 7 天）"),
):
    """
    下載一週班表的 CSV。
    每一列 = 一個站位上的一個人班別。
    之後月班表會再做人成 x 日期矩陣。
    """
    week_state = generate_week(start_date, num_days=days, prev_state=None)
    week_plan = week_state["week_plan"]  # date_str -> day_plan

    buf = StringIO()
    writer = csv.writer(buf)

    writer.writerow(["date", "station", "name", "shift", "chef_present"])

    for date_str, plan in sorted(week_plan.items()):
        chefs = ",".join(plan.get("chefs_present", []))
        assignments = plan.get("assignments", {})

        for station, recs in assignments.items():
            for rec in recs:
                writer.writerow(
                    [
                        date_str,
                        station,
                        rec["name"],
                        rec["shift"],
                        chefs,
                    ]
                )

    buf.seek(0)

    filename = f"week_{start_date}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers=headers,
    )


# ------------------------------------------------------------
# 整月排班工具：用 generate_week 分段跑完整個月
# ------------------------------------------------------------


def _generate_month_state(start_date_str: str) -> dict:
    """
    給「這個月中的任一天」，產生整個月的排班與工時統計。
    """
    base_date = dtparser.parse(start_date_str).date()
    month_start = base_date.replace(day=1)

    # 算出這個月最後一天
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    month_end = next_month - timedelta(days=1)

    cur = month_start
    prev_state: dict | None = None

    month_plan: dict = {}  # date_str -> day_plan
    summary_total: dict = {}  # name -> {"days": int, "hours": float}

    while cur <= month_end:
        days_left = (month_end - cur).days + 1
        chunk_days = min(7, days_left)

        week_state = generate_week(
            cur.isoformat(),
            num_days=chunk_days,
            prev_state=prev_state,
        )

        month_plan.update(week_state["week_plan"])

        week_summary = summarize_week(week_state)
        for name, stats in week_summary.items():
            total = summary_total.setdefault(name, {"days": 0, "hours": 0.0})
            total["days"] += int(stats["days"])
            total["hours"] += float(stats["hours"])

        prev_state = week_state
        cur += timedelta(days=chunk_days)

    overtime: dict = {}
    for name, stats in summary_total.items():
        hrs = stats["hours"]
        status = None
        if hrs > 75:
            status = "HARD_LIMIT"
        elif hrs > 45:
            status = "WARNING"

        if status:
            overtime[name] = {
                "status": status,
                "hours": hrs,
            }

    return {
        "month_start": month_start.isoformat(),
        "month_end": month_end.isoformat(),
        "plan": month_plan,
        "summary": summary_total,
        "overtime": overtime,
    }


@router.get("/api/month")
def get_month(
    start_date: str = Query(
        ...,
        description="這個月中的任一天（例如 2025-11-10）",
    )
):
    """
    整月排班 API：
    - 會自動對齊到該月 1 號
    - 回傳整個月的排班 + 每人本月工時 + 加班警示
    """
    month_state = _generate_month_state(start_date)
    return month_state


@router.get("/api/month_csv")
def api_month_csv(start_date: str = Query(..., description="任一個在目標月份內的日期")):
    """
    下載「整個月」的排班 CSV。
    一列 = 一個人某天在某站的班別。
    """
    state = _generate_month_state(start_date)
    month_start = state["month_start"]
    plan = state["plan"]  # date_str -> day_plan

    rows: list[dict] = []
    for date_str, day_plan in plan.items():
        chefs = ",".join(day_plan.get("chefs_present", []))
        hours = day_plan.get("hours_estimate", {})

        for station, assignments in day_plan.get("assignments", {}).items():
            for rec in assignments:
                name = rec["name"]
                shift = rec["shift"]
                rows.append(
                    {
                        "date": date_str,
                        "station": station,
                        "name": name,
                        "shift": shift,
                        "shift_hours": hours.get(name, 0.0),
                        "chef_present": chefs,
                    }
                )

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["date", "station", "name", "shift", "shift_hours", "chef_present"],
    )
    writer.writeheader()
    writer.writerows(rows)

    csv_bytes = buf.getvalue().encode("utf-8-sig")
    filename = f"month_{month_start}.csv"

    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
