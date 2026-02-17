from __future__ import annotations

import argparse
import json
import random

from app.generate_day import greedy_assign_with_inputs
from app.infra.engine_inputs import build_inputs_from_json


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
