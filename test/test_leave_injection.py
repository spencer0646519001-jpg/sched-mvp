import importlib.util
import sys
import types
from pathlib import Path


def _identity_decorator(*args, **kwargs):
    if args and callable(args[0]) and len(args) == 1 and not kwargs:
        return args[0]

    def _decorator(fn):
        return fn

    return _decorator


def _load_api_views_unit(monkeypatch):
    django_http = types.ModuleType("django.http")
    django_http.JsonResponse = lambda *args, **kwargs: {"args": args, "kwargs": kwargs}
    django_http.HttpResponse = lambda *args, **kwargs: {"args": args, "kwargs": kwargs}

    django_csrf = types.ModuleType("django.views.decorators.csrf")
    django_csrf.csrf_exempt = _identity_decorator

    django_http_decorators = types.ModuleType("django.views.decorators.http")
    django_http_decorators.require_http_methods = _identity_decorator

    daily_presenter = types.ModuleType("core.presenters.daily_run_presenter")
    daily_presenter.present_create_daily_run_success = lambda **kwargs: kwargs
    daily_presenter.present_create_daily_run_graph_success = lambda **kwargs: kwargs

    core_models = types.ModuleType("core.models")
    core_models.ScheduleRun = type("ScheduleRun", (), {"objects": type("Mgr", (), {})()})

    month_service = types.ModuleType("app.month_service")
    month_service.run_daily_schedule = lambda *args, **kwargs: None
    month_service.build_month = lambda *args, **kwargs: {}

    run_service = types.ModuleType("app.run_service")
    run_service.build_out_from_run = lambda *args, **kwargs: {}

    presenter = types.ModuleType("app.presenter")
    presenter.present_run_out = lambda *args, **kwargs: {}
    presenter.present_api_success = lambda *args, **kwargs: {}
    presenter.present_api_error = lambda *args, **kwargs: {}

    generate_day = types.ModuleType("app.generate_day")
    generate_day.greedy_assign = lambda date_str, absent: {
        "date": date_str,
        "assignments": {},
        "hours_estimate": {},
        "warnings": [],
        "is_holiday": False,
    }
    generate_day.load_json = lambda *_args, **_kwargs: {"people": []}

    plan_service = types.ModuleType("app.plan_service")
    plan_service.create_plan = lambda *args, **kwargs: {}
    plan_service.patch_preview = lambda *args, **kwargs: {}
    plan_service.patch_apply = lambda *args, **kwargs: {}
    plan_service.get_plan = lambda *args, **kwargs: {}
    plan_service.list_all_plans = lambda *args, **kwargs: []
    plan_service.delete_plan = lambda *args, **kwargs: {}

    generate_week = types.ModuleType("app.generate_week")
    generate_week.generate_week = lambda *args, **kwargs: {
        "week_plan": {},
        "days_worked": {},
        "days_off": {},
        "consecutive_days": {},
        "weekly_hours": {},
        "shift_count": {},
    }
    generate_week.summarize_week = lambda *_args, **_kwargs: {}

    shift_defs = types.ModuleType("core.shift_defs")
    shift_defs.ShiftDefsInvalid = type("ShiftDefsInvalid", (Exception,), {})
    shift_defs.ShiftDefsNotFound = type("ShiftDefsNotFound", (Exception,), {})
    shift_defs.build_shift_legend = lambda *_args, **_kwargs: {"": {"label": ""}, "OFF": {"label": "OFF"}}
    shift_defs.load_shift_defs = lambda *_args, **_kwargs: {}

    app_pkg = types.ModuleType("app")
    app_pkg.__path__ = []
    app_pkg.generate_day = generate_day

    core_presenters_pkg = types.ModuleType("core.presenters")
    core_presenters_pkg.__path__ = []

    monkeypatch.setitem(sys.modules, "django.http", django_http)
    monkeypatch.setitem(sys.modules, "django.views.decorators.csrf", django_csrf)
    monkeypatch.setitem(sys.modules, "django.views.decorators.http", django_http_decorators)
    monkeypatch.setitem(sys.modules, "core.presenters", core_presenters_pkg)
    monkeypatch.setitem(sys.modules, "core.presenters.daily_run_presenter", daily_presenter)
    monkeypatch.setitem(sys.modules, "core.models", core_models)
    monkeypatch.setitem(sys.modules, "app", app_pkg)
    monkeypatch.setitem(sys.modules, "app.month_service", month_service)
    monkeypatch.setitem(sys.modules, "app.run_service", run_service)
    monkeypatch.setitem(sys.modules, "app.presenter", presenter)
    monkeypatch.setitem(sys.modules, "app.generate_day", generate_day)
    monkeypatch.setitem(sys.modules, "app.plan_service", plan_service)
    monkeypatch.setitem(sys.modules, "app.generate_week", generate_week)
    monkeypatch.setitem(sys.modules, "core.shift_defs", shift_defs)

    module_path = Path(__file__).resolve().parents[1] / "core" / "api_views.py"
    spec = importlib.util.spec_from_file_location("unit_core_api_views", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_leave_merge_and_dedup(monkeypatch):
    api_views = _load_api_views_unit(monkeypatch)

    observed = {}

    def fake_generate_month_state(start_date_str, leave_by_date=None):
        observed["start_date_str"] = start_date_str
        observed["leave_by_date"] = leave_by_date
        return {
            "month_start": "2025-11-01",
            "month_end": "2025-11-30",
            "plan": {},
            "summary": {},
            "overtime": {},
        }

    monkeypatch.setattr(api_views, "_generate_month_state", fake_generate_month_state)

    api_views._generate_month_state_with_leave_requests(
        "2025-11-01",
        {"2025-11-05": ["Kim", "Ana", "Ana"]},
    )

    assert observed["start_date_str"] == "2025-11-01"
    assert observed["leave_by_date"] == {"2025-11-05": ["Kim", "Ana", "Ana"]}


def test_generate_month_state_with_leave_requests_propagates_exceptions(monkeypatch):
    api_views = _load_api_views_unit(monkeypatch)

    def fake_generate_month_state(_start_date_str, leave_by_date=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(api_views, "_generate_month_state", fake_generate_month_state)

    try:
        api_views._generate_month_state_with_leave_requests("2025-11-01", {"2025-11-05": ["Kim", "Kim"]})
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert str(exc) == "boom"
