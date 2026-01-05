# app/main.py
# ---------------------------
# Sched-MVP FastAPI server
# ---------------------------

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.api_calendar import router as calendar_router
from app import generate_day as gd
from app.api_week import router as week_router
from app.api_llm_patch import router as llm_patch_router


app = FastAPI(
    title="Sched-MVP API",
    description="排班 MVP 的後端 API",
    version="0.2.0",
)

# ✅ CORS：給 Next.js 前端用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ✅ 啟動時：初始化 generate_day 需要的 shifts_map（取代以前的 global punch）
@app.on_event("startup")
def init_globals():
    shifts = gd.load_json("shifts.json")
    shifts_map, _ = gd.build_shift_maps(shifts)
    gd.shifts_map = shifts_map


@app.get("/")
def healthcheck():
    return {"status": "ok"}


# -----------------------------------------
# 單日排班 API（保留原本功能）
# -----------------------------------------
@app.get("/generate/day/{date}")
def generate_day_api(date: str, absent: str = ""):
    """
    例：
    /generate/day/2025-11-03
    /generate/day/2025-11-03?absent=Chung,Masuda
    """

    try:
        absent_list = (
            [x.strip() for x in absent.split(",") if x.strip()]
            if absent else []
        )

        result = gd.greedy_assign(date, absent_list)
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------
# 安裝 router：week / month API
# -----------------------------------------
# ⚠ 不加 prefix，因為 router 裡的路徑已經是 "/api/xxx"
app.include_router(week_router)
app.include_router(calendar_router, prefix="/api")
# -----------------------------------------
# 安裝 LLM patch API（你之前做的）
# 這個 router 裡路徑應該是 "/llm_patch_preview" 之類的
# ➜ 加上 prefix="/api" → /api/llm_patch_preview
# -----------------------------------------
app.include_router(llm_patch_router, prefix="/api")
