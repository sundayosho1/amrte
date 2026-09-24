from dataclasses import replace

from amrte.market.intelligence import IntelligenceAvailability,IntelligenceHealth
from amrte.strategies.framework import *
from Tests.Unit.test_strategy_framework import TestStrategy,intelligence,orchestrator


def test_phase2_snapshot_is_only_authoritative_input_and_lineage_is_preserved():
    strategy=TestStrategy();engine,_=orchestrator(strategy);intel=intelligence();result=engine.evaluate(strategy,intel)
    assert result.candidate.market_intelligence_snapshot_id==intel.market_intelligence_snapshot_id
    assert result.research_signal.market_intelligence_snapshot_id==intel.market_intelligence_snapshot_id
    assert result.candidate.configuration_snapshot_id==intel.configuration_snapshot_id


def test_no_action_is_valid_success_not_error():
    strategy=TestStrategy(detect=DetectionState.NOT_DETECTED);engine,_=orchestrator(strategy);result=engine.evaluate(strategy,intelligence())
    assert result.outcome is EvaluationOutcome.NO_ACTION and result.strategy_health is StrategyHealth.HEALTHY
    assert result.decision_trace.outcome.name=="NO_ACTION"


def test_upstream_restrictions_are_monotonic():
    strategy=TestStrategy();engine,_=orchestrator(strategy);intel=intelligence()
    blocked=replace(intel,overall_intelligence_health=IntelligenceHealth.UNAVAILABLE,intelligence_availability=IntelligenceAvailability.NOT_AVAILABLE,restrictions=("NEWS_BLOCK",))
    result=engine.evaluate(strategy,blocked)
    assert result.final_action is FinalResearchAction.BLOCKED and "NEWS_BLOCK" in result.applicability.restrictions
