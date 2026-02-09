from __future__ import annotations

import argparse
import json

from app.generate_day import EngineInputs, greedy_assign_with_inputs
from app.infra.json_loader import load_calendar, load_rules, load_shifts, load_workers


def build_inputs_from_json() -> EngineInputs:
    shifts_list = load_shifts()
    rules = load_rules()
    calendar = load_calendar()
    workers = load_workers()
    people = workers.get("people") or []
    station_order = [str(k).strip().lower() for k in (rules.get("stations") or {}).keys()]
    return EngineInputs(
        shifts_list=shifts_list,
        rules=rules,
        calendar=calendar,
        people=[p for p in people if isinstance(p, dict)],
        station_order=station_order,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("date", help="YYYY-MM-DD")
    parser.add_argument("--absent", default=None)
    args = parser.parse_args()

    absent = []
    if args.absent:
        absent = [x.strip() for x in args.absent.split(",") if x.strip()]

    inputs = build_inputs_from_json()
    out = greedy_assign_with_inputs(args.date, absent, inputs)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
