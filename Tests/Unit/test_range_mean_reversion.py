from dataclasses import FrozenInstanceError,replace
from types import MappingProxyType

import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.regime import PrimaryRegime
from amrte.market.structure import *
from amrte.strategies.framework import *
from amrte.strategies.range_mean_reversion import *
from amrte.strategies.scoring import CentralSignalScorer
from Tests.Unit.test_events import NOW
from Tests.Unit.test_strategy_framework import intelligence,orchestrator
from Tests.Unit.test_trend_pullback import with_features

def ranged_intel(position,*,displacement=0.2,rsi=50,identity="S3",regime=PrimaryRegime.RANGE,breakout=False,two_sided=True,width=2.0):
    x=with_features(intelligence(),execution_displacement=displacement,identity=identity,extra=(("strategy","BOLLINGER_PERCENT_B",position),("strategy","RSI",rsi),("strategy","RANGE_ATR",width),("strategy","BOLLINGER_BANDWIDTH",.02)))
    support=StructuralZone(f"SUP-{identity}",x.instrument_id,"H1",ZoneType.SUPPORT,99,100,NOW,NOW,NOW,2,ZoneState.TESTED,1,90,(),(),x.dataset_id)
    resistance=StructuralZone(f"RES-{identity}",x.instrument_id,"H1",ZoneType.RESISTANCE,110,111,NOW,NOW,NOW,2,ZoneState.TESTED,1,90,(),(),x.dataset_id)
    zones=(support,resistance) if two_sided else (support,)
    con=ConsolidationResult(ConsolidationState.CONSOLIDATING,100,110,10,NOW,NOW,90,("TWO_SIDED",))
    breaks=()
    if breakout:breaks=(StructuralBreak(f"BR-{identity}",x.instrument_id,"H1",BreakDirection.BULLISH_BOS,"SW",110,"BAR",NOW,111,1,BreakConfirmation.CLOSE_BREAK,True,1,90,x.dataset_id,x.market_data_snapshot_id),)
    side=lambda tf:replace(tf,direction=StructuralDirection.SIDEWAYS,consolidation=con,zones=zones,breaks=breaks)
    structure=replace(x.structure,context_structure=side(x.structure.context_structure),strategy_structure=side(x.structure.strategy_structure),execution_structure=side(x.structure.execution_structure),alignment=Alignment.NEUTRAL)
    rg=replace(x.regime,primary_regime=regime,source_structure_snapshot_id=structure.structure_snapshot_id)
    return replace(x,structure=structure,regime=rg,market_intelligence_snapshot_id=f"INTEL-{identity}")

def components(config=S3Configuration()):
    audit=InMemoryAuditSink();strategy=RangeMeanReversionStrategy(config,audit);scorer=CentralSignalScorer(audit=audit,strategy_families={S3_STRATEGY_ID:StrategyFamily.MEAN_REVERSION});engine,_=orchestrator(strategy,scorer=scorer);return strategy,engine,audit

def sequence(*,upper=False,config=S3Configuration()):
    strategy,engine,audit=components(config);extreme=1.05 if upper else -.05;inside=.75 if upper else .25;disp=-.4 if upper else .4
    first=engine.evaluate(strategy,ranged_intel(extreme,displacement=disp,identity="EXT-U" if upper else "EXT-L"));second=engine.evaluate(strategy,ranged_intel(inside,displacement=disp,identity="IN-U" if upper else "IN-L"));return strategy,first,second,audit

def test_registration_identity_family_and_framework_integration():
    registry=StrategyRegistry();s=register_s3(registry);assert registry.get(S3_STRATEGY_ID) is s and s.metadata.identity.family is StrategyFamily.MEAN_REVERSION

def test_configuration_timeframes_and_validation():
    assert RangeMeanReversionStrategy(S3Configuration(context_timeframe="D1",range_timeframe="H4",confirmation_timeframe="H1")).metadata.required_timeframes==("D1","H4","H1")
    with pytest.raises(ValueError,match="S3_INVALID_TIMEFRAME_ROLES"):RangeMeanReversionStrategy(S3Configuration(context_timeframe="H1"))
    with pytest.raises(ValueError,match="S3_INVALID_RANGE_WIDTH"):RangeMeanReversionStrategy(S3Configuration(minimum_normalized_width=9,maximum_normalized_width=8))
    with pytest.raises(ValueError,match="S3_INVALID_EXTREMES"):RangeMeanReversionStrategy(S3Configuration(lower_extreme=.6))

@pytest.mark.parametrize("regime,state",[(PrimaryRegime.RANGE,ApplicabilityState.APPLICABLE),(PrimaryRegime.TRANSITION,ApplicabilityState.CONDITIONAL),(PrimaryRegime.TREND,ApplicabilityState.BLOCKED),(PrimaryRegime.BREAKOUT_EXPANSION,ApplicabilityState.BLOCKED),(PrimaryRegime.ABNORMAL,ApplicabilityState.BLOCKED),(PrimaryRegime.UNKNOWN,ApplicabilityState.BLOCKED)])
def test_regime_applicability_and_hard_precedence(regime,state):
    s,e,_=components();r=e.evaluate(s,ranged_intel(0,regime=regime,identity=regime.name));assert r.applicability.state is state and (r.research_signal is None if state is ApplicabilityState.BLOCKED else True)

