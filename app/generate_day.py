# sched-mvp/app/generate_day.py
# -----------------------------------------------
# 單日排班（嚴格→寬鬆 fallback）＋臨時請假處理
# 輸入：python -m app.generate_day 2025-11-08 --absent "Chung,Masuda"
# -----------------------------------------------

import json  # 讀寫 JSON
from pathlib import Path  # 路徑處理（跨平台安全）
from datetime import datetime  # 日期處理
from dateutil import parser as dtparser  # 解析字串日期
import argparse  # 解析 CLI 參數
import hashlib
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional  # 型別註解
from app.week_utils import choose_shift_for_person
from app.infra.engine_inputs import build_inputs_from_json
import logging
logger = logging.getLogger(__name__)


# 以檔案自身位置定位 data 目錄：<repo>/sched-mvp/data
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@dataclass(frozen=True)
class EngineInputs:
    shifts_list: List[dict]
    rules: dict
    calendar: dict
    people: List[dict]
    station_order: List[str]


# -------- I/O 基礎 --------
def load_json(name: str):
    """讀取 data/*.json；name 如 'rules.json'。"""
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(obj, out_path: Path):
    """輸出結果到檔案（供除錯用）。"""
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _build_engine_inputs_default(tenant_name: str) -> EngineInputs:
    return build_inputs_from_json()


# -------- 小工具 --------
def is_weekend(dt: datetime) -> bool:
    """週六日為週末：Sat=5, Sun=6。"""
    return dt.weekday() >= 5


def weekday_str(dt: datetime) -> str:
    """回傳 'Mon'..'Sun'，供 fixed_days_off 比對。"""
    return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][dt.weekday()]


def parse_absent_list(s: Optional[str]) -> List[str]:
    """CLI 的 --absent 轉為名字清單。"""
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def _to_datekey(s: str) -> str:
    # 接受 "2025-11-11" 或 "2025/11/11" 或 datetime 皆可
    if isinstance(s, datetime):
        return s.date().isoformat()
    return dtparser.parse(str(s)).date().isoformat()


def wish_off_flags(person: dict, date_obj: datetime) -> tuple[bool, bool]:
    """回傳 (is_hard, is_soft)；自動容忍 '-' 或 '/' 的日期字串。"""
    dkey = _to_datekey(date_obj)
    wish = person.get("wish_off") or {}
    hard = {_to_datekey(x) for x in (wish.get("hard") or [])}
    soft = {_to_datekey(x) for x in (wish.get("soft") or [])}
    return (dkey in hard), (dkey in soft)


# -------- 班別與時數 --------
def build_shift_maps(
    shifts_list: List[dict],
) -> Tuple[Dict[str, dict], Dict[str, float]]:
    """
    shifts_list 來自 shifts.json（為 list）
    回傳：
      - shift_map: 代碼 -> 班別設定
      - paid_hours: 代碼 -> 該班別的 paid_hours
    """
    shift_map = {s["code"]: s for s in shifts_list}
    paid_hours = {s["code"]: float(s.get("paid_hours", 0.0)) for s in shifts_list}
    return shift_map, paid_hours


def _ordered_allowed_shift_codes(
    allowed: set[str],
    shifts_map: Dict[str, dict],
) -> List[str]:
    ordered: List[str] = []
    seen: set[str] = set()

    for raw_code in shifts_map.keys():
        code = str(raw_code).upper()
        if code in allowed and code not in seen:
            ordered.append(code)
            seen.add(code)

    for code in sorted(allowed):
        if code not in seen:
            ordered.append(code)

    return ordered


def _rotate_allowed_shift_codes(
    allowed_list: List[str],
    *,
    date_str: str,
    person_name: str,
) -> List[str]:
    if len(allowed_list) <= 1:
        return list(allowed_list)

    token = f"{date_str}|{person_name}".encode("utf-8")
    digest = hashlib.sha256(token).digest()
    offset = int.from_bytes(digest[:8], "big") % len(allowed_list)
    return allowed_list[offset:] + allowed_list[:offset]


