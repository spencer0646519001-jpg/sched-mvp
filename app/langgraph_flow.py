# app/langgraph_flow.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END

# 你的引擎（不改它）
from app.generate_day import EngineInputs, greedy_assign_with_inputs
from app.infra.engine_input_resolver import resolve_engine_inputs_for_tenant


class GraphState(TypedDict, total=False):
    # input
    tenant_name: str
    date_str: str
    absent: List[str]
    language: str

    # context
    engine_inputs: EngineInputs
    stations: List[str]                 # db-ordered station codes
    station_need: Dict[str, int]        # normalized keys
    skills_by_station: Dict[str, List[str]]

    # engine out
    greedy_result: Dict[str, Any]

    # trace + explanation
    decision_trace: List[Dict[str, Any]]
    explanations: Dict[str, str]
    metrics: Dict[str, int]


def _load_station_need_normalized(rules: Dict[str, Any]) -> Dict[str, int]:
    raw = (rules.get("stations") or {})
    # 你現在已經在 greedy 裡做過類似 normalize；這裡再保險一次
    return {str(k).strip().lower(): int(v) for k, v in raw.items()}


def node_load_context(state: GraphState) -> GraphState:
    inputs = resolve_engine_inputs_for_tenant(state["tenant_name"])
    station_need = _load_station_need_normalized(inputs.rules)

    base_order = [str(code).strip().lower() for code in (inputs.station_order or [])]
    stations = [code for code in base_order if code in station_need]
    missing_in_order = [code for code in station_need.keys() if code not in set(stations)]
    stations.extend(missing_in_order)

    # skills_by_station: station_code -> [employee_name...]
    skills_by_station: Dict[str, List[str]] = {code: [] for code in stations}
    for person in inputs.people:
        if not isinstance(person, dict):
            continue
        name = str(person.get("name") or "").strip()
        if not name:
            continue
        for code in person.get("station_skills") or []:
            station_code = str(code).strip().lower()
            if station_code in skills_by_station:
                skills_by_station[station_code].append(name)

    for code, names in skills_by_station.items():
        skills_by_station[code] = sorted(set(names), key=lambda n: n.lower())

    return {
        "engine_inputs": inputs,
        "station_need": station_need,
        "stations": stations,
        "skills_by_station": skills_by_station,
    }


def node_run_greedy(state: GraphState) -> GraphState:
    date_str = state["date_str"]
    absent = state.get("absent") or []
    inputs = state.get("engine_inputs") or resolve_engine_inputs_for_tenant(
        state["tenant_name"]
    )

    out = greedy_assign_with_inputs(date_str, absent=absent, inputs=inputs)
    return {"greedy_result": out}

def _build_station_trace_item(
    st: str,
    assignees: List[Dict[str, Any]],
    skilled: List[str],
    absent: List[str],
) -> Dict[str, Any]:
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

    return {
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
    }

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
        trace.append(_build_station_trace_item(st, assignees, skilled, absent))

    return {"decision_trace": trace}



def _apply_trace_item_metrics(
    metrics: Dict[str, int],
    *,
    picked: List[str],
    picked_has_skill: List[str],
    has_fallback: bool,
    missing_but_absent: List[str],
    missing_and_not_absent: List[str],
) -> None:
    updated = dict(metrics)
    updated["stations_total"] += 1

    if has_fallback:
        updated["fallback_stations"] += 1

    fallback_people = max(0, len(picked) - len(picked_has_skill))
    updated["fallback_people_total"] += fallback_people

    updated["absent_skill_total"] += len(missing_but_absent)
    updated["skill_not_used_total"] += len(missing_and_not_absent)
    return updated


def _normalize_language(language: Optional[str]) -> str:
    lang = str(language or "").strip().lower()
    if lang in {"ja", "en", "zh"}:
        return lang
    return "en"


def _i18n_text(language: str) -> Dict[str, str]:
    if language == "ja":
        return {
            "assigned": "割当:",
            "skilled_pool": "この站位のスキル候補（上位）:",
            "no_skilled_pool": "この站位のスキル候補が見つかりません。",
            "picked_has_skill": "割当のうちスキル一致:",
            "picked_no_skill": "割当者がスキル候補に見つかりません。",
            "fallback_1": "fallback_no_skill が発生: スキル候補不足のため代替配置。",
            "fallback_2": "主因: 先行站位で技能者が先に消費された可能性。",
            "skilled_total": "スキル候補人数:",
            "missing": "スキル候補で未選出（上位）:",
            "missing_absent": "そのうち欠勤:",
            "missing_not_absent": "欠勤以外で未選出:",
            "notes": "備考:",
            "empty_station": "この站位には割当がありません。",
        }
    if language == "zh":
        return {
            "assigned": "分配到:",
            "skilled_pool": "此站位技能名單（前列）:",
            "no_skilled_pool": "此站位找不到技能名單。",
            "picked_has_skill": "分配中具此站技能:",
            "picked_no_skill": "分配到的人不在技能名單中。",
            "fallback_1": "發生 fallback_no_skill：技能候選不足，使用替補分配。",
            "fallback_2": "常見原因：前序站位先用掉技能者。",
            "skilled_total": "技能候選總數:",
            "missing": "技能名單中未被選到（前列）:",
            "missing_absent": "其中缺席:",
            "missing_not_absent": "其中未缺席但未被選到:",
            "notes": "備註:",
            "empty_station": "此站位沒有被分配到人。",
        }
    return {
        "assigned": "Assigned:",
        "skilled_pool": "Skilled pool for this station (top):",
        "no_skilled_pool": "No skilled pool found for this station.",
        "picked_has_skill": "Picked with matching skill:",
        "picked_no_skill": "Picked people are not in the skilled pool.",
        "fallback_1": "fallback_no_skill occurred: skilled candidates were unavailable.",
        "fallback_2": "Common reason: skilled candidates were consumed by earlier stations.",
        "skilled_total": "Skilled pool size:",
        "missing": "Skilled but not picked (top):",
        "missing_absent": "Among them absent:",
        "missing_not_absent": "Not absent but not picked:",
        "notes": "notes:",
        "empty_station": "No one was assigned to this station.",
    }


