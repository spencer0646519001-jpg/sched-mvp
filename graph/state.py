# graph/state.py
from typing import TypedDict, List, Dict, Any, NotRequired

class ScheduleState(TypedDict):
    date: str
    input: Dict[str, Any]
    greedy_result: NotRequired[Dict[str, Any]]
    decision_trace: NotRequired[List[Dict[str, Any]]]
