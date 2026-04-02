from app.infra.station_metadata import build_station_metadata_overlay, serialize_station_metadata


def test_build_station_metadata_overlay_prefers_db_labels_but_keeps_base_station_codes():
    overlay = build_station_metadata_overlay(
        base_station_codes=["petit_four", "GATEAU", "petit_four"],
        db_station_rows=[
            {
                "code": "gateau",
                "display_name": "Gateau Counter",
                "is_active": False,
                "sort_order": 25,
            },
            {
                "code": "db_only_station",
                "display_name": "DB Only",
                "is_active": True,
                "sort_order": 99,
            },
        ],
    )

    assert overlay.ordered_codes == ["petit_four", "gateau"]
    assert overlay.labels == {
        "petit_four": "petit_four",
        "gateau": "Gateau Counter",
    }
    assert overlay.lookup["gateaucounter"] == "gateau"
    assert overlay.by_code["gateau"].is_active is False
    assert overlay.by_code["gateau"].sort_order == 25
    assert "db_only_station" not in overlay.by_code
    assert serialize_station_metadata(overlay) == [
        {
            "code": "petit_four",
            "display_name": "petit_four",
            "is_active": True,
            "sort_order": 0,
        },
        {
            "code": "gateau",
            "display_name": "Gateau Counter",
            "is_active": False,
            "sort_order": 25,
        },
    ]
