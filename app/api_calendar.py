# app/api_calendar.py
from fastapi import APIRouter
from app.month_service import build_month
from fastapi.responses import Response
import csv
import io
from app.domain.normalize import canonical_station, canonical_shift

router = APIRouter()

@router.get("/calendar/month")
def api_calendar_month(start_date: str = ""):
    """
    GET /api/calendar/month?start_date=2025-11-01
    回傳整月每天 assignments
    """
    return build_month(start_date)

@router.get("/calendar/month_csv")
def api_calendar_month_csv(start_date: str = ""):
    """
    GET /api/calendar/month_csv?start_date=2025-11-01
    下載整月 rows 的 CSV（date, station, name, shift）
    """
    data = build_month(start_date)
    if not data.get("success"):
        # 先用 400，因為 CSV 下載在參數錯誤時不建議回空檔
        return Response(
            content=",".join(data.get("errors", ["UNKNOWN_ERROR"])),
            media_type="text/plain",
            status_code=400,
        )

    # 如果你還沒加 rows/stations（剛改完應該有），這裡做 fallback
    rows = data.get("rows")
    if rows is None:
        # 建議你一定要先做 B2-1，這段只是保險
        rows = []
        for d in data.get("days", []):
            for station, entries in (d.get("assignments", {}) or {}).items():
                for e in entries or []:
                    rows.append(
                        {
                            "date": d.get("date"),
                            "station": station,
                            "name": e.get("name", ""),
                            "shift": e.get("shift", ""),
                        }
                    )


    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["date", "station", "name", "shift"])
    w.writeheader()
    w.writerows(rows)

    filename = f"month_{start_date}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
