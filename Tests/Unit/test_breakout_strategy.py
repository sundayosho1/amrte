from dataclasses import FrozenInstanceError,replace

import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.regime import *
from amrte.market.structure import *
from amrte.strategies.breakout_volatility import *
from amrte.strategies.framework import *
from amrte.strategies.scoring import CentralSignalScorer
from Tests.Unit.test_events import NOW
from Tests.Unit.test_strategy_framework import intelligence,orchestrator
from Tests.Unit.test_temporal_features_compression import series,snapshots
from Tests.Unit.test_trend_pullback import with_features


def compression():
    _,temporal=series(snapshots());return HistoricalCompressionAnalyzer().analyze(temporal)


def breakout_intel(*,bearish=False,wick=False,expansion=1.5,displacement=1.0,compression_state=CompressionState.CONFIRMED,role_flip=False,identity="S2"):
    x=with_features(intelligence(),strategy_displacement=displacement if not bearish else -displacement,execution_displacement=displacement if not bearish else -displacement,volatility=expansion,identity=identity)
    comp=replace(compression(),compression_state=compression_state,compression_score=100 if compression_state is CompressionState.CONFIRMED else 40)
    regime=replace(x.regime,historical_compression=comp,primary_regime=PrimaryRegime.BREAKOUT_EXPANSION)
    direction=BreakDirection.BEARISH_BOS if bearish else BreakDirection.BULLISH_BOS
    event=StructuralBreak(f"BREAK-{identity}",x.instrument_id,"H1",direction,"SWING",100,"BAR",NOW,99 if bearish else 101,1.0,BreakConfirmation.WICK_BREAK if wick else BreakConfirmation.CLOSE_BREAK,True,1.0,90,x.dataset_id,x.market_data_snapshot_id)
    strategy=replace(x.structure.strategy_structure,breaks=(event,))
    execution=x.structure.execution_structure
    if role_flip:
        zone=StructuralZone(f"ZONE-{identity}",x.instrument_id,"M15",ZoneType.RESISTANCE if bearish else ZoneType.SUPPORT,99,101,NOW,NOW,NOW,1,ZoneState.ROLE_FLIPPED,1,90,(),(),x.dataset_id)
        execution=replace(execution,zones=(zone,))
    structure=replace(x.structure,strategy_structure=strategy,execution_structure=execution)
    regime=replace(regime,source_structure_snapshot_id=structure.structure_snapshot_id)
    return replace(x,regime=regime,structure=structure,market_intelligence_snapshot_id=f"INTEL-{identity}")


def evaluate(config=S2Configuration(),intel=None):
    audit=InMemoryAuditSink();strategy=BreakoutVolatilityStrategy(config,audit)
    scorer=CentralSignalScorer(audit=audit,strategy_families={strategy.metadata.identity.strategy_id:StrategyFamily.BREAKOUT})
    engine,_=orchestrator(strategy,scorer=scorer)
    return strategy,engine.evaluate(strategy,intel or breakout_intel()),audit


def test_registration_identity_family_and_variants():
    registry=StrategyRegistry();strategy=register_s2(registry)
    assert registry.get(strategy.metadata.identity.strategy_id) is strategy and strategy.metadata.identity.family is StrategyFamily.BREAKOUT
    assert BreakoutVolatilityStrategy(S2Configuration(variant=S2Variant.RETEST)).metadata.identity.strategy_id.endswith("RETEST")


@pytest.mark.parametrize("variant",list(S2Variant))
def test_variant_configuration_and_prompt12_integration(variant):
    config=S2Configuration(variant=variant);intel=breakout_intel(role_flip=variant is S2Variant.RETEST,identity=variant.name)
    _,result,_=evaluate(config,intel)
    assert result.score is not None and result.score.scoring_model_id.endswith("BREAKOUT_RESEARCH_SCORE")
    assert result.research_signal is not None


def test_both_disabled_and_invalid_configuration_rejected():
    with pytest.raises(ValueError,match="S2_NO_VARIANT_ENABLED"):BreakoutVolatilityStrategy(S2Configuration(immediate_enabled=False,retest_enabled=False))
    with pytest.raises(ValueError,match="S2_INVALID_COMPRESSION_WINDOW"):BreakoutVolatilityStrategy(S2Configuration(minimum_compression_bars=10,maximum_compression_lookback=2))
    with pytest.raises(ValueError,match="S2_INVALID_TIMEFRAME_ROLES"):BreakoutVolatilityStrategy(S2Configuration(context_timeframe="H1"))