def pick_shift_for(
    person: dict, shifts_map: Dict[str, dict], is_holiday: bool, date_str: str
) -> Optional[str]:
    """
    依照 shift_prefs 從「當天允許的班別」中挑一個。

    規則：
      - 平日：A/B/C/D
      - 假日：A/B/C/D + 1/2/3/4
      - shift_prefs 會自動轉大寫
      - 若偏好都不能用 → fallback 到允許集合中的任一班別
    """
    if is_holiday:
        allowed = {"A", "B", "C", "D", "1", "2", "3", "4"}
    else:
        allowed = {"A", "B", "C", "D"}
    
    # --- per-person hard constraint: allowed_shifts ---
    
    person_allowed_raw = person.get("allowed_shifts") or []
    person_allowed = {str(s).upper() for s in person_allowed_raw if str(s).strip()}

    if person_allowed:
        intersect = allowed & person_allowed
        # 保守退回：交集為空就不要擋，改用全域 allowed
        if intersect:
            allowed = intersect

    prefs = person.get("shift_prefs") or []
    prefs = [str(p).upper() for p in prefs]  # 小寫轉大寫

    # 1) 先依照偏好找第一個合法的
    for code in prefs:
        if code in allowed:
            return code

    # 2) 沒有偏好落在 allowed → fallback 隨機選
    if allowed:
        allowed_list = _ordered_allowed_shift_codes(allowed, shifts_map)
        rotated_allowed_list = _rotate_allowed_shift_codes(
            allowed_list,
            date_str=date_str,
            person_name=str(person.get("name") or ""),
        )
        return rotated_allowed_list[0]

    return None


def enforce_morning_requirements(assignments: dict, rules: dict):
    """
    根據 rules.json:
    - morning_shifts = 早班集合
    - stations_require_morning = {"GATEAU":1, "petit_four":1}

    如果某個 station 的早班人數不足，
    從該 station 的 assignment 中挑一個人換成早班。
    """

    morning_shifts = [
        str(code).upper()
        for code in (rules.get("morning_shifts", []) or [])
        if str(code).strip()
    ]
    morning_shift_set = set(morning_shifts)
    station_require = rules.get("stations_require_morning", {})

    for station, required_count in station_require.items():
        assigned_list = assignments.get(station, [])
        if not assigned_list:
            continue

        # 計算目前有多少早班
        current_morning = [
            p for p in assigned_list if str(p.get("shift", "")).upper() in morning_shift_set
        ]
        missing = required_count - len(current_morning)

        if missing <= 0:
            continue  # 早班已足夠

        # 不足 → 找出 非早班 的人
        non_morning = [
            p for p in assigned_list if str(p.get("shift", "")).upper() not in morning_shift_set
        ]
        if not non_morning or not morning_shifts:
            continue

        # 從 non-morning 裡挑第一個（未來可改成最少 penalty）
        target = non_morning[0]
        target["shift"] = morning_shifts[0]  # 指派第一個早班

    return assignments


# -------- 資格檢查（硬約束）--------
def eligible_today(
    person: dict,
    date_obj: datetime,
    shift_code: Optional[str],
    rules: dict,
    shifts_map: dict,
) -> bool:
    """當日硬過濾：班別合法、非固定與臨時休、hard 想休直接擋。"""
    if person.get("role") == "chef":
        # 主廚當天是否出勤：仍可出勤（不排班別），hard 想休就擋
        is_hard, _ = wish_off_flags(person, date_obj)
        if rules.get("enforce_hard_off", True) and is_hard:
            return False
        return True

    fixed_off = set(person.get("fixed_days_off") or [])
    if weekday_str(date_obj) in fixed_off:
        return False

    adhoc = {_to_datekey(x) for x in (person.get("ad_hoc_unavailable") or [])}
    if _to_datekey(date_obj) in adhoc:
        return False

    if shift_code and shift_code not in shifts_map:
        return False

    # 員工 hard 想休直接擋
    is_hard, _ = wish_off_flags(person, date_obj)
    if rules.get("enforce_hard_off", True) and is_hard:
        return False

    return True


