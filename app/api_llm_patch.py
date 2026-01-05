# app/api_llm_patch.py
from fastapi import APIRouter
from fastapi import HTTPException
from pydantic import BaseModel
from app.plan_service import create_plan, patch_preview, patch_apply, get_plan, list_all_plans, delete_plan

router = APIRouter()

class PlanRequest(BaseModel):
    date: str = "2025-11-10"

class PatchRequest(BaseModel):
    plan_id: str
    text: str

@router.post("/plan/create")
def api_plan_create(body: PlanRequest):
    return create_plan(body.date)

@router.post("/plan/patch_preview")
def api_plan_patch_preview(body: PatchRequest):
    return patch_preview(body.plan_id, body.text)

@router.post("/plan/patch_apply")
def api_plan_patch_apply(body: PatchRequest):
    return patch_apply(body.plan_id, body.text)

@router.get("/plan/get")
def api_plan_get(plan_id: str):
    """
    用 plan_id 取得目前的班表內容
    GET /api/plan/get?plan_id=xxxx
    """

    # ✅ 防呆：沒帶 plan_id
    if not plan_id:
        return {
            "success": False,
            "errors": ["MISSING_PLAN_ID"],
        }

    if not plan_id:
        raise HTTPException(status_code=400, detail="MISSING_PLAN_ID")

    try:
        return get_plan(plan_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="PLAN_NOT_FOUND")



@router.get("/plan/list")
def api_plan_list():
    return list_all_plans()
from app.plan_service import delete_plan

@router.delete("/plan/delete")
def api_plan_delete(plan_id: str):
    if not plan_id:
        raise HTTPException(status_code=400, detail="MISSING_PLAN_ID")

    try:
        return delete_plan(plan_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="PLAN_NOT_FOUND")

