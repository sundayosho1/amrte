from dataclasses import replace
from time import perf_counter

from Tests.Unit.test_strategy_evaluation_runtime import runtime_with, unified_snapshot
from Tests.Unit.test_strategy_framework import TestStrategy, intelligence
from amrte.strategies.evaluation_runtime import StrategyEvaluationRuntimeAcceptance


def test_prompt42_bounded_strategy_evaluation_soak():
    runtime = runtime_with(*(TestStrategy(f"S{i}") for i in range(4)))
    base = intelligence()

    began = perf_counter()
    accepted = 0
    candidates = 0
    for index in range(80):
        snapshot = unified_snapshot(replace(base, market_intelligence_snapshot_id=f"P42-{index}"))
        result = runtime.evaluate_unified_snapshot(snapshot)
        accepted += result.acceptance is StrategyEvaluationRuntimeAcceptance.ACCEPTED
        candidates += len(result.evaluation_set.candidates)
    elapsed = perf_counter() - began

    assert accepted == 80
    assert candidates == 320
    assert runtime.diagnostics()["evaluation_set_count"] == 80
    assert runtime.diagnostics()["candidate_count"] == 320
    assert elapsed < 5.0
