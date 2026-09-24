from __future__ import annotations

from typing import Any

from amrte.research.improvement_intelligence import (
    RESEARCH_IMPROVEMENT_RUNTIME_VERSION,
    improvement_candidate_schema_identity,
    research_failure_cluster_schema_identity,
    research_improvement_components_from_inventory,
    research_improvement_policy_identity,
    research_improvement_snapshot_schema_identity,
)


def build_research_improvements_summary(
    runtime: Any,
    *,
    offset: int = 0,
    limit: int = 50,
    finding_type: str | None = None,
    domain: str | None = None,
) -> dict[str, Any]:
    composition = getattr(runtime, "composition", None)
    diagnostics = composition.diagnostics() if composition is not None else None
    improvement = _improvement_runtime(composition)
    bounded_limit = max(1, min(int(limit), 100))
    items = improvement.query_candidates(offset=max(0, int(offset)), limit=bounded_limit, finding_type=finding_type, domain=domain) if improvement else ()
    latest = next(reversed(improvement.snapshots.values()), None) if improvement and improvement.snapshots else None
    return {
        "mode": "READ_ONLY",
        "research_only": True,
        "schema_version": "1.0",
        "runtime_version": RESEARCH_IMPROVEMENT_RUNTIME_VERSION,
        "policy_identity": research_improvement_policy_identity(),
        "schemas": {
            "improvement_candidate": improvement_candidate_schema_identity(),
            "failure_cluster": research_failure_cluster_schema_identity(),
            "improvement_snapshot": research_improvement_snapshot_schema_identity(),
        },
        "authority": {
            "input_boundary": "P47 evidence + P48 attribution/snapshot",
            "automatic_change": False,
            "validation_required": True,
            "configuration_mutation_available": False,
            "strategy_mutation_available": False,
            "financial_authorization": "NONE",
        },
        "components": research_improvement_components_from_inventory(tuple(diagnostics["components"])) if diagnostics else {},
        "runtime_health": improvement.diagnostics() if improvement else None,
        "as_of": latest.analysis_as_of.isoformat() if latest else None,
        "candidate_count": len(improvement.candidates) if improvement else 0,
        "finding_distribution": dict(latest.finding_distribution) if latest else {},
        "domain_distribution": dict(latest.domain_distribution) if latest else {},
        "evidence_strength_distribution": dict(latest.evidence_strength_distribution) if latest else {},
        "investigation_priority_distribution": dict(latest.investigation_priority_distribution) if latest else {},
        "offset": max(0, int(offset)),
        "limit": bounded_limit,
        "items": [_candidate_payload(item) for item in items],
        "warnings": list(latest.warnings) if latest else ["P49_NO_IMPROVEMENT_SNAPSHOT_PUBLISHED"],
        "limitations": list(latest.limitations) if latest else ["NoImprovementCandidate != RuntimeFailure."],
        "financial_execution": "NONE",
    }


def build_research_improvement_detail(runtime: Any, candidate_id: str) -> dict[str, Any]:
    improvement = _improvement_runtime(getattr(runtime, "composition", None))
    if improvement is None:
        return {"mode": "READ_ONLY", "available": False, "reason": "P49_RUNTIME_UNAVAILABLE", "financial_execution": "NONE"}
    try:
        candidate = improvement.get_candidate(candidate_id)
    except KeyError:
        return {"mode": "READ_ONLY", "available": False, "reason": "P49_CANDIDATE_NOT_FOUND", "candidate_id": candidate_id, "financial_execution": "NONE"}
    payload = _candidate_payload(candidate)
    payload.update(
        {
            "finding_detail": candidate.finding_detail,
            "supporting_evidence_refs": list(candidate.supporting_evidence_refs),
            "contradicting_evidence_refs": list(candidate.contradicting_evidence_refs),
            "limitations": list(candidate.limitations),
            "confounders": list(candidate.confounders),
            "warnings": list(candidate.warnings),
            "proposed_hypothesis": dict(candidate.proposed_hypothesis),
            "automatic_change": candidate.automatic_change,
            "validation_required": candidate.validation_required,
        }
    )
    return {"mode": "READ_ONLY", "available": True, "candidate": payload, "financial_execution": "NONE"}


def _improvement_runtime(composition: Any) -> Any | None:
    if composition is None:
        return None
    try:
        component = composition.get("research_improvement_snapshot").component
    except Exception:
        return None
    return getattr(component, "runtime", None)


def _candidate_payload(candidate: Any) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "finding_type": candidate.finding_type,
        "finding_domain": candidate.finding_domain,
        "finding_summary": candidate.finding_summary,
        "evidence_count": candidate.evidence_count,
        "independent_window_count": candidate.independent_window_count,
        "evidence_strength": candidate.evidence_strength,
        "confidence_classification": candidate.confidence_classification,
        "effect_direction": candidate.effect_direction,
        "effect_magnitude": str(candidate.effect_magnitude) if candidate.effect_magnitude is not None else None,
        "recommended_investigation": candidate.recommended_investigation,
        "investigation_priority": candidate.investigation_priority,
        "candidate_status": candidate.candidate_status,
        "automatic_change": candidate.automatic_change,
        "validation_required": candidate.validation_required,
        "candidate_fingerprint": candidate.candidate_fingerprint,
    }
