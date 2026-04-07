from app.langgraph_flow import node_explain


def test_node_explain_accumulates_metrics_from_trace_items():
    result = node_explain(
        {
            "language": "en",
            "decision_trace": [
                {
                    "station": "gateau",
                    "picked": ["Aki", "Bea"],
                    "picked_has_skill": ["Aki"],
                    "has_fallback": True,
                    "missing_but_absent_top": ["Cora"],
                    "missing_and_not_absent_top": ["Dev"],
                    "skilled_pool_top": ["Aki", "Cora", "Dev"],
                    "skilled_missing_top": ["Cora", "Dev"],
                    "skilled_total": 3,
                    "notes": ["fallback_no_skill"],
                },
                {
                    "station": "petit_four",
                    "picked": ["Eli"],
                    "picked_has_skill": ["Eli"],
                    "has_fallback": False,
                    "missing_but_absent_top": [],
                    "missing_and_not_absent_top": ["Fran"],
                    "skilled_pool_top": ["Eli", "Fran"],
                    "skilled_missing_top": ["Fran"],
                    "skilled_total": 2,
                    "notes": [],
                },
            ],
        }
    )

    assert result["metrics"] == {
        "stations_total": 2,
        "fallback_stations": 1,
        "fallback_people_total": 1,
        "absent_skill_total": 1,
        "skill_not_used_total": 2,
    }
    assert set(result["explanations"]) == {"gateau", "petit_four"}
