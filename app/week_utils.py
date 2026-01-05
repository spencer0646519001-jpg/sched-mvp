from typing import List, Dict, Tuple

# 之後可以改成從 people.json 讀，現在先寫死
CHEF_LIST = ["Takahashi_chef", "Funatsu"]

def pick_chefs_for_day(
    is_holiday: bool,
    state: Dict,
    all_chefs: List[str] = None,
    max_days_per_week: int = 5,
) -> Tuple[List[str], List[str]]:
    """
    根據平日 / 假日、目前週狀態，選出今天要上班的主廚清單。
    使用 state["days_worked"][name] 來判斷這週已經上了幾天。
    回傳 (chefs_present, warnings)
    """
    if all_chefs is None:
        all_chefs = CHEF_LIST

    # 1. 平日最多 1 個主廚，假日最多 2 個主廚
    if is_holiday:
        min_chefs = 1
        max_chefs = 2
    else:
        min_chefs = 1
        max_chefs = 1

    warnings: List[str] = []

    days_worked: Dict[str, int] = state["days_worked"]

    # 2. 先挑「這週工作天數 < max_days_per_week」的主廚當候選
    candidates = [
        name for name in all_chefs
        if days_worked.get(name, 0) < max_days_per_week
    ]

    # 3. 依照「已工作天數」由少到多排序，優先讓本週上班少的人先上
    candidates.sort(key=lambda name: days_worked.get(name, 0))

    picked: List[str] = []

    for name in candidates:
        if len(picked) >= max_chefs:
            break
        picked.append(name)

    # 4. 如果還沒達到最低主廚人數（理論上是所有人都滿 5 天才會發生）
    if len(picked) < min_chefs:
        # 從所有主廚裡挑「工作天數最少」的一個硬上
        overflow_candidates = sorted(
            all_chefs,
            key=lambda name: days_worked.get(name, 0)
        )
        for name in overflow_candidates:
            if name in picked:
                continue
            picked.append(name)
            warnings.append(f"CHEF_OVERWORK:{name}")
            break

    return picked, warnings

def choose_shift_for_person(
    name: str,
    allowed_shifts: List[str],
    state: Dict,
) -> str:
    """
    在 allowed_shifts 中，選出對這個人本週來說「使用次數最少」的班別。
    同時直接更新 state["shift_count"][name][shift]。
    """
    shift_count = state.setdefault("shift_count", {}).setdefault(name, {})

    # 從允許的班別中，挑使用次數最少的那個
    best_shift = min(
        allowed_shifts,
        key=lambda s: shift_count.get(s, 0)
    )

    # 更新使用次數
    shift_count[best_shift] = shift_count.get(best_shift, 0) + 1

    return best_shift
