"""Read-only Research Lifecycle & Quality Assurance evidence surface.

This module intentionally does not construct or invoke the underlying
research engines.  The target engines are implemented domain capabilities,
not registered runtime authorities, so current engine state is unavailable.
"""

from __future__ import annotations

from typing import Any


PRODUCT = "Research Lifecycle & Quality Assurance Console"
ENVIRONMENT = "RESEARCH"


def build_research_lifecycle_quality_payload() -> dict[str, Any]:
    """Return static implementation and contract evidence only."""

    domains: dict[str, dict[str, Any]] = {
        "research_lifecycle": {
            "engine": "ResearchLifecycleEngine",
            "implementation_state": "IMPLEMENTED",
            "implemented": True,
            "runtime_active": False,
            "runtime_authority": False,
            "current_state_available": False,
            "engine_version": "1.0",
            "recovery_schema_version": "1.0",
            "states": [
                "PROPOSED",
                "VALIDATED",
                "AUTHORIZED",
                "QUEUED",
                "ACTIVATED",
                "ACTIVE",
                "SAFEGUARDED",
                "MONITORED",
                "RESOLVED",
                "ARCHIVED",
                "REJECTED",
                "CANCELLED",
                "EXPIRED",
                "INVALIDATED",
                "FAILED",
            ],
            "health_states": [
                "HEALTHY",
                "DEGRADED",
                "QUARANTINED",
                "INVALID",
                "UNKNOWN",
            ],
            "decisions": [
                "ALLOW",
                "BLOCK",
                "NO_ACTION",
                "INVALID",
            ],
        },
        "observation_quality": {
            "engine": "ObservationQualityEngine",
            "implementation_state": "IMPLEMENTED",
            "implemented": True,
            "runtime_active": False,
            "runtime_authority": False,
            "current_state_available": False,
            "engine_version": "1.0",
            "recovery_schema_version": "1.0",
            "observation_health": [
                "HEALTHY",
                "DEGRADED",
                "STALE",
                "INVALID",
                "UNAVAILABLE",
                "UNKNOWN",
            ],
            "quality_states": [
                "HEALTHY",
                "DEGRADED",
                "POOR",
                "UNTRUSTED",
                "UNAVAILABLE",
                "UNKNOWN",
            ],
            "restrictions": [
                "ALLOW",
                "RESTRICT",
                "BLOCK",
                "NO_ACTION",
            ],
            "deviation_regimes": [
                "NORMAL",
                "ELEVATED",
                "HIGH",
                "EXTREME",
                "UNKNOWN",
            ],
        },
        "research_reliability": {
            "engine": "ResearchReliabilityEngine",
            "implementation_state": "IMPLEMENTED",
            "implemented": True,
            "runtime_active": False,
            "runtime_authority": False,
            "current_state_available": False,
            "engine_version": "1.0",
            "recovery_schema_version": "1.0",
            "stages": [
                "NORMAL",
                "WATCH",
                "RESTRICTED",
                "PROTECTED",
                "SUSPENDED",
                "UNKNOWN",
            ],
            "health_states": [
                "HEALTHY",
                "DEGRADED",
                "RESTRICTED",
                "INVALID",
                "UNKNOWN",
            ],
            "decisions": [
                "ACCEPTED",
                "NO_ACTION",
                "BLOCKED",
                "INVALID",
            ],
        },
        "temporal_quality": {
            "engine": "TemporalQualityProtectionEngine",
            "implementation_state": "IMPLEMENTED",
            "implemented": True,
            "runtime_active": False,
            "runtime_authority": False,
            "current_state_available": False,
            "engine_version": "1.0",
            "recovery_schema_version": "1.0",
            "stages": [
                "NORMAL",
                "WATCH",
                "RESTRICTED",
                "COOLDOWN",
                "SUSPENDED",
                "UNKNOWN",
            ],
            "outcome_classes": [
                "ADVERSE",
                "NEUTRAL",
                "FAVORABLE",
                "UNKNOWN",
            ],
            "cooldown_states": [
                "INACTIVE",
                "ACTIVE",
                "EXPIRED_PENDING_CONFIRMATION",
                "RELEASED",
            ],
            "decisions": [
                "ACCEPTED",
                "NO_ACTION",
                "BLOCKED",
                "INVALID",
            ],
        },
        "system_safety": {
            "engine": "SystemSafetyEngine",
            "implementation_state": "IMPLEMENTED",
            "implemented": True,
            "runtime_active": False,
            "runtime_authority": False,
            "current_state_available": False,
            "engine_version": "1.0",
            "recovery_schema_version": "1.0",
            "states": [
                "NORMAL",
                "CAUTION",
                "RESTRICTED",
                "CIRCUIT_OPEN",
                "EMERGENCY_STOP",
                "RECOVERY_PENDING",
                "PROBATION",
                "UNKNOWN",
            ],
            "signal_severities": [
                "INFO",
                "LOW",
                "MEDIUM",
                "HIGH",
                "CRITICAL",
                "UNKNOWN",
            ],
            "incident_states": [
                "OPEN",
                "LATCHED",
                "RECOVERY_PENDING",
                "PROBATION",
                "RESOLVED",
            ],
            "trigger_scopes": [
                "SCOPED",
                "GLOBAL",
            ],
            "decisions": [
                "ACCEPTED",
                "NO_ACTION",
                "BLOCKED",
                "INVALID",
            ],
        },
    }

    return {
        "product": PRODUCT,
        "environment": ENVIRONMENT,
        "read_only": True,
        "domains": domains,
        "runtime_authority": {
            "authoritative_runtime": "PersistentResearchRuntime",
            "target_engines_registered": False,
            "target_engines_runtime_active": False,
            "target_engines_current_state_available": False,
        },
        "current_state": {
            "available": False,
            "status": "UNAVAILABLE",
            "reason": (
                "The target research engines are not registered with the "
                "authoritative runtime; current engine state is therefore "
                "not available from this console."
            ),
        },
        "safety_boundary": {
            "environment": "RESEARCH",
            "financial_execution": False,
            "broker_connectivity": False,
            "account_connectivity": False,
            "order_execution": False,
            "position_management": False,
            "live_execution": False,
            "demo_execution": False,
        },
    }
