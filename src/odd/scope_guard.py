"""Minimal fail-closed intended-use guard; deliberately not a scope framework."""

from __future__ import annotations

from collections.abc import Callable

from odd.constants import REGULATORY_ROLE_DISCOVERY_SCOPE
from odd.errors import ProvenanceValidationFailure

ScopeDiagnostic = dict[str, str]


def require_input_scope(
    *,
    intended_use_scope: str | None,
    required_input_scope: str,
    save_diagnostic: Callable[[ScopeDiagnostic], None],
) -> ScopeDiagnostic:
    """Require one exact declared scope and persist the decision before failing."""

    compatible = bool(intended_use_scope) and intended_use_scope == required_input_scope
    diagnostic = {
        "intended_use_scope": intended_use_scope or "MISSING",
        "required_input_scope": required_input_scope,
        "status": "SCOPE_MATCH" if compatible else "INTENDED_USE_SCOPE_VIOLATION",
    }
    save_diagnostic(diagnostic)
    if not compatible:
        raise ProvenanceValidationFailure(
            "producer intended-use scope does not exactly match the consumer requirement",
            details=diagnostic,
        )
    return diagnostic


def require_role_discovery_input(
    intended_use_scope: str | None,
    save_diagnostic: Callable[[ScopeDiagnostic], None],
) -> ScopeDiagnostic:
    """Guard the one known unsafe ODD-005-to-role-discovery connection."""

    return require_input_scope(
        intended_use_scope=intended_use_scope,
        required_input_scope=REGULATORY_ROLE_DISCOVERY_SCOPE,
        save_diagnostic=save_diagnostic,
    )