# -------- 評分（軟約束）--------
def assignment_cost(
    person: dict, station: str, shift_code: str, rules: dict, date_obj: datetime
) -> tuple[float, dict]:
    """
    回傳 (cost, extra_notes)
    成本越小越好：
      +0.0  具備 station_skills
      +fallback_penalty  不具備 station_skills（fallback_no_skill）
      +0.2  shift_prefs 不包含該班別
      +soft_off_penalty 今天被標記為 soft 想休
    """
    notes = {}
    cost = 0.0

    skills = set(person.get("station_skills") or [])
    if station not in skills:
        cost += float(rules.get("fallback_penalty", 1.0))
        notes["fallback_no_skill"] = True

    prefs_raw = person.get("shift_prefs") or []
    prefs = {str(p).upper() for p in prefs_raw}

    shift_code_upper = str(shift_code).upper()

    # 這裡直接寫死 0.8 也可以
    if prefs and shift_code_upper not in prefs:
        cost += 0.8

    _, is_soft = wish_off_flags(person, date_obj)
    if is_soft:
        cost += float(rules.get("soft_off_penalty", 2.5))
        notes["soft_off_override"] = True
    # Core staff priority (core people are preferred)
    if person.get("core", False):
        cost -= float(rules.get("core_priority_bonus", 1.0))

    return cost, notes


# -------- 核心：貪婪排班（帶 fallback 與不留空）--------
def greedy_assign_with_inputs(
    date_str: str,
    absent: List[str],
    inputs: EngineInputs,
    weekly_context: Optional[dict] = None,
) -> dict:
    # 解析日期；去掉 timezone 以免比較問題
    day = dtparser.parse(date_str).replace(tzinfo=None)

    # 載入所有設定
    shifts_map, paid_hours_map = build_shift_maps(inputs.shifts_list)
    rules = inputs.rules
    calendar = inputs.calendar
    people = inputs.people
    require_one_chef = bool(rules.get("require_one_chef", True))
    allow_fallback = bool(rules.get("allow_fallback_when_short", True))

    # 週末 or holiday
    is_holi = is_weekend(day) or (date_str in set(calendar.get("holidays", [])))
    min_staff = int(
        rules["min_staff_weekend"] if is_holi else rules["min_staff_weekday"]
    )
    max_staff = int(rules.get("max_staff_per_day", 9))

    # 當日站位需求（仍從 rules.json）
    station_need_raw: Dict[str, int] = rules.get("stations", {}) or {}
    station_need: Dict[str, int] = {
        str(k).strip().lower(): int(v) for k, v in station_need_raw.items()
    }

    # 站位順序（由輸入決定）
    db_station_codes = inputs.station_order or list(station_need.keys())

    # 最終 stations：以 station_order 為主，但只保留 rules 有定義需求的站位
    stations = [code for code in db_station_codes if code in station_need]

    # 防呆：rules 有定義，但 station_order 沒 → 補到最後
    missing_in_db = [
        code for code in station_need.keys() if code not in set(db_station_codes)
    ]
    stations.extend(missing_in_db)

    warnings: List[str] = []

    logger.debug("stations order = %s", stations)



    # 主廚出勤
    chefs_present: List[str] = []
    for p in people:
        if p.get("role") == "chef":
            if p["name"] not in absent and eligible_today(
                p, day, None, rules, shifts_map
            ):
                chefs_present.append(p["name"])

    # 員工出勤
    employees = [
        p
        for p in people
        if p.get("role") != "chef"
        and p["name"] not in absent
        and eligible_today(p, day, None, rules, shifts_map)
    ]
    logger.debug("station_need keys = %s", list(station_need.keys()))
    logger.debug("db_station_codes = %s", db_station_codes)

    # 初始化
    assignments: Dict[str, List[dict]] = {s: [] for s in stations}
    used_today = set()
    hours_estimate: Dict[str, float] = {}

    # 計算總人數
    def headcount_total() -> int:
        base = sum(len(v) for v in assignments.values())
        if rules.get("count_chefs_in_headcount", True):
            base += len(chefs_present)
        return base

    # 是否還有缺口
    def need_more() -> bool:
        if require_one_chef and len(chefs_present) == 0:
            return True
        if headcount_total() < min_staff:
            return True
        for s in stations:
            if len(assignments[s]) < station_need[s]:
                return True
        return False

    # 主迴圈
    while need_more() and headcount_total() < max_staff:
        deficit_sorted = sorted(
            stations, key=lambda s: (len(assignments[s]) - station_need[s])
        )
        placed_any = False

        for s in deficit_sorted:
            # 這個站位已補滿且整體已達最低人數 → 可以跳過
            if (
                len(assignments[s]) >= station_need[s]
                and headcount_total() >= min_staff
            ):
                continue

            strict_pool, relaxed_pool = [], []

            # 掃過今天可上班的每個員工，計算配這個站位的 cost
            for p in employees:
                if p["name"] in used_today:
                    continue

                shift_code = pick_shift_for(p, shifts_map, is_holi, date_str)
                if not shift_code or not eligible_today(
                    p, day, shift_code, rules, shifts_map
                ):
                    continue

                has_skill = s in set(p.get("station_skills") or [])
                cost, extra = assignment_cost(p, s, shift_code, rules, day)

                # === D 規則：週成本加權（由 generate_week 顯式傳入 weekly_context）===
                ws = weekly_context
                if ws is not None:
                    name = p["name"]
                    days_worked = ws["days_worked"][name]
                    consec = ws["consecutive_days"][name]
                    week_hours = ws["weekly_hours"][name]

                    weekly_penalty = (
                        days_worked * 0.8 + consec * 0.5 + week_hours * 0.05
                    )
                    cost += weekly_penalty

                # 把加完週成本的 cost 加進候選池
                item = (cost, p, shift_code, extra)
                if has_skill:
                    strict_pool.append(item)
                else:
                    relaxed_pool.append(item)

            # 先用有技能的人；不夠再用 fallback 沒技能的人
            candidate_pool = strict_pool
            fallback_flag = False
            if not candidate_pool and allow_fallback and relaxed_pool:
                candidate_pool = relaxed_pool
                fallback_flag = True

            if not candidate_pool:
                continue

            # cost 最低的那個人
            candidate_pool.sort(key=lambda x: x[0])
            best = candidate_pool[0]
            _, person, shift_code, extra = best

            rec = {"name": person["name"], "shift": shift_code}
            notes = []

            if fallback_flag or extra.get("fallback_no_skill"):
                notes.append("fallback_no_skill")
            if extra.get("soft_off_override"):
                notes.append("soft_off_override")

            if notes:
                rec["notes"] = notes

            assignments[s].append(rec)
            used_today.add(person["name"])
            hours_estimate[person["name"]] = hours_estimate.get(
                person["name"], 0.0
            ) + paid_hours_map.get(shift_code, 0.0)
            placed_any = True
            break  # 換下一個站位

        if not placed_any:
            break

    # 主廚檢查
    if require_one_chef and len(chefs_present) == 0:
        warnings.append("NO_CHEF_AVAILABLE")
    # 早班站位人數檢查
    assignments = enforce_morning_requirements(assignments, rules)

    # 輸出
    out = {
        "date": date_str,
        "is_holiday": is_holi,
        "chefs_present": chefs_present,
        "headcount_total": headcount_total(),
        "assignments": assignments,
        "hours_estimate": hours_estimate,
        "warnings": warnings,
    }
    return out


