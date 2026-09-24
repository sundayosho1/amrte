from dataclasses import FrozenInstanceError,replace
from datetime import timedelta

import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.regime import PrimaryRegime
from amrte.strategies.strategy_arbitration import *
from amrte.strategies.framework import *
from amrte.strategies.trend_pullback import TrendPullbackStrategy,S1Configuration
from Tests.Unit.test_trend_pullback import bullish,evaluate as evaluate_s1

def baseline():
    intel=bullish();_,evaluation,_=evaluate_s1(intel);return intel,evaluation

def metadata(strategy_id,family,native):
    base=TrendPullbackStrategy().metadata
    return replace(base,identity=StrategyIdentity(strategy_id,family,strategy_id,"1.0.0"),allowed_regimes=tuple(native))

def opinion_eval(base,strategy_id,family,direction,*,score=80,confidence=80,quality=80,completeness=100,uncertainty=0,logical=None,health=StrategyHealth.HEALTHY,expires=None):
    sid=f"SCORE-{strategy_id}";cid=f"CAND-{strategy_id}";rid=f"SIGNAL-{strategy_id}";logical=logical or f"LOGICAL-{strategy_id}"
    sc=replace(base.score,signal_score_id=sid,overall_score=score,confidence=confidence,quality=quality,completeness=completeness,uncertainty=uncertainty)
    cand=replace(base.candidate,signal_candidate_id=cid,logical_signal_id=logical,signal_version_id=f"V-{strategy_id}",strategy_id=strategy_id,strategy_family=family,direction=direction,signal_score_id=sid,expires_at_utc=expires or base.candidate.expires_at_utc)
    sig=replace(base.research_signal,research_signal_id=rid,logical_signal_id=logical,signal_version_id=f"V-{strategy_id}",signal_candidate_id=cid,strategy_id=strategy_id,strategy_family=family,direction=direction,score=score,confidence=confidence,quality=quality)
    qual=replace(base.qualification,strategy_id=strategy_id)
    return replace(base,strategy_id=strategy_id,score=sc,candidate=cand,research_signal=sig,qualification=qual,strategy_health=health)

def engine(config=ArbitrationConfiguration()):return StrategyArbitrationEngine(config,InMemoryAuditSink())

def test_configuration_registry_and_validation():
    with pytest.raises(ValueError,match="ARB_INVALID_THRESHOLD"):engine(ArbitrationConfiguration(tie_tolerance=101))
    with pytest.raises(ValueError,match="ARB_DUPLICATE_PRIORITY"):engine(ArbitrationConfiguration(strategy_priority=("S1","S1")))
    registry=ArbitrationPolicyRegistry();registry.register("default",ArbitrationPolicy.HYBRID_CONSERVATIVE);assert registry.get("default") is ArbitrationPolicy.HYBRID_CONSERVATIVE
    with pytest.raises(ValueError):registry.register("default",ArbitrationPolicy.REJECT_CONFLICTS)

def test_single_eligible_is_preferred_and_unified_snapshot_created():
    intel,base=baseline();item=opinion_eval(base,"S1",StrategyFamily.TREND,SignalDirection.LONG_BIAS);result=engine().arbitrate(intel,(item,),{"S1":metadata("S1",StrategyFamily.TREND,("TREND",))})
    assert result.decision.outcome is ArbitrationOutcome.SINGLE_PREFERRED and result.snapshot.preferred_research_signal_id=="SIGNAL-S1" and result.snapshot.research_availability is ResearchAvailability.AVAILABLE
    assert len(result.decision_trace.evaluations)==4

def test_empty_and_invalid_inputs_fail_closed():
    intel,base=baseline();assert engine().arbitrate(intel,(),{}).decision.outcome is ArbitrationOutcome.ALL_REJECTED
    bad=opinion_eval(base,"S1",StrategyFamily.TREND,SignalDirection.LONG_BIAS);bad=replace(bad,candidate=replace(bad.candidate,market_intelligence_snapshot_id="OTHER"))
    assert "ARB_INVALID_LINEAGE" in engine().arbitrate(intel,(bad,),{"S1":metadata("S1",StrategyFamily.TREND,("TREND",))}).decision.reason_codes

