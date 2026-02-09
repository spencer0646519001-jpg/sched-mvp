from __future__ import annotations

import argparse
import json
import random

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


def run_engine(date: str, absent: list[str], seed: int | None = None) -> dict:
    if seed is not None:
        random.seed(seed)
    inputs = build_inputs_from_json()
    return greedy_assign_with_inputs(date, absent, inputs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("date", help="YYYY-MM-DD")
    parser.add_argument("--absent", default=None)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    absent = []
    if args.absent:
        absent = [x.strip() for x in args.absent.split(",") if x.strip()]

    out = run_engine(args.date, absent, seed=args.seed)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
