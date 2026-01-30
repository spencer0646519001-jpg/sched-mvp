# app/langgraph_flow.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END

from django.db.models import QuerySet
from core.models import Tenant, Station, EmployeeStationSkill

# 你的引擎（不改它）
from app.generate_day import greedy_assign


class GraphState(TypedDict, total=False):
    # input
    tenant_name: str
    date_str: str
    absent: List[str]

    # context
    stations: List[str]                 # db-ordered station codes
    station_need: Dict[str, int]        # normalized keys
    skills_by_station: Dict[str, List[str]]

    # engine out
    greedy_result: Dict[str, Any]

    # trace + explanation
    decision_trace: List[Dict[str, Any]]
    explanations: Dict[str, str]


def _load_station_need_normalized(rules: Dict[str, Any]) -> Dict[str, int]:
    raw = (rules.get("stations") or {})
    # 你現在已經在 greedy 裡做過類似 normalize；這裡再保險一次
    return {str(k).strip().lower(): int(v) for k, v in raw.items()}


def node_load_context(state: GraphState) -> GraphState:
    tenant_name = state["tenant_name"]

    # rules/calendar 仍然由 greedy_assign 內部讀 json
    # 這裡只需要 DB 的 station order + station skills（用來解釋）
    tenant = Tenant.objects.get(name=tenant_name)

    db_station_codes = list(
        Station.objects
        .filter(tenant=tenant, is_active=True)
        .order_by("sort_order", "code")
        .values_list("code", flat=True)
    )

    # skills_by_station: station_code -> [employee_name...]
    skills_by_station: Dict[str, List[str]] = {}
    for code in db_station_codes:
        st = Station.objects.get(tenant=tenant, code=code)

        qs: QuerySet[EmployeeStationSkill] = (
            EmployeeStationSkill.objects
            .filter(
                tenant=tenant,
                station=st,
                employee__is_active=True,
                employee__is_assignable=True,
            )
            .order_by("-level", "employee__name")
        )
        skills_by_station[code] = [s.employee.name for s in qs]

    return {
        "stations": db_station_codes,
        "skills_by_station": skills_by_station,
    }


def node_run_greedy(state: GraphState) -> GraphState:
    date_str = state["date_str"]
    absent = state.get("absent") or []

    out = greedy_assign(date_str, absent=absent)
    return {"greedy_result": out}

def node_build_trace(state: GraphState) -> GraphState:
    out = state["greedy_result"]
    assignments: Dict[str, List[dict]] = out.get("assignments") or {}
    stations_db = state.get("stations") or []
    skills_by_station = state.get("skills_by_station") or {}
    absent = state.get("absent") or []

    ordered = [s for s in stations_db if s in assignments] + [
        s for s in assignments.keys() if s not in set(stations_db)
    ]

    trace: List[Dict[str, Any]] = []

    for st in ordered:
        assignees = assignments.get(st) or []
        skilled = skills_by_station.get(st) or []

        picked_names = [a.get("name") for a in assignees if a.get("name")]

        notes_flat: List[str] = []
        for a in assignees:
            notes = a.get("notes")
            if isinstance(notes, list):
                notes_flat.extend([str(x) for x in notes])
            elif isinstance(notes, str) and notes:
                notes_flat.append(notes)

        has_fallback = any(n == "fallback_no_skill" for n in notes_flat)

        skilled_set = set(skilled)
        picked_has_skill = [n for n in picked_names if n in skilled_set]

        # ✅ skill 名單中「沒被選到」的人（前 N）
        missing = [n for n in skilled if n not in set(picked_names)]
        missing_top = missing[:8]
        absent_set = set(absent)
        missing_but_absent = [n for n in missing if n in absent_set][:8]
        missing_and_not_absent = [n for n in missing if n not in absent_set][:8]

        trace.append({
            "station": st,
            "picked": picked_names,
            "notes": notes_flat,

            "absent": absent,
            "missing_but_absent_top": missing_but_absent,
            "missing_and_not_absent_top": missing_and_not_absent,

            "skilled_total": len(skilled),
            "skilled_pool_top": skilled[:8],
            "skilled_missing_top": missing_top,

            "has_fallback": has_fallback,
            "picked_has_skill": picked_has_skill,
        })

    return {"decision_trace": trace}