@pytest.mark.parametrize("bearish,direction",[(False,SignalDirection.LONG_BIAS),(True,SignalDirection.SHORT_BIAS)])
def test_bullish_bearish_symmetry_and_authoritative_boundary(bearish,direction):
    strategy,result,_=evaluate(intel=breakout_intel(bearish=bearish,identity=str(bearish)))
    assert result.candidate.direction is direction and strategy.breakout_history[-1].boundary_id=="SWING"


@pytest.mark.parametrize("state",[CompressionState.PROBABLE,CompressionState.WEAK,CompressionState.NOT_CONFIRMED,CompressionState.INSUFFICIENT_HISTORY])
def test_strict_compression_required(state):
    _,result,_=evaluate(intel=breakout_intel(compression_state=state,identity=state.name))
    assert result.research_signal is None and result.applicability.state is ApplicabilityState.NOT_APPLICABLE


def test_missing_compression_is_blocked():
    x=breakout_intel();x=replace(x,regime=replace(x.regime,historical_compression=None),market_intelligence_snapshot_id="NO-COMP")
    _,result,_=evaluate(intel=x);assert result.final_action is FinalResearchAction.BLOCKED


def test_wick_policy_close_confirmation_expansion_and_displacement():
    _,wick,_=evaluate(intel=breakout_intel(wick=True,identity="WICK"));assert wick.research_signal is None
    _,allowed,_=evaluate(S2Configuration(wick_break_allowed=True),breakout_intel(wick=True,identity="WICK-OK"));assert allowed.research_signal is not None
    _,no_expansion,_=evaluate(intel=breakout_intel(expansion=1.0,identity="NO-EXP"));assert no_expansion.research_signal is None
    _,no_displacement,_=evaluate(intel=breakout_intel(displacement=0.01,identity="NO-DISP"));assert no_displacement.research_signal is None


def test_shared_breakout_identity_and_variant_candidate_independence():
    intel=breakout_intel(role_flip=True);a,immediate,_=evaluate(S2Configuration(variant=S2Variant.IMMEDIATE),intel);b,retest,_=evaluate(S2Configuration(variant=S2Variant.RETEST),intel)
    assert a.breakout_history[-1].breakout_event_id==b.breakout_history[-1].breakout_event_id
    assert immediate.candidate.signal_candidate_id!=retest.candidate.signal_candidate_id


def test_retest_waiting_then_role_flip_hold_and_resumption():
    config=S2Configuration(variant=S2Variant.RETEST);_,waiting,_=evaluate(config,breakout_intel(role_flip=False,identity="WAIT"));assert waiting.research_signal is None
    strategy,held,_=evaluate(config,breakout_intel(role_flip=True,identity="HELD"));assert held.research_signal is not None
    assert next(iter(strategy._retests.values())).state is RetestState.RESUMPTION_CONFIRMED


def test_abnormal_unknown_session_news_and_hard_blocks_not_rescued():
    for regime in (PrimaryRegime.ABNORMAL,PrimaryRegime.UNKNOWN):
        x=breakout_intel(identity=regime.name);x=replace(x,regime=replace(x.regime,primary_regime=regime),market_intelligence_snapshot_id=f"R-{regime.name}")
        _,result,_=evaluate(intel=x);assert result.research_signal is None


def test_event_candidate_immutability_lineage_and_duplicate_prevention():
    strategy,result,_=evaluate();event=strategy.breakout_history[-1]
    assert event.compression_evidence_id and event.market_intelligence_snapshot_id==result.candidate.market_intelligence_snapshot_id
    with pytest.raises(FrozenInstanceError):event.status=BreakoutState.FALSE_BREAK
    replay,second,_=evaluate();assert replay.breakout_history[-1].breakout_event_id==event.breakout_event_id and second.candidate.logical_signal_id==result.candidate.logical_signal_id


def test_recovery_observability_no_action_and_safety_surface():
    strategy,result,audit=evaluate();state=strategy.recovery_state()
    assert strategy.validate_recovery(state) and not strategy.validate_recovery({"s2_engine_version":"OLD"})
    assert {name for name,_ in audit.events}>={"s2_evaluation_started","s2_evaluation_completed","scoring_completed"}
    forbidden={"place_order","submit_order","size_position","set_stop_loss","set_take_profit","close_position","broker_login"}
    assert forbidden.isdisjoint(set(dir(BreakoutVolatilityStrategy)))
