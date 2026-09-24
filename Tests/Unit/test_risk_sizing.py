from dataclasses import FrozenInstanceError,replace
from datetime import timedelta
from decimal import Decimal

import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.risk.sizing import *
from amrte.strategies.strategy_arbitration import *
from Tests.Unit.test_strategy_arbitration import baseline,metadata,opinion_eval
from amrte.strategies.framework import SignalDirection,StrategyFamily

def strategy_snapshot():
    intel,base=baseline();item=opinion_eval(base,"S1",StrategyFamily.TREND,SignalDirection.LONG_BIAS);result=StrategyArbitrationEngine().arbitrate(intel,(item,),{"S1":metadata("S1",StrategyFamily.TREND,("TREND",))});return result.snapshot

def inputs(capital="10000",distance="2",cost=None):
    snap=strategy_snapshot();cap=ResearchCapitalContext.create(capital,snap.as_of_timestamp_utc);dist=InvalidationDistanceContext.create(distance,snap.as_of_timestamp_utc) if distance is not None else None;buf=ResearchCostBuffer.create(cost,snap.as_of_timestamp_utc) if cost is not None else None;return snap,cap,dist,buf

def test_valid_decimal_sizing_budget_quantization_and_identity():
    snap,cap,dist,cost=inputs();engine=RiskSizingEngine();result=engine.size(snap,cap,dist,cost)
    d=result.exposure_decision;assert d.base_risk_amount==Decimal("100.00") and d.raw_simulated_exposure==Decimal("50.00") and d.quantized_simulated_exposure==Decimal("50.00") and d.recalculated_risk<=d.effective_risk_amount
    assert result.risk_budget.base_risk_amount==result.risk_budget.effective_risk_amount and result.decision_trace.outcome is DecisionOutcome.ACCEPTED

@pytest.mark.parametrize("outcome,reason",[(ArbitrationOutcome.NO_ACTION,"RISK_UPSTREAM_NO_ACTION"),(ArbitrationOutcome.ALL_REJECTED,"RISK_UPSTREAM_NO_ACTION"),(ArbitrationOutcome.BLOCKED,"RISK_UPSTREAM_BLOCKED"),(ArbitrationOutcome.UNKNOWN,"RISK_UPSTREAM_BLOCKED")])
def test_upstream_outcomes_fail_closed(outcome,reason):
    snap,cap,dist,_=inputs();snap=replace(snap,outcome=outcome,research_availability=ResearchAvailability.NO_ACTION if outcome is ArbitrationOutcome.NO_ACTION else ResearchAvailability.NOT_AVAILABLE,snapshot_id=f"{snap.snapshot_id}-{outcome.name}");d=RiskSizingEngine().size(snap,cap,dist).exposure_decision;assert d.quantized_simulated_exposure==0 and reason in d.reason_codes

def test_multiple_compatible_default_blocks_full_budget_duplication():
    snap,cap,dist,_=inputs();snap=replace(snap,outcome=ArbitrationOutcome.MULTIPLE_COMPATIBLE,snapshot_id="MULTI");d=RiskSizingEngine().size(snap,cap,dist).exposure_decision;assert d.eligibility is SizingEligibility.BLOCKED and d.quantized_simulated_exposure==0

@pytest.mark.parametrize("distance,reason",[(None,"RISK_INVALIDATION_MISSING"),("0","RISK_INVALIDATION_ZERO"),("0.01","RISK_INVALIDATION_TOO_SMALL"),("11","RISK_INVALIDATION_TOO_LARGE"),("-1","RISK_INVALIDATION_ZERO")])
def test_missing_zero_near_zero_excessive_negative_distance(distance,reason):
    snap,cap,dist,_=inputs(distance=distance);d=RiskSizingEngine().size(snap,cap,dist).exposure_decision;assert d.quantized_simulated_exposure==0 and reason in d.reason_codes

def test_zero_risk_and_zero_capital_are_valid_no_action():
    snap,cap,dist,_=inputs(capital="0");d=RiskSizingEngine().size(snap,cap,dist).exposure_decision;assert d.quantized_simulated_exposure==0
    snap,cap,dist,_=inputs();d=RiskSizingEngine(RiskSizingConfiguration(base_risk_fraction=Decimal("0"))).size(snap,cap,dist).exposure_decision;assert d.quantized_simulated_exposure==0

