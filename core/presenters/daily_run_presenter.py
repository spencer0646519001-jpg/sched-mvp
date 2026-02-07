# core/presenters/daily_run_presenter.py
from typing import Any, Dict

from app.presenter import present_api_success, present_run_out


def present_create_daily_run_success(*, run_id: int, date_str: str, out: Dict[str, Any]) -> Dict[str, Any]:
    presented = present_run_out(date=date_str, out=out)
    return present_api_success(
        data={"run_id": run_id, "out": presented},
        meta={"engine_version": "0.1"},
    )


def present_create_daily_run_graph_success(*, out: Dict[str, Any]) -> Dict[str, Any]:
    # 這個 out 是 graph 已經組好的結果（含 ok/data/meta 的 out）
    return present_api_success(
        data={"out": out},
        meta={"engine_version": "0.1"},
    )