def test_opposite_direction_conflict_abstains_under_reject_policy():
    intel,base=baseline();a=opinion_eval(base,"S1",StrategyFamily.TREND,SignalDirection.LONG_BIAS);b=opinion_eval(base,"S3",StrategyFamily.MEAN_REVERSION,SignalDirection.SHORT_BIAS)
    result=engine(ArbitrationConfiguration(policy=ArbitrationPolicy.REJECT_CONFLICTS)).arbitrate(intel,(a,b),{"S1":metadata("S1",StrategyFamily.TREND,("TREND",)),"S3":metadata("S3",StrategyFamily.MEAN_REVERSION,("RANGE",))})
    assert result.decision.outcome is ArbitrationOutcome.NO_ACTION and ConflictType.DIRECTIONAL_CONFLICT in result.assessments[0].conflict_types and result.snapshot.overall_strategy_health is StrategySystemHealth.CONFLICTED

def test_regime_native_preference_is_metadata_driven():
    intel,base=baseline();a=opinion_eval(base,"ALPHA",StrategyFamily.TREND,SignalDirection.LONG_BIAS,score=60);b=opinion_eval(base,"BETA",StrategyFamily.MEAN_REVERSION,SignalDirection.SHORT_BIAS,score=99)
    result=engine().arbitrate(intel,(a,b),{"ALPHA":metadata("ALPHA",StrategyFamily.TREND,("TREND",)),"BETA":metadata("BETA",StrategyFamily.MEAN_REVERSION,("RANGE",))})
    selected=next(o for o in result.group.opinions if o.opinion_id==result.decision.preferred_opinion_id);assert selected.strategy_id=="ALPHA"

def test_same_direction_explicit_pair_can_coexist():
    intel,base=baseline();a=opinion_eval(base,"S1",StrategyFamily.TREND,SignalDirection.LONG_BIAS);b=opinion_eval(base,"S2",StrategyFamily.BREAKOUT,SignalDirection.LONG_BIAS,score=75)
    cfg=ArbitrationConfiguration(combination_mode=CombinationMode.ALLOW_EXPLICIT_PAIRS_ONLY,allowed_pairs=(("S1","S2"),))
    result=engine(cfg).arbitrate(intel,(a,b),{"S1":metadata("S1",StrategyFamily.TREND,("TREND",)),"S2":metadata("S2",StrategyFamily.BREAKOUT,("BREAKOUT_EXPANSION","TREND"))});assert result.decision.outcome is ArbitrationOutcome.MULTIPLE_COMPATIBLE and len(result.snapshot.permitted_research_signal_ids)==2

def test_same_direction_is_not_automatically_compatible():
    intel,base=baseline();a=opinion_eval(base,"S1",StrategyFamily.TREND,SignalDirection.LONG_BIAS);b=opinion_eval(base,"S2",StrategyFamily.BREAKOUT,SignalDirection.LONG_BIAS)
    result=engine().arbitrate(intel,(a,b),{"S1":metadata("S1",StrategyFamily.TREND,("TREND",)),"S2":metadata("S2",StrategyFamily.BREAKOUT,("TREND",))});assert result.decision.outcome is ArbitrationOutcome.NO_ACTION

def test_breakout_range_thesis_conflict_even_same_direction():
    intel,base=baseline();a=opinion_eval(base,"S2",StrategyFamily.BREAKOUT,SignalDirection.LONG_BIAS);b=opinion_eval(base,"S3",StrategyFamily.MEAN_REVERSION,SignalDirection.LONG_BIAS)
    result=engine().arbitrate(intel,(a,b),{"S2":metadata("S2",StrategyFamily.BREAKOUT,("BREAKOUT_EXPANSION",)),"S3":metadata("S3",StrategyFamily.MEAN_REVERSION,("RANGE",))});assert ConflictType.THESIS_CONFLICT in result.assessments[0].conflict_types

def test_duplicate_hypothesis_detected_without_vote_inflation():
    intel,base=baseline();a=opinion_eval(base,"S2_A",StrategyFamily.BREAKOUT,SignalDirection.LONG_BIAS,logical="SHARED");b=opinion_eval(base,"S2_B",StrategyFamily.BREAKOUT,SignalDirection.LONG_BIAS,logical="SHARED")
    b=replace(b,candidate=replace(b.candidate,signal_candidate_id=a.candidate.signal_candidate_id),research_signal=replace(b.research_signal,signal_candidate_id=a.candidate.signal_candidate_id))
    result=engine().arbitrate(intel,(a,b),{"S2_A":metadata("S2_A",StrategyFamily.BREAKOUT,("TREND",)),"S2_B":metadata("S2_B",StrategyFamily.BREAKOUT,("TREND",))});assert result.assessments[0].compatibility is CompatibilityState.DUPLICATE and result.decision.outcome is ArbitrationOutcome.NO_ACTION

