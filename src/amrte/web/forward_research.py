from __future__ import annotations

from typing import Any

from amrte.research.forward_runtime import (
    FORWARD_RESEARCH_RUNTIME_VERSION,
    forward_drift_snapshot_schema_identity,
    forward_observation_envelope_schema_identity,
    forward_research_components_from_inventory,
    forward_research_decision_record_schema_identity,
    forward_research_policy_identity,
    forward_research_session_schema_identity,
    shadow_research_comparison_schema_identity,
)


def build_forward_runtime_summary(runtime: Any, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    composition = getattr(runtime, "composition", None)
    diagnostics = composition.diagnostics() if composition is not None else None
    forward = _forward_runtime(composition)
    bounded_limit = max(1, min(int(limit), 100))
    items = forward.query_sessions(offset=max(0, int(offset)), limit=bounded_limit) if forward else ()
    return {
        "mode": "READ_ONLY",
        "research_only": True,
        "schema_version": "1.0",
        "runtime_version": FORWARD_RESEARCH_RUNTIME_VERSION,
        "policy_identity": forward_research_policy_identity(),
        "schemas": _schemas(),
        "authority": {
            "input_boundary": "P50 VersionedResearchConfiguration + P39 CanonicalMarketObservation",
            "observation_trust_authority": "P40 DataQualityTrustRuntime",
            "decision_authority_reference": "P46/P47 schema lineage",
            "configuration_mutation": False,
            "automatic_retuning": False,
            "financial_authorization": "NONE",
            "financial_execution": "NONE",
        },
        "components": forward_research_components_from_inventory(tuple(diagnostics["components"])) if diagnostics else {},
        "runtime_health": forward.diagnostics() if forward else None,
        "offset": max(0, int(offset)),
        "limit": bounded_limit,
        "session_count": len(forward.sessions) if forward else 0,
        "items": [_session_payload(item) for item in items],
        "financial_execution": "NONE",
    }


def build_forward_session_detail(runtime: Any, session_id: str) -> dict[str, Any]:
    forward = _forward_runtime(getattr(runtime, "composition", None))
    if forward is None:
        return {"mode": "READ_ONLY", "available": False, "reason": "P51_RUNTIME_UNAVAILABLE", "financial_execution": "NONE"}
    session = forward.sessions.get(session_id)
    if session is None:
        return {"mode": "READ_ONLY", "available": False, "reason": "P51_SESSION_NOT_FOUND", "session_id": session_id, "financial_execution": "NONE"}
    envelopes = forward.query_envelopes(session_id, limit=100)
    comparisons = forward.query_shadow_comparisons(session_id, limit=100)
    decisions = tuple(item for item in forward.decisions.values() if item.session_id == session_id)
    drifts = tuple(item for item in forward.drift_snapshots.values() if item.session_id == session_id)
    return {
        "mode": "READ_ONLY",
        "available": True,
        "session": _session_payload(session),
        "observation_envelopes": [_envelope_payload(item) for item in envelopes],
        "decisions": [_decision_payload(item) for item in decisions],
        "shadow_comparisons": [_comparison_payload(item) for item in comparisons],
        "drift_snapshots": [_drift_payload(item) for item in drifts],
        "financial_execution": "NONE",
    }


def build_forward_streams_summary(
    runtime: Any,
    *,
    session_id: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    forward = _forward_runtime(getattr(runtime, "composition", None))
    bounded_limit = max(1, min(int(limit), 100))
    items = forward.query_envelopes(session_id, offset=max(0, int(offset)), limit=bounded_limit) if forward else ()
    return {
        "mode": "READ_ONLY",
        "research_only": True,
        "schema_version": "1.0",
        "runtime_version": FORWARD_RESEARCH_RUNTIME_VERSION,
        "session_id": session_id,
        "offset": max(0, int(offset)),
        "limit": bounded_limit,
        "stream_count": len(forward.envelopes) if forward else 0,
        "items": [_envelope_payload(item) for item in items],
        "financial_execution": "NONE",
    }


def build_shadow_research_summary(
    runtime: Any,
    *,
    session_id: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    forward = _forward_runtime(getattr(runtime, "composition", None))
    bounded_limit = max(1, min(int(limit), 100))
    items = forward.query_shadow_comparisons(session_id, offset=max(0, int(offset)), limit=bounded_limit) if forward else ()
    return {
        "mode": "READ_ONLY",
        "research_only": True,
        "schema_version": "1.0",
        "runtime_version": FORWARD_RESEARCH_RUNTIME_VERSION,
        "schema_identity": shadow_research_comparison_schema_identity(),
        "session_id": session_id,
        "offset": max(0, int(offset)),
        "limit": bounded_limit,
        "comparison_count": len(forward.shadow_comparisons) if forward else 0,
        "items": [_comparison_payload(item) for item in items],
        "financial_execution": "NONE",
    }


def _forward_runtime(composition: Any) -> Any | None:
    if composition is None:
        return None
    try:
        component = composition.get("forward_research_runtime").component
    except Exception:
        return None
    return getattr(component, "runtime", None)


def _schemas() -> dict[str, str]:
    return {
        "forward_research_session": forward_research_session_schema_identity(),
        "forward_observation_envelope": forward_observation_envelope_schema_identity(),
        "forward_research_decision_record": forward_research_decision_record_schema_identity(),
        "shadow_research_comparison": shadow_research_comparison_schema_identity(),
        "forward_drift_snapshot": forward_drift_snapshot_schema_identity(),
    }


def _session_payload(item: Any) -> dict[str, Any]:
    return {
        "session_id": item.session_id,
        "research_configuration_id": item.research_configuration_id,
        "configuration_version": item.configuration_version,
        "configuration_fingerprint": item.configuration_fingerprint,
        "dataset_id": item.dataset_id,
        "dataset_fingerprint": item.dataset_fingerprint,
        "source_id": item.source_id,
        "instrument_id": item.instrument_id,
        "timeframe": item.timeframe,
        "session_state": item.session_state,
        "source_lifecycle_state": item.source_lifecycle_state,
        "observation_count": item.observation_count,
        "accepted_decision_count": item.accepted_decision_count,
        "duplicate_observation_count": item.duplicate_observation_count,
        "gap_count": item.gap_count,
        "backfill_count": item.backfill_count,
        "financial_execution": item.financial_execution,
    }


def _envelope_payload(item: Any) -> dict[str, Any]:
    return {
        "envelope_id": item.envelope_id,
        "session_id": item.session_id,
        "observation_id": item.observation_id,
        "trusted_observation_id": item.trusted_observation_id,
        "trust_status": item.trust_status,
        "source_id": item.source_id,
        "event_time_utc": item.event_time_utc.isoformat(),
        "sequence": item.sequence,
        "duplicate": item.duplicate,
        "backfill": item.backfill,
        "gap_detected": item.gap_detected,
        "effect": item.effect,
        "reason_codes": list(item.reason_codes),
        "warning_codes": list(item.warning_codes),
        "financial_execution": item.financial_execution,
    }


def _decision_payload(item: Any) -> dict[str, Any]:
    return {
        "decision_id": item.decision_id,
        "session_id": item.session_id,
        "observation_id": item.observation_id,
        "research_configuration_id": item.research_configuration_id,
        "forward_signal_value": str(item.forward_signal_value),
        "final_classification": item.final_classification,
        "effective_permission": item.effective_permission,
        "reason_codes": list(item.reason_codes),
        "financial_execution": item.financial_execution,
    }


def _comparison_payload(item: Any) -> dict[str, Any]:
    return {
        "comparison_id": item.comparison_id,
        "session_id": item.session_id,
        "decision_id": item.decision_id,
        "observation_id": item.observation_id,
        "baseline_shadow_value": str(item.baseline_shadow_value),
        "forward_signal_value": str(item.forward_signal_value),
        "absolute_delta": str(item.absolute_delta),
        "tolerance": str(item.tolerance),
        "state": item.state,
        "reason_codes": list(item.reason_codes),
        "financial_execution": item.financial_execution,
    }


def _drift_payload(item: Any) -> dict[str, Any]:
    return {
        "drift_snapshot_id": item.drift_snapshot_id,
        "session_id": item.session_id,
        "dimension": item.dimension,
        "baseline_mean": str(item.baseline_mean),
        "forward_mean": str(item.forward_mean),
        "absolute_delta": str(item.absolute_delta),
        "threshold": str(item.threshold),
        "sample_count": item.sample_count,
        "state": item.state,
        "reason_codes": list(item.reason_codes),
        "financial_execution": item.financial_execution,
    }
