from app.infra.shift_metadata import build_shift_metadata_overlay, serialize_shift_metadata


def test_build_shift_metadata_overlay_prefers_db_labels_but_keeps_base_shift_codes():
    overlay = build_shift_metadata_overlay(
        base_shift_defs=[
            {"code": "A", "start": "10:00", "end": "20:00", "break_minutes": 60, "paid_hours": 9.0},
            {"code": "D", "start": "14:00", "end": "23:00", "break_minutes": 60, "paid_hours": 8.0},
            {"code": "A", "start": "10:00", "end": "20:00", "break_minutes": 60, "paid_hours": 9.0},
        ],
        db_shift_rows=[
            {
                "code": "a",
                "display_name": "Morning Prep",
                "legend_label": "Morning Prep shift",
                "paid_hours": 7.5,
            },
            {
                "code": "db_only_shift",
                "display_name": "DB Only",
                "legend_label": "DB Only shift",
                "paid_hours": 6.0,
            },
        ],
    )

    assert overlay.ordered_codes == ["A", "D"]
    assert overlay.labels == {
        "A": "Morning Prep",
        "D": "D",
    }
    assert overlay.lookup["morningprep"] == "A"
    assert overlay.by_code["A"].legend_label == "Morning Prep shift"
    assert overlay.by_code["A"].paid_hours == 7.5
    assert overlay.by_code["D"].paid_hours == 8.0
    assert "DB_ONLY_SHIFT" not in overlay.by_code
    assert serialize_shift_metadata(overlay) == [
        {
            "code": "A",
            "display_name": "Morning Prep",
            "legend_label": "Morning Prep shift",
            "start": "10:00",
            "end": "20:00",
            "break_minutes": 60,
            "paid_hours": 7.5,
        },
        {
            "code": "D",
            "display_name": "D",
            "legend_label": "",
            "start": "14:00",
            "end": "23:00",
            "break_minutes": 60,
            "paid_hours": 8.0,
        },
    ]
