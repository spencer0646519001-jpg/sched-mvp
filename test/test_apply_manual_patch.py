# test_apply_manual_patch.py
import json
from app.generate_day import (
    greedy_assign,
    apply_manual_patch,
    load_json,
    build_shift_maps,
)


def main():
    date = "2025-11-10"
    absent = []

    # 1. 先產生原始班表
    base_plan = greedy_assign(date, absent)
    print("=== 原始班表（部分） ===")
    print(json.dumps(base_plan["assignments"], ensure_ascii=False, indent=2))

    # 2. 準備必要設定
    shifts_list = load_json("shifts.json")
    shifts_map, paid_hours_map = build_shift_maps(shifts_list)
    rules = load_json("rules.json")
    calendar = load_json("calendar.json")
    people = load_json("workers.json")["people"]

    # 3. 做一個示範 patch：
    #    把 Kim 調去 petit_four 的 A 班
    patch = {
        "date": date,
        "name": "Kim",
        "station": "petit_four",
        "shift": "A",
    }

    new_plan, errors = apply_manual_patch(
        base_plan,
        patch,
        rules,
        shifts_map,
        paid_hours_map,
        calendar,
        people,
    )

    print("\n=== patch 結果的錯誤列表 ===")
    print(errors)

    print("\n=== patch 後的班表（部分） ===")
    print(json.dumps(new_plan["assignments"], ensure_ascii=False, indent=2))
    print("\n=== [錯誤測試] INVALID_SHIFT_CODE ===")
    patch_bad_shift = {
        "date": date,
        "name": "Kim",
        "station": "petit_four",
        "shift": "Z",
    }
    new_plan, errs = apply_manual_patch(
        base_plan,
        patch_bad_shift,
        rules,
        shifts_map,
        paid_hours_map,
        calendar,
        people,
    )
    print("errors =", errs)
    print("\n=== [錯誤測試] UNKNOWN_PERSON ===")
    patch_bad_person = {
        "date": date,
        "name": "Nobody",
        "station": "petit_four",
        "shift": "A",
    }
    new_plan, errs = apply_manual_patch(
        base_plan,
        patch_bad_person,
        rules,
        shifts_map,
        paid_hours_map,
        calendar,
        people,
    )
    print("errors =", errs)


if __name__ == "__main__":
    main()
