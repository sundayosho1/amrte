from dataclasses import replace
from time import perf_counter

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.strategies.framework import SignalDirection
from amrte.strategies.research_scoring_runtime import (
    ResearchScoringRuntime,
    ResearchScoringRuntimeConfiguration,
)
from Tests.Unit.test_events import NOW
from Tests.Unit.test_strategy_evaluation_runtime import runtime_with, unified_snapshot
from Tests.Unit.test_strategy_framework import TestStrategy, intelligence


def test_prompt43_scoring_runtime_is_bounded_under_synthetic_load():
    p42 = runtime_with(
        TestStrategy("A", direction=SignalDirection.LONG_BIAS),
        TestStrategy("B", direction=SignalDirection.SHORT_BIAS),
        TestStrategy("C", direction=SignalDirection.LONG_BIAS),
    )
    runtime = ResearchScoringRuntime(
        ResearchScoringRuntimeConfiguration(maximum_scored_candidates=12, maximum_assessments=5),
        clock=FixedClock(NOW),
        audit=InMemoryAuditSink(),
        registry=p42.registry,
    )

    started = perf_counter()
    for index in range(20):
        intel = replace(
            intelligence(),
            market_intelligence_snapshot_id=f"P43-LOAD-{index}",
        )
        snapshot = unified_snapshot(intel)
        evaluation_set = p42.evaluate_unified_snapshot(snapshot).evaluation_set
        runtime.assess(evaluation_set, snapshot.market_intelligence)
    elapsed = perf_counter() - started

    assert runtime.metrics["evaluation_sets_received"] == 20
    assert runtime.metrics["candidates_scored"] == 60
    assert len(runtime.scored_candidates) <= 12
    assert len(runtime.assessments) <= 5
    assert elapsed < 5.0
