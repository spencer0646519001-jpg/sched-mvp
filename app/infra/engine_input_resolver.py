"""Resolve canonical scheduler engine inputs for the current demo runtime.

The resolver is intentionally narrow and truthful:
- only the demo fixture tenant is supported
- canonical demo scheduler inputs remain JSON-backed today
"""

from __future__ import annotations

from app.infra.engine_inputs import build_inputs_from_json


DEMO_TENANT_NAME = "demo_kitchen"
_SUPPORTED_TENANTS = (DEMO_TENANT_NAME,)


class UnsupportedEngineInputTenant(ValueError):
    def __init__(self, tenant_name: str):
        self.tenant_name = tenant_name
        supported = ", ".join(_SUPPORTED_TENANTS)
        super().__init__(
            f"Unsupported scheduling tenant '{tenant_name}'. "
            f"Canonical scheduling currently supports only {supported}."
        )


def _normalize_tenant_name(tenant_name: str) -> str:
    return str(tenant_name or "").strip()


def supported_engine_input_tenants() -> list[str]:
    return list(_SUPPORTED_TENANTS)


def require_supported_engine_input_tenant(tenant_name: str) -> str:
    normalized = _normalize_tenant_name(tenant_name)
    if normalized not in _SUPPORTED_TENANTS:
        raise UnsupportedEngineInputTenant(normalized)
    return normalized


def resolve_engine_inputs_for_tenant(tenant_name: str):
    """Return the canonical demo scheduler engine inputs for a supported tenant."""

    require_supported_engine_input_tenant(tenant_name)
    return build_inputs_from_json()
