from __future__ import annotations

from typing import Any

from amrte.research.outcome_performance import (
    RESEARCH_OUTCOME_RUNTIME_VERSION,
    research_outcome_attribution_schema_identity,
    research_outcome_performance_components_from_inventory,
    research_outcome_policy_identity,
    research_outcome_window_schema_identity,
    research_performance_snapshot_schema_identity,
)


def build_research_performance_summary(runtime: Any) -> dict[str, Any]:
    composition = getattr(runtime, "composition", None)
    diagnostics = composition.diagnostics() if composition is not None else None
    outcome = _outcome_runtime(composition)
    runtime_status = outcome.diagnostics() if outcome is not None else None
    latest = next(reversed(outcome.snapshots.values()), None) if outcome is not None and outcome.snapshots else None
    return {
        "mode": "READ_ONLY",
        "research_only": True,
        "schema_version": "1.0",
        "runtime_version": RESEARCH_OUTCOME_RUNTIME_VERSION,
        "policy_identity": research_outcome_policy_identity(),
        "schemas": {
            "outcome_window": research_outcome_window_schema_identity(),
            "outcome_attribution": research_outcome_attribution_schema_identity(),
            "performance_snapshot": research_performance_snapshot_schema_identity(),
        },
        "authority": {
            "historical_decision_source": "P47 ResearchDecisionEvidenceRecord",
            "future_observation_source": "P39 CanonicalMarketObservation + P40 TrustedResearchObservation",
            "historical_decision_mutation_available": False,
            "configuration_mutation_available": False,
            "strategy_promotion_available": False,
            "financial_authorization": "NONE",
        },
        "components": research_outcome_performance_components_from_inventory(tuple(diagnostics["components"])) if diagnostics else {},
        "runtime_health": runtime_status,
        "latest_performance_snapshot": _snapshot_payload(latest) if latest is not None else None,
        "decision_population": {
            "mature_outcomes": latest.mature_outcome_count if latest else 0,
            "partial_outcomes": latest.partial_count if latest else 0,
            "missing_outcomes": latest.missing_count if latest else 0,
            "invalid_outcomes": latest.invalid_count if latest else 0,
        },
        "classification_analytics": dict(latest.classification_distribution) if latest else {},
        "strategy_attribution": dict(latest.strategy_attribution) if latest else {},
        "regime_attribution": dict(latest.regime_attribution) if latest else {},
        "session_attribution": dict(latest.session_attribution) if latest else {},
        "configuration_attribution": dict(latest.configuration_attribution) if latest else {},
        "no_action_analytics": dict(latest.no_action_statistics) if latest else {"sample_count": 0},
        "restriction_analytics": dict(latest.restriction_statistics) if latest else {"sample_count": 0},
        "portfolio_interaction_analytics": dict(latest.portfolio_interaction_evidence) if latest else {},
        "sample_sufficiency": latest.sample_sufficiency if latest else "INSUFFICIENT_EVIDENCE",
        "warnings": list(latest.warnings) if latest else ["P48_NO_PERFORMANCE_SNAPSHOT_PUBLISHED"],
        "limitations": list(latest.limitations) if latest else ["Healthy runtime does not imply sufficient research evidence."],
        "financial_execution": "NONE",
    }


def build_research_outcomes_summary(
    runtime: Any,
    *,
    offset: int = 0,
    limit: int = 50,
    classification: str | None = None,
) -> dict[str, Any]:
    outcome = _outcome_runtime(getattr(runtime, "composition", None))
    bounded_limit = max(1, min(int(limit), 100))
    if outcome is None:
        return {
            "mode": "READ_ONLY",
            "available": False,
            "reason": "P48_OUTCOME_RUNTIME_UNAVAILABLE",
            "items": [],
            "financial_execution": "NONE",
        }
    items = outcome.query_attributions(offset=max(0, int(offset)), limit=bounded_limit, classification=classification)
    return {
        "mode": "READ_ONLY",
        "available": True,
        "schema_identity": research_outcome_attribution_schema_identity(),
        "policy_identity": outcome.policy.policy_identity,
        "offset": max(0, int(offset)),
        "limit": bounded_limit,
        "classification": classification,
        "count": len(items),
        "items": [_attribution_payload(item) for item in items],
        "financial_execution": "NONE",
    }


def _outcome_runtime(composition: Any) -> Any | None:
    if composition is None:
        return None
    try:
        component = composition.get("research_performance_snapshot").component
    except Exception:
        return None
    return getattr(component, "runtime", None)


def _snapshot_payload(snapshot: Any) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "as_of": snapshot.as_of.isoformat(),
        "decision_count": snapshot.decision_count,
        "mature_outcome_count": snapshot.mature_outcome_count,
        "partial_count": snapshot.partial_count,
        "missing_count": snapshot.missing_count,
        "invalid_count": snapshot.invalid_count,
        "sample_sufficiency": snapshot.sample_sufficiency,
        "snapshot_fingerprint": snapshot.snapshot_fingerprint,
    }


def _attribution_payload(item: Any) -> dict[str, Any]:
    return {
        "attribution_id": item.attribution_id,
        "evidence_record_id": item.evidence_record_id,
        "decision_id": item.decision_id,
        "trace_id": item.trace_id,
        "outcome_window_id": item.outcome_window_id,
        "decision_classification": item.decision_classification,
        "strategy_id": item.strategy_id,
        "strategy_version": item.strategy_version,
        "regime_at_decision": item.regime_at_decision,
        "session_at_decision": item.session_at_decision,
        "configuration_identity": item.configuration_identity,
        "score_band": item.score_band,
        "research_direction": item.research_direction,
        "normalized_research_change": str(item.normalized_research_change) if item.normalized_research_change is not None else None,
        "research_change_applicability": item.research_change_applicability,
        "hypothesis_outcome": item.hypothesis_outcome,
        "causal_claim": item.causal_claim,
        "financial_execution": item.financial_execution,
        "attribution_fingerprint": item.attribution_fingerprint,
    }
