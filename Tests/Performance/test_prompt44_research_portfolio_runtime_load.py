from dataclasses import replace
from time import perf_counter

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.portfolio.research_portfolio_runtime import (
    CandidatePortfolioContext,
    ResearchPortfolioRuntime,
    ResearchPortfolioRuntimeConfiguration,
)
from amrte.strategies.framework import SignalDirection
from amrte.strategies.research_scoring_runtime import ResearchScoringRuntime
from Tests.Unit.test_events import NOW
from Tests.Unit.test_strategy_evaluation_runtime import runtime_with, unified_snapshot
from Tests.Unit.test_strategy_framework import TestStrategy, intelligence


def _contexts(p42, evaluation_set, assessment, index):
    candidate_by_id = {item.candidate_id: item for item in evaluation_set.candidates}
    metadata_by_strategy = {
        strategy.metadata.identity.strategy_id: strategy.metadata
        for strategy in p42.registry.all()
    }
    out = []
    for offset, scored in enumerate(assessment.scored_candidates):
        candidate = candidate_by_id[scored.candidate_id]
        metadata = metadata_by_strategy[scored.strategy_id]
        out.append(
            CandidatePortfolioContext.create(
                candidate_id=scored.candidate_id,
                scored_candidate_id=scored.scored_candidate_id,
                instrument_id=f"FICTIONAL_{index}_{offset}",
                strategy_id=scored.strategy_id,
                strategy_version=scored.strategy_version,
                strategy_family=metadata.identity.family.name,
                strategy_variant=None,
                research_direction=candidate.research_direction,
                dataset_id=candidate.dataset_id,
                dataset_fingerprint=candidate.dataset_fingerprint,
                timeframe=candidate.timeframe,
                market_intelligence_snapshot_id=candidate.market_intelligence_snapshot_id,
                knowledge_cutoff_utc=assessment.knowledge_cutoff_utc,
                configuration_identity=assessment.configuration_identity,
                recovery_epoch=assessment.recovery_epoch,
            )
        )
    return tuple(out)


def test_prompt44_research_portfolio_runtime_is_bounded_under_synthetic_load():
    p42 = runtime_with(
        TestStrategy("A", direction=SignalDirection.LONG_BIAS),
        TestStrategy("B", direction=SignalDirection.SHORT_BIAS),
        TestStrategy("C", direction=SignalDirection.LONG_BIAS),
    )
    p43 = ResearchScoringRuntime(
        clock=FixedClock(NOW),
        audit=InMemoryAuditSink(),
        registry=p42.registry,
    )
    runtime = ResearchPortfolioRuntime(
        ResearchPortfolioRuntimeConfiguration(
            maximum_candidate_risk_assessments=12,
            maximum_correlation_snapshots=5,
            maximum_snapshots=5,
            maximum_conflicts=12,
        ),
        clock=FixedClock(NOW),
        audit=InMemoryAuditSink(),
    )

    started = perf_counter()
    for index in range(20):
        intel = replace(
            intelligence(),
            market_intelligence_snapshot_id=f"P44-LOAD-{index}",
        )
        snapshot = unified_snapshot(intel)
        evaluation_set = p42.evaluate_unified_snapshot(snapshot).evaluation_set
        assessment = p43.assess(evaluation_set, snapshot.market_intelligence).assessment
        runtime.assess(assessment, _contexts(p42, evaluation_set, assessment, index))
    elapsed = perf_counter() - started

    assert runtime.metrics["p43_assessments_received"] == 20
    assert runtime.metrics["candidates_risk_assessed"] == 60
    assert len(runtime.candidate_risk) <= 12
    assert len(runtime.correlation_snapshots) <= 5
    assert len(runtime.snapshots) <= 5
    assert len(runtime.conflicts) <= 12
    assert elapsed < 5.0