def greedy_assign(date_str: str, absent: List[str]) -> dict:
    inputs = _build_engine_inputs_default("demo_kitchen")
    return greedy_assign_with_inputs(date_str, absent, inputs)


def apply_manual_patch(
    day_plan: dict,
    patch: dict,
    rules: dict,
    shifts_map: dict,
    paid_hours_map: dict,
    calendar: dict,
    people: list[dict],
) -> tuple[dict, list[str]]:
    """
    讓外部用 JSON 方式調整某一天的排班。

    patch 範例：
    {
      "date": "2025-11-10",
      "name": "Kim",
      "station": "petit_four",
      "shift": "A"          # 若為 None / "" 表示把這個人當天排班清掉
    }

    回傳：(new_plan, errors)
      - errors 為空 list 代表成功
      - 有錯誤時會回傳原本的 day_plan + 錯誤碼
    """
    errors: list[str] = []

    # --- 基本欄位檢查 ---
    date_str = day_plan.get("date")
    if patch.get("date") and patch["date"] != date_str:
        errors.append("DATE_MISMATCH")
        return day_plan, errors

    name = patch.get("name")
    station = patch.get("station")
    shift_code = patch.get("shift")

    if not name or not station:
        errors.append("MISSING_NAME_OR_STATION")
        return day_plan, errors

    if shift_code:
        shift_code = str(shift_code).upper()
        if shift_code not in shifts_map:
            errors.append("INVALID_SHIFT_CODE")
            return day_plan, errors

    # --- 找人資訊 ---
    person = next((p for p in people if p["name"] == name), None)
    if person is None:
        errors.append("UNKNOWN_PERSON")
        return day_plan, errors
        # --- 當日基本 eligibility 檢查 ---
    day = dtparser.parse(date_str).replace(tzinfo=None)

    # 確保 eligible_today 裡面用到的 shifts_map 有值
    globals()["shifts_map"] = shifts_map

    # 如果有指定 shift，就檢查那個 shift 當天可不可以上
    if shift_code:
        # 這裡會用到 eligible_today（裡面會看 hard off、固定休等）
        if not eligible_today(person, day, shift_code, rules, shifts_map):
            errors.append("NOT_ELIGIBLE_TODAY_FOR_SHIFT")
            return day_plan, errors

    # --- 複製 assignments，避免直接改掉原物件 ---
    assignments = {
        s: [dict(rec) for rec in recs]
        for s, recs in day_plan.get("assignments", {}).items()
    }

    # 先把這個人從所有 station 移除，避免重複出現
    for s, recs in assignments.items():
        assignments[s] = [rec for rec in recs if rec["name"] != name]

    # 若有指定新 shift，就加入指定 station
    if shift_code:
        rec = {"name": name, "shift": shift_code}
        assignments.setdefault(station, []).append(rec)

    # --- 重新套用早班需求規則 ---
    assignments = enforce_morning_requirements(assignments, rules)

    # --- 重新計算 hours_estimate ---
    hours_estimate: dict[str, float] = {}
    for s, recs in assignments.items():
        for rec in recs:
            sc = rec["shift"]
            hours_estimate[rec["name"]] = hours_estimate.get(
                rec["name"], 0.0
            ) + paid_hours_map.get(sc, 0.0)

    # --- 重新計算 headcount_total ---
    def _headcount_total(assignments: dict, chefs_present: list[str]) -> int:
        base = sum(len(v) for v in assignments.values())
        if rules.get("count_chefs_in_headcount", True):
            base += len(chefs_present)
        return base

    new_plan = dict(day_plan)
    new_plan["assignments"] = assignments
    new_plan["hours_estimate"] = hours_estimate
    new_plan["headcount_total"] = _headcount_total(
        assignments,
        day_plan.get("chefs_present", []),
    )

    # TODO：如果之後要更嚴格，可以在這裡再加：
    # - 每個 station 是否低於 station_need
    # - 是否超過 max_staff
    # 不過先做到這裡，就已經可以讓 LLM 幫忙 patch + 檢查 eligibility 了。

    return new_plan, errors


# -------- CLI 入口 --------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("date", help="YYYY-MM-DD")
    ap.add_argument(
        "--absent", help="臨時請假名單，以逗號分隔，如 'Chung,Masuda'", default=None
    )
    args = ap.parse_args()

    date_str = args.date
    absent = parse_absent_list(args.absent)
    # 為安全，也把 workers.json 個人的 ad_hoc_unavailable 與 fixed day off 交給 eligible_today 檢查

    # 供 eligible_today 使用的全域 shifts_map（簡化傳參）
    globals_shifts = load_json("shifts.json")
    shifts_map, _ = build_shift_maps(globals_shifts)
    globals()["shifts_map"] = shifts_map

    # rules 在這裡也載入一份，給 print / validate 使用
    rules = load_json("rules.json")

    plan = greedy_assign(date_str, absent)

    # 原本的 JSON 輸出，保留
    print(json.dumps(plan, ensure_ascii=False, indent=2))

    # 新增：人類可讀的排班表
    # print_human_readable(plan, rules)

    # 新增：檢查總結
    # report = validate_plan(plan, rules)
    # print("\n[VALIDATION]")
    # print(json.dumps(report, ensure_ascii=False, indent=2))
