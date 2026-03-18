"""Shared helper functions for API view modules."""

import json

from app.presenter import present_api_error


def _parse_request_payload(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}"), None
    except json.JSONDecodeError:
        payload_err = present_api_error(
            code="invalid_json",
            message="Invalid JSON body",
        )
        return None, payload_err


def _validate_daily_run_payload(payload, *, include_absent_type: bool):
    date_str = payload.get("date")
    if not date_str:
        payload_err = present_api_error(
            code="missing_date",
            message="Missing 'date' in body",
        )
        return None, None, payload_err

    absent = payload.get("absent") or []
    if not isinstance(absent, list):
        details = {"absent_type": type(absent).__name__} if include_absent_type else None
        payload_err = present_api_error(
            code="invalid_absent",
            message="'absent' must be a list",
            details=details,
        )
        return None, None, payload_err

    return date_str, absent, None
