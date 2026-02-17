from dataclasses import dataclass
from typing import Dict, List, Optional

from app.generate_day import build_shift_maps, load_json


@dataclass(frozen=True)
class PlanData:
    shifts_list: List[dict]
    shifts_map: Dict[str, dict]
    paid_hours_map: Dict[str, float]
    rules: dict
    calendar: dict
    people: List[dict]


class PlanDataProvider:
    def __init__(self) -> None:
        self._memo: Optional[PlanData] = None

    def get(self) -> PlanData:
        if self._memo is None:
            shifts_list = load_json("shifts.json")
            shifts_map, paid_hours_map = build_shift_maps(shifts_list)
            rules = load_json("rules.json")
            calendar = load_json("calendar.json")
            people = load_json("workers.json").get("people", [])
            self._memo = PlanData(
                shifts_list=shifts_list,
                shifts_map=shifts_map,
                paid_hours_map=paid_hours_map,
                rules=rules,
                calendar=calendar,
                people=people,
            )
        return self._memo


default_plan_data_provider = PlanDataProvider()