def test_negative_nonfinite_and_invalid_configuration_rejected():
    with pytest.raises(ValueError,match="RISK_NEGATIVE_CAPITAL"):RiskSizingEngine(RiskSizingConfiguration(default_research_capital=Decimal("-1")))
    with pytest.raises(ValueError,match="RISK_INVALID_FRACTION"):RiskSizingEngine(RiskSizingConfiguration(base_risk_fraction=Decimal("1.1")))
    with pytest.raises(ValueError,match="RISK_INVALID_EXPOSURE_STEP"):RiskSizingEngine(RiskSizingConfiguration(exposure_step=Decimal("0")))
    with pytest.raises(ValueError,match="RISK_NUMERICAL_INVALID"):ResearchCapitalContext.create("NaN",strategy_snapshot().as_of_timestamp_utc)

def test_cost_buffer_missing_policy_and_conservative_fallback():
    snap,cap,dist,_=inputs();blocked=RiskSizingEngine(RiskSizingConfiguration(cost_buffer_enabled=True,missing_cost_policy=MissingCostPolicy.BLOCK)).size(snap,cap,dist).exposure_decision;assert "RISK_COST_UNKNOWN" in blocked.reason_codes
    cfg=RiskSizingConfiguration(cost_buffer_enabled=True,missing_cost_policy=MissingCostPolicy.USE_CONFIGURED_CONSERVATIVE_BUFFER,conservative_cost_buffer=Decimal("10"));d=RiskSizingEngine(cfg).size(snap,cap,dist).exposure_decision;assert d.cost_buffer==10 and d.usable_risk_amount==90

def test_maximum_cap_minimum_rejection_and_floor_quantization():
    snap,cap,dist,_=inputs(distance="0.5");d=RiskSizingEngine(RiskSizingConfiguration(maximum_exposure=Decimal("10"),exposure_step=Decimal("3"))).size(snap,cap,dist).exposure_decision;assert d.raw_simulated_exposure==200 and d.quantized_simulated_exposure==9 and "RISK_EXPOSURE_CAPPED" in d.reason_codes
    d=RiskSizingEngine(RiskSizingConfiguration(minimum_exposure=Decimal("60"))).size(*inputs()[:3]).exposure_decision;assert d.quantized_simulated_exposure==0

def test_modifiers_only_reduce_never_amplify_and_compose_conservatively():
    snap,cap,dist,_=inputs();mods=(RiskModifier("A",Decimal("0.75"),"TEST","REDUCE",snap.as_of_timestamp_utc),RiskModifier("B",Decimal("0.5"),"TEST","REDUCE",snap.as_of_timestamp_utc));d=RiskSizingEngine().size(snap,cap,dist,modifiers=mods).exposure_decision;assert d.effective_risk_fraction==Decimal("0.005") and d.effective_risk_amount<=d.base_risk_amount
    with pytest.raises(ValueError,match="RISK_MODIFIER_MAY_NOT_AMPLIFY"):RiskModifier("BAD",Decimal("1.1"),"TEST","BAD",snap.as_of_timestamp_utc)

def test_temporal_safety_future_capital_distance_cost_and_modifier():
    snap,cap,dist,_=inputs();future=snap.as_of_timestamp_utc+timedelta(minutes=1)
    assert "RISK_FUTURE_CAPITAL" in RiskSizingEngine().size(snap,replace(cap,available_at_utc=future),dist).exposure_decision.reason_codes
    assert "RISK_FUTURE_INVALIDATION" in RiskSizingEngine().size(snap,cap,replace(dist,available_at_utc=future)).exposure_decision.reason_codes
    cfg=RiskSizingConfiguration(cost_buffer_enabled=True);cost=ResearchCostBuffer.create("1",snap.as_of_timestamp_utc);assert "RISK_FUTURE_COST" in RiskSizingEngine(cfg).size(snap,cap,dist,replace(cost,available_at_utc=future)).exposure_decision.reason_codes

def test_determinism_cache_immutability_recovery_observability_and_safety_surface():
    snap,cap,dist,_=inputs();audit=InMemoryAuditSink();engine=RiskSizingEngine(RiskSizingConfiguration(maximum_cache_entries=1),audit);a=engine.size(snap,cap,dist);b=engine.size(snap,cap,dist);assert a is b and a.exposure_decision.decision_id==b.exposure_decision.decision_id
    with pytest.raises(FrozenInstanceError):a.exposure_decision.quantized_simulated_exposure=999
    state=engine.recovery_state();assert engine.validate_recovery(state) and not engine.validate_recovery({"risk_engine_version":"OLD"})
    assert {x for x,_ in audit.events}>={"risk_sizing_started","risk_sizing_completed"}
    forbidden={"place_order","submit_order","size_broker_lots","set_stop_loss","set_take_profit","broker_login","margin_required","leverage"};assert forbidden.isdisjoint(set(dir(RiskSizingEngine)))

