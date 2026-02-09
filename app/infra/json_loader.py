from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _load_json(name: str) -> Any:
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def load_shifts() -> list[dict]:
    return _load_json("shifts.json")


def load_rules() -> dict:
    return _load_json("rules.json")


def load_calendar() -> dict:
    return _load_json("calendar.json")


def load_workers() -> dict:
    return _load_json("workers.json")