def test_quality_confidence_threshold_and_tie_handling():
    intel,base=baseline();m={"A":metadata("A",StrategyFamily.CUSTOM,("TREND",)),"B":metadata("B",StrategyFamily.CUSTOM,("TREND",))}
    a=opinion_eval(base,"A",StrategyFamily.CUSTOM,SignalDirection.LONG_BIAS,quality=95,score=95);b=opinion_eval(base,"B",StrategyFamily.CUSTOM,SignalDirection.LONG_BIAS,quality=70,score=70)
    assert engine(ArbitrationConfiguration(policy=ArbitrationPolicy.QUALITY_PRIORITY,combination_mode=CombinationMode.ALLOW_NONE)).arbitrate(intel,(a,b),m).decision.outcome is ArbitrationOutcome.SINGLE_PREFERRED
    tied=replace(b,score=replace(b.score,overall_score=95,quality=95),research_signal=replace(b.research_signal,score=95,quality=95));assert engine(ArbitrationConfiguration(regime_native_priority=False,combination_mode=CombinationMode.ALLOW_NONE)).arbitrate(intel,(a,tied),m).decision.outcome is ArbitrationOutcome.NO_ACTION

@pytest.mark.parametrize("field,value,reason",[("health",StrategyHealth.INVALID,"ARB_STRATEGY_UNHEALTHY"),("expires",True,"ARB_EXPIRED_SIGNAL"),("uncertainty",99,"ARB_INCOMPLETE_EVIDENCE"),("completeness",10,"ARB_INCOMPLETE_EVIDENCE")])
def test_health_expiration_completeness_uncertainty_filters(field,value,reason):
    intel,base=baseline();kwargs={}
    if field=="health":kwargs["health"]=value
    elif field=="expires":kwargs["expires"]=intel.as_of_timestamp_utc-timedelta(minutes=1)
    else:kwargs[field]=value
    item=opinion_eval(base,"S1",StrategyFamily.TREND,SignalDirection.LONG_BIAS,**kwargs);result=engine().arbitrate(intel,(item,),{"S1":metadata("S1",StrategyFamily.TREND,("TREND",))});assert reason in result.decision.reason_codes

def test_order_independence_and_deterministic_identity():
    intel,base=baseline();a=opinion_eval(base,"A",StrategyFamily.CUSTOM,SignalDirection.LONG_BIAS);b=opinion_eval(base,"B",StrategyFamily.CUSTOM,SignalDirection.SHORT_BIAS);m={"A":metadata("A",StrategyFamily.CUSTOM,("TREND",)),"B":metadata("B",StrategyFamily.CUSTOM,("TREND",))}
    x=engine().arbitrate(intel,(a,b),m);y=engine().arbitrate(intel,(b,a),m);assert x.group.arbitration_group_id==y.group.arbitration_group_id and x.decision.decision_id==y.decision.decision_id

def test_cache_reuses_immutable_group_and_is_bounded():
    intel,base=baseline();item=opinion_eval(base,"S1",StrategyFamily.TREND,SignalDirection.LONG_BIAS);arb=engine(ArbitrationConfiguration(maximum_cache_entries=1));m={"S1":metadata("S1",StrategyFamily.TREND,("TREND",))}
    first=arb.arbitrate(intel,(item,),m);second=arb.arbitrate(intel,(item,),m);assert first is second and len(arb._cache)==1

def test_immutability_recovery_bounded_history_observability_and_safety():
    intel,base=baseline();audit=InMemoryAuditSink();arb=StrategyArbitrationEngine(ArbitrationConfiguration(maximum_groups=1,maximum_decisions=1),audit);item=opinion_eval(base,"S1",StrategyFamily.TREND,SignalDirection.LONG_BIAS);result=arb.arbitrate(intel,(item,),{"S1":metadata("S1",StrategyFamily.TREND,("TREND",))})
    with pytest.raises(FrozenInstanceError):result.decision.outcome=ArbitrationOutcome.BLOCKED
    state=arb.recovery_state();assert arb.validate_recovery(state) and not arb.validate_recovery({"arbitration_engine_version":"OLD"}) and len(arb._groups)==1
    assert {x for x,_ in audit.events}>={"arbitration_started","strategy_opinion_accepted","arbitration_completed"}
    forbidden={"place_order","submit_order","size_position","set_stop_loss","set_take_profit","close_position","broker_login"};assert forbidden.isdisjoint(set(dir(StrategyArbitrationEngine)))
