from __future__ import annotations

import random

from app.generate_day import EngineInputs, greedy_assign_with_inputs


def run_engine(
    date: str,
    absent: list[str],
    inputs: EngineInputs,
    seed: int | None = None,
) -> dict:
    if seed is not None:
        random.seed(seed)
    return greedy_assign_with_inputs(date, absent, inputs)