def node_explain(state: GraphState) -> GraphState:
    trace = state.get("decision_trace") or []
    explanations: Dict[str, str] = {}

    for item in trace:
        st = item.get("station")
        picked = item.get("picked") or []
        skilled_top = item.get("skilled_pool_top") or []
        picked_has_skill = item.get("picked_has_skill") or []
        has_fallback = bool(item.get("has_fallback"))
        notes = item.get("notes") or []
        skilled_total = item.get("skilled_total")
        missing = item.get("skilled_missing_top") or []
        missing_but_absent = item.get("missing_but_absent_top") or []
        missing_and_not_absent = item.get("missing_and_not_absent_top") or []

        if not st:
            continue

        if not picked:
            explanations[st] = "此站位沒有被分配到人。"
            continue

        lines = []
        lines.append(f"分配到：{', '.join(picked)}")

        if skilled_top:
            lines.append(f"此站位有技能名單（DB Top）：{', '.join(skilled_top)}{'…' if len(skilled_top)==8 else ''}")
        else:
            lines.append("此站位 DB 查不到技能名單（可能未建 skill 或被停用）。")

        if picked_has_skill:
            lines.append(f"其中具備此站技能：{', '.join(picked_has_skill)}")
        else:
            lines.append("分配到的人在 DB skill 名單中找不到（= 沒技能）。")

        if has_fallback:
            lines.append("⚠️ 出現 fallback_no_skill：代表當輪到此站位時，候選池裡沒有『有技能且未被用掉』的人，只好用沒技能的人頂上。")
            lines.append("最常見原因：站位排序 + used_today 先把技能者用在其他站位，導致此站位輪到時已無技能者可用。")
        # ✅ B1-2 evidence
        if skilled_total is not None:
            lines.append(f"技能名單總數：{skilled_total}")

        if missing:
            lines.append(f"技能名單中未被選到（Top）：{', '.join(missing)}")

        if missing_but_absent:
            lines.append(f"其中缺席（absent）者：{', '.join(missing_but_absent)}")

        if missing_and_not_absent:
            lines.append(
                "其中未缺席但未被選到（可能被其他站位先用掉 / 不可排 / 資料不一致）："
        + ", ".join(missing_and_not_absent)
    )
    
        # 若你想保留 notes 給 debug（可選）
        if notes:
            lines.append(f"notes: {', '.join([str(x) for x in notes])}")

        explanations[st] = "\n".join(lines)

    return {"explanations": explanations}


def build_graph():
    g = StateGraph(GraphState)
    g.add_node("load_context", node_load_context)
    g.add_node("run_greedy", node_run_greedy)

    # ✅ 新增這行
    g.add_node("build_trace", node_build_trace)

    g.add_node("explain", node_explain)

    g.set_entry_point("load_context")
    g.add_edge("load_context", "run_greedy")

    # ✅ 改這兩條邊：run_greedy -> build_trace -> explain
    g.add_edge("run_greedy", "build_trace")
    g.add_edge("build_trace", "explain")

    g.add_edge("explain", END)

    return g.compile()



def run_daily_schedule_graph(*, tenant_name: str, date_str: str, absent: Optional[List[str]] = None) -> Dict[str, Any]:
    graph = build_graph()
    state_in: GraphState = {
        "tenant_name": tenant_name,
        "date_str": date_str,
        "absent": absent or [],
    }
    state_out = graph.invoke(state_in)

    # 給 API 用：把 greedy out + explanations 一起回傳
    out_engine = state_out["greedy_result"]
    decision_trace = state_out.get("decision_trace", [])
    explanations = state_out.get("explanations", {})

    return {
            "ok": True,
            "data": {
                "out": out_engine,
                "decision_trace": decision_trace,
                "explanations": explanations,
            },
            # backward compatibility（先留著，避免其他地方還在用）
            "compat": {
                "out_engine": out_engine,
                "decision_trace": decision_trace,
                "explanations": explanations,
            }
        }