def _build_explanation_lines(
    *,
    language: str,
    picked: List[str],
    skilled_top: List[str],
    picked_has_skill: List[str],
    has_fallback: bool,
    skilled_total: Optional[int],
    missing: List[str],
    missing_but_absent: List[str],
    missing_and_not_absent: List[str],
    notes: List[Any],
) -> List[str]:
    text = _i18n_text(language)
    lines = []
    lines.append(f"{text['assigned']} {', '.join(picked)}")

    if skilled_top:
        lines.append(
            f"{text['skilled_pool']} {', '.join(skilled_top)}"
            f"{'…' if len(skilled_top) == 8 else ''}"
        )
    else:
        lines.append(text["no_skilled_pool"])

    if picked_has_skill:
        lines.append(f"{text['picked_has_skill']} {', '.join(picked_has_skill)}")
    else:
        lines.append(text["picked_no_skill"])

    if has_fallback:
        lines.append(text["fallback_1"])
        lines.append(text["fallback_2"])

    # ====== B1-2 evidence ======
    if skilled_total is not None:
        lines.append(f"{text['skilled_total']} {skilled_total}")

    if missing:
        lines.append(f"{text['missing']} {', '.join(missing)}")

    if missing_but_absent:
        lines.append(f"{text['missing_absent']} {', '.join(missing_but_absent)}")

    if missing_and_not_absent:
        lines.append(f"{text['missing_not_absent']} {', '.join(missing_and_not_absent)}")

    # debug（可留可刪）
    if notes:
        lines.append(f"{text['notes']} {', '.join([str(x) for x in notes])}")

    return lines


def node_explain(state: GraphState) -> GraphState:
    trace = state.get("decision_trace") or []
    explanations: Dict[str, str] = {}
    language = _normalize_language(state.get("language"))

    metrics = {
        "stations_total": 0,
        "fallback_stations": 0,
        "fallback_people_total": 0,
        "absent_skill_total": 0,
        "skill_not_used_total": 0,
    }

    for item in trace:
        # ====== 先抽資料（非常重要的順序）======
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

        # ====== metrics（B1-2）======
        _apply_trace_item_metrics(
            metrics,
            picked=picked,
            picked_has_skill=picked_has_skill,
            has_fallback=has_fallback,
            missing_but_absent=missing_but_absent,
            missing_and_not_absent=missing_and_not_absent,
        )

        # ====== explain text ======
        if not picked:
            explanations[st] = _i18n_text(language)["empty_station"]
            continue

        lines = _build_explanation_lines(
            language=language,
            picked=picked,
            skilled_top=skilled_top,
            picked_has_skill=picked_has_skill,
            has_fallback=has_fallback,
            skilled_total=skilled_total,
            missing=missing,
            missing_but_absent=missing_but_absent,
            missing_and_not_absent=missing_and_not_absent,
            notes=notes,
        )

        explanations[st] = "\n".join(lines)

    return {
        "explanations": explanations,
        "metrics": metrics,
    }


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



def run_daily_schedule_graph(
    *,
    tenant_name: str,
    date_str: str,
    absent: Optional[List[str]] = None,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    graph = build_graph()
    state_in: GraphState = {
        "tenant_name": tenant_name,
        "date_str": date_str,
        "absent": absent or [],
        "language": _normalize_language(language),
    }
    state_out = graph.invoke(state_in)

    # engine outputs
    out_engine = state_out["greedy_result"]
    decision_trace = state_out.get("decision_trace", [])
    explanations = state_out.get("explanations", {})
    metrics = state_out.get("metrics", {})  # ✅ 就是這一行

    return {
        "ok": True,
        "data": {
            "out": out_engine,
            "decision_trace": decision_trace,
            "explanations": explanations,
            "metrics": metrics,               # ✅ 對外 API
        },
        # backward compatibility
        "compat": {
            "out_engine": out_engine,
            "decision_trace": decision_trace,
            "explanations": explanations,
            "metrics": metrics,               # ✅ 舊接口也能拿
        }
    }