def test_strong_trend_and_confirmed_breakout_block():
    s,e,_=components();x=ranged_intel(0);structure=replace(x.structure,context_structure=replace(x.structure.context_structure,direction=StructuralDirection.BULLISH),strategy_structure=replace(x.structure.strategy_structure,direction=StructuralDirection.BULLISH));x=replace(x,structure=structure,market_intelligence_snapshot_id="TREND")
    assert e.evaluate(s,x).applicability.state is ApplicabilityState.BLOCKED
    s,e,_=components();assert e.evaluate(s,ranged_intel(0,breakout=True,identity="BREAK")).applicability.state is ApplicabilityState.BLOCKED

def test_range_identity_maturity_boundaries_mean_and_immutability():
    s,e,_=components();e.evaluate(s,ranged_intel(0,identity="RANGE"));r=s.range_history[-1]
    assert r.range_state is RangeState.MATURE and r.lower_boundary_tests==2 and r.upper_boundary_tests==2 and r.mean_reference.reference_value==105
    again,_,_=components();e2=orchestrator(again,scorer=CentralSignalScorer(strategy_families={S3_STRATEGY_ID:StrategyFamily.MEAN_REVERSION}))[0];e2.evaluate(again,ranged_intel(0,identity="RANGE"));assert again.range_history[-1].range_id==r.range_id
    with pytest.raises(FrozenInstanceError):r.range_state=RangeState.BROKEN

def test_two_sided_width_and_missing_position_fail_closed():
    for x in (ranged_intel(0,two_sided=False,identity="ONE"),ranged_intel(0,width=.1,identity="NARROW")):
        s,e,_=components();assert e.evaluate(s,x).research_signal is None and s.range_history[-1].range_state is RangeState.FORMING
    x=ranged_intel(0);features={k:dict(v) for k,v in x.features.features.items()};features["strategy"]={k:v for k,v in features["strategy"].items() if not k.startswith("BOLLINGER_PERCENT_B:")};x=replace(x,features=replace(x.features,features=features),market_intelligence_snapshot_id="MISSING")
    s,e,_=components();result=e.evaluate(s,x);assert result.detection is None or result.detection.status is DetectionState.INCOMPLETE

@pytest.mark.parametrize("upper,direction",[(False,SignalDirection.LONG_BIAS),(True,SignalDirection.SHORT_BIAS)])
def test_bullish_bearish_extreme_rejection_reentry_reversion_symmetry(upper,direction):
    s,first,second,_=sequence(upper=upper);assert first.research_signal is None and second.research_signal is not None and second.candidate.direction is direction
    setup=next(iter(s._setups.values()));assert setup.rejection_state is RejectionState.CONFIRMED and setup.reentry_state is ReentryState.REENTERED_RANGE

def test_rsi_or_bollinger_extreme_alone_never_creates_candidate():
    s,e,_=components();one=e.evaluate(s,ranged_intel(-.05,rsi=5,identity="ONLY"));assert one.research_signal is None and one.detection.status is DetectionState.NOT_DETECTED

def test_reentry_without_toward_mean_momentum_is_no_action():
    s,e,_=components();e.evaluate(s,ranged_intel(-.05,identity="E"));r=e.evaluate(s,ranged_intel(.25,displacement=-.4,identity="WRONG"));assert r.research_signal is None and r.detection.status is DetectionState.NOT_DETECTED

def test_excessive_excursion_and_breakout_are_blocked():
    s,e,_=components();assert e.evaluate(s,ranged_intel(-.5,identity="EXCESS")).detection.status is DetectionState.BLOCKED

def test_destination_is_immutable_research_metadata_not_take_profit():
    s,_,result,_=sequence();d=next(iter(s.destinations.values()));assert d.reference_value==105 and d.destination_type is DestinationType.RANGE_MEAN
    assert not any(hasattr(d,x) for x in ("take_profit","place_order","execute"))
    with pytest.raises(FrozenInstanceError):d.reference_value=999

def test_prompt12_scoring_candidate_lineage_duplicate_determinism():
    s,_,r,_=sequence();assert r.score.scoring_model_id.endswith("MEAN_REVERSION_RESEARCH_SCORE") and r.candidate.market_intelligence_snapshot_id=="INTEL-IN-L"
    other,_,r2,_=sequence();assert r.candidate.logical_signal_id==r2.candidate.logical_signal_id and next(iter(s.destinations))==next(iter(other.destinations))

def test_recovery_observability_bounded_history_and_safety_surface():
    s,_,r,a=sequence(config=S3Configuration(maximum_history=1));state=s.recovery_state();assert s.validate_recovery(state) and not s.validate_recovery({"s3_engine_version":"OLD"}) and len(s.range_history)==1
    assert {name for name,_ in a.events}>={"s3_evaluation_started","s3_extreme_detected","s3_reversion_confirmed","scoring_completed"}
    forbidden={"place_order","submit_order","size_position","set_stop_loss","set_take_profit","close_position","broker_login"};assert forbidden.isdisjoint(set(dir(RangeMeanReversionStrategy)))

def test_instrument_strategy_and_state_isolation():
    s,e,_=components();e.evaluate(s,ranged_intel(-.05,identity="A"));x=ranged_intel(-.05,identity="B");x=replace(x,instrument_id="FICTIONAL_BETA",market_intelligence_snapshot_id="BETA")
    context=StrategyEvaluationContext("BETA-EVAL",S3_STRATEGY_ID,"FICTIONAL_BETA",x.as_of_timestamp_utc,x,x.configuration_snapshot_id,None,EvaluationReason.NEW_BAR,x.recovery_epoch);s.detect(context);assert len(s._setups)==2
    assert not hasattr(s,"arbitrate") and not hasattr(s,"execute")
