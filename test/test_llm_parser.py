import json
from app.llm_parser import parse_request_to_patch


def main():
    workers = ["Kim", "Spencer", "Masuda", "Chung"]
    stations = ["petit_four", "glaze_and_fruit", "gateau"]
    shifts = ["A", "B", "C", "D", "1", "2"]

    user_input = "キムさんをプチフールのA番に移してください"

    result = parse_request_to_patch.invoke(
        {
            "user_input": user_input,
            "workers": workers,
            "stations": stations,
            "shifts": shifts,
        }
    )

    print("\n=== LLM 解析結果 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
