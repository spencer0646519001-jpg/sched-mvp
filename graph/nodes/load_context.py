# graph/nodes/load_context.py
from graph.state import ScheduleState

def load_context(state: ScheduleState) -> ScheduleState:
    # B1: 先做 identity node（不改 state）
    # 之後 B2 才會在這裡載入 tenant rules / station map / config 等
    return state
