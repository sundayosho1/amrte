from dataclasses import FrozenInstanceError,replace
from types import MappingProxyType

import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.features import FeatureHealth,FeatureValue,WarmupMetadata,WarmupState
from amrte.market.intelligence import IntelligenceAvailability,IntelligenceHealth
from amrte.market.regime import PrimaryRegime,RegimeDirection
from amrte.market.structure import Alignment,ConsolidationState,StructuralDirection
from amrte.strategies.framework import *
from amrte.strategies.scoring import CentralSignalScorer
from amrte.strategies.trend_pullback import *
from Tests.Unit.test_events import NOW
from Tests.Unit.test_strategy_framework import intelligence,orchestrator


def fv(value):return FeatureValue(value,FeatureHealth.VALID,NOW,"BAR",WarmupMetadata(WarmupState.READY,1,10,True,NOW))


def with_features(intel,*,strategy_displacement=-1.0,execution_displacement=1.0,adx=80.0,volatility=1.0,extra=None,identity="S1"):
    features={role:dict(values) for role,values in intel.features.features.items()}
    def put(role,name,value):features[role][f"{name}:{{}}:0"]=fv(value)
    put("strategy","ATR_ADJUSTED_DISPLACEMENT",strategy_displacement);put("execution","ATR_ADJUSTED_DISPLACEMENT",execution_displacement)
    put("strategy","ADX",adx);put("strategy","VOLATILITY_EXPANSION_RATIO",volatility)
    for role,name,value in extra or ():put(role,name,value)
    snapshot=replace(intel.features,feature_snapshot_id=f"FEATURE-{identity}",features=features)
    regime=replace(intel.regime,source_feature_snapshot_id=snapshot.feature_snapshot_id,regime_snapshot_id=f"REGIME-{identity}")
    return replace(intel,features=snapshot,feature_snapshot_id=snapshot.feature_snapshot_id,regime=regime,regime_snapshot_id=regime.regime_snapshot_id,market_intelligence_snapshot_id=f"INTEL-{identity}")


def bullish(**kwargs):return with_features(intelligence(),**kwargs)


def bearish(**kwargs):
    x=with_features(intelligence(),strategy_displacement=1.0,execution_displacement=-1.0,**kwargs)
    structure=replace(x.structure,
      context_structure=replace(x.structure.context_structure,direction=StructuralDirection.BEARISH),
      strategy_structure=replace(x.structure.strategy_structure,direction=StructuralDirection.BEARISH),
      execution_structure=replace(x.structure.execution_structure,direction=StructuralDirection.BEARISH),alignment=Alignment.FULL_BEARISH_ALIGNMENT)
    regime=replace(x.regime,direction=RegimeDirection.BEARISH,source_structure_snapshot_id=structure.structure_snapshot_id)
    return replace(x,structure=structure,regime=regime,market_intelligence_snapshot_id="INTEL-BEAR")


def evaluate(intel=None,config=S1Configuration()):
    audit=InMemoryAuditSink();strategy=TrendPullbackStrategy(config,audit)
    scorer=CentralSignalScorer(audit=audit,strategy_families={S1_STRATEGY_ID:StrategyFamily.TREND})
    engine,_=orchestrator(strategy,scorer=scorer)
    return strategy,engine.evaluate(strategy,intel or bullish()),audit


def test_registration_identity_family_and_version():
    registry=StrategyRegistry();strategy=register_s1(registry)
    assert registry.get(S1_STRATEGY_ID) is strategy
    assert strategy.metadata.identity.family is StrategyFamily.TREND and strategy.metadata.identity.version=="1.0.0"


def test_three_timeframe_roles_are_configurable_and_validated():
    config=S1Configuration(context_timeframe="D1",strategy_timeframe="H4",execution_timeframe="H1")
    assert TrendPullbackStrategy(config).metadata.required_timeframes==("D1","H4","H1")
    with pytest.raises(ValueError,match="S1_INVALID_TIMEFRAME_HIERARCHY"):TrendPullbackStrategy(S1Configuration(context_timeframe="H1"))
    with pytest.raises(ValueError,match="S1_INVALID_PULLBACK_DEPTH"):TrendPullbackStrategy(S1Configuration(minimum_pullback_depth=4,maximum_pullback_depth=3))
    with pytest.raises(ValueError,match="S1_INVALID_PULLBACK_DURATION"):TrendPullbackStrategy(S1Configuration(minimum_pullback_duration=3,maximum_pullback_duration=2))


@pytest.mark.parametrize("factory,direction",[(bullish,SignalDirection.LONG_BIAS),(bearish,SignalDirection.SHORT_BIAS)])
def test_bullish_bearish_symmetry_prompt11_prompt12(factory,direction):
    strategy,result,_=evaluate(factory())
    assert result.final_action is FinalResearchAction.RESEARCH_SIGNAL
    assert result.candidate.direction is direction and result.research_signal.direction is direction
    assert result.score.scoring_model_id.endswith("TREND_RESEARCH_SCORE") and result.score.overall_score>=0
    assert strategy.pullback_history[-1].state is PullbackState.COMPLETED


@pytest.mark.parametrize("regime,state",[(PrimaryRegime.RANGE,ApplicabilityState.NOT_APPLICABLE),(PrimaryRegime.ABNORMAL,ApplicabilityState.BLOCKED),(PrimaryRegime.UNKNOWN,ApplicabilityState.BLOCKED)])
def test_regime_applicability_fail_closed(regime,state):
    x=bullish(identity=regime.name);x=replace(x,regime=replace(x.regime,primary_regime=regime),market_intelligence_snapshot_id=f"I-{regime.name}")
    _,result,_=evaluate(x);assert result.applicability.state is state and result.research_signal is None


def test_invalid_intelligence_is_blocked_upstream():
    x=replace(bullish(),overall_intelligence_health=IntelligenceHealth.UNTRUSTED,intelligence_availability=IntelligenceAvailability.NOT_AVAILABLE,market_intelligence_snapshot_id="INVALID")
    _,result,_=evaluate(x);assert result.final_action is FinalResearchAction.BLOCKED and result.detection is None


@pytest.mark.parametrize("strategy_value,execution_value,expected",[(1,1,DetectionState.NOT_DETECTED),(-.01,1,DetectionState.NOT_DETECTED),(-4,1,DetectionState.BLOCKED),(-1,0,DetectionState.NOT_DETECTED)])
def test_pullback_depth_and_resumption_states(strategy_value,execution_value,expected):
    _,result,_=evaluate(bullish(strategy_displacement=strategy_value,execution_displacement=execution_value,identity=f"{strategy_value}-{execution_value}"))
    assert result.detection.status is expected and (result.research_signal is None)==(expected is not DetectionState.DETECTED)


def test_no_trend_and_mixed_context_are_normal_no_action():
    x=bullish();structure=replace(x.structure,context_structure=replace(x.structure.context_structure,direction=StructuralDirection.MIXED))
    x=replace(x,structure=structure,market_intelligence_snapshot_id="MIXED")
    _,result,_=evaluate(x);assert result.outcome is EvaluationOutcome.NO_ACTION and result.final_action is FinalResearchAction.NO_ACTION


def test_consolidation_is_not_pullback():
    x=bullish();s=x.structure.strategy_structure;s=replace(s,consolidation=replace(s.consolidation,state=ConsolidationState.CONSOLIDATING))
    x=replace(x,structure=replace(x.structure,strategy_structure=s),market_intelligence_snapshot_id="CONSOLIDATION")
    strategy,result,_=evaluate(x)
    assert result.research_signal is None and strategy.pullback_history[-1].classification is PullbackClassification.CONSOLIDATION


def test_ema_adx_di_and_optional_momentum_evidence_consumed_not_recalculated():
    extra=(("strategy","EMA_SLOPE",.2),("strategy","EMA_SEPARATION",.3),("strategy","PLUS_DI",40),("strategy","MINUS_DI",20),("execution","ROC",2),("execution","MACD_HISTOGRAM",.5),("execution","RSI",55),("execution","CANDLE_BODY_RATIO",.8))
    strategy,result,_=evaluate(bullish(extra=extra))
    trend=strategy.trend_context(StrategyEvaluationContext("E",S1_STRATEGY_ID,result.instrument_id,result.candidate.as_of_timestamp_utc,bullish(extra=extra),"CFG",None,EvaluationReason.NEW_BAR,0))
    assert trend.ema_alignment=="BULLISH" and trend.directional_movement=="BULLISH" and trend.adx==80


@pytest.mark.parametrize("volatility,support",[(1.0,True),(4.0,False)])
def test_volatility_context(volatility,support):
    _,result,_=evaluate(bullish(volatility=volatility,identity=f"VOL-{volatility}"))
    vol=next(e for e in result.detection.evidence if e.evidence_type=="VOLATILITY")
    assert (vol.category is EvidenceCategory.SUPPORTING) is support


def test_pullback_identity_determinism_immutability_and_configuration_lineage():
    strategy,result,_=evaluate();first=strategy.pullback_history[-1]
    replay,_,_=evaluate();second=replay.pullback_history[-1]
    assert first.pullback_id==second.pullback_id and first.pullback_version_id==second.pullback_version_id
    assert first.configuration_snapshot_id==S1Configuration().configuration_snapshot_id
    with pytest.raises(FrozenInstanceError):first.state=PullbackState.INVALIDATED


def test_expiration_and_bounded_history():
    strategy=TrendPullbackStrategy(S1Configuration(maximum_pullback_duration=1,maximum_history=1));x=bullish(execution_displacement=0)
    _,context,detection,qualification=__import__("Tests.Unit.test_signal_scoring",fromlist=["context_and_results"]).context_and_results()
    # Use explicit S1 contexts to advance the same logical pullback.
    for index in range(2):
        c=StrategyEvaluationContext(f"E{index}",S1_STRATEGY_ID,x.instrument_id,x.as_of_timestamp_utc,x,x.configuration_snapshot_id,None,EvaluationReason.NEW_BAR,x.recovery_epoch)
        strategy.detect(c)
    assert strategy.pullback_history[-1].state is PullbackState.EXPIRED and len(strategy.pullback_history)==1


def test_recovery_validation_and_instrument_isolation():
    strategy,result,_=evaluate();state=strategy.recovery_state();x=bullish()
    assert strategy.validate_recovery(state,x.dataset_fingerprint,x.instrument_id,x.recovery_epoch)
    assert not strategy.validate_recovery(state,"OTHER",x.instrument_id,x.recovery_epoch)
    assert strategy.state(x.instrument_id).instrument_id==x.instrument_id and strategy.state("FICTIONAL_BETA") is None


def test_exit_context_is_research_metadata_only():
    strategy,result,_=evaluate();context=StrategyEvaluationContext(result.evaluation_id,S1_STRATEGY_ID,result.instrument_id,result.candidate.as_of_timestamp_utc,bullish(),"CFG",None,EvaluationReason.NEW_BAR,0)
    strategy._latest[context.evaluation_id]=strategy._latest[result.evaluation_id]
    exit_context=strategy.exit_context(context)
    assert exit_context.state is ExitContextState.THESIS_INTACT
    assert not any(hasattr(exit_context,name) for name in ("stop_price","target_price","close_position"))


def test_observability_decision_trace_and_no_action_trace():
    _,signal,audit=evaluate();_,none,audit2=evaluate(bullish(strategy_displacement=1,identity="NONE"))
    assert signal.decision_trace.outcome.name=="NO_ACTION" and none.decision_trace.outcome.name=="NO_ACTION"
    assert {name for name,_ in audit.events}>={"s1_evaluation_started","s1_evaluation_completed","scoring_completed"}


def test_high_score_never_rescues_hard_failure():
    x=bullish();s=replace(x.structure,strategy_structure=replace(x.structure.strategy_structure,direction=StructuralDirection.BEARISH))
    x=replace(x,structure=s,market_intelligence_snapshot_id="STRUCTURE-CONFLICT")
    _,result,_=evaluate(x);assert result.research_signal is None


def test_configuration_change_changes_pullback_identity_not_history():
    a,_,_=evaluate(config=S1Configuration(configuration_snapshot_id="A"));b,_,_=evaluate(config=S1Configuration(configuration_snapshot_id="B"))
    assert a.pullback_history[-1].pullback_id!=b.pullback_history[-1].pullback_id


def test_safety_surface_has_no_execution_or_financial_methods():
    forbidden={"place_order","submit_order","size_position","set_stop_loss","set_take_profit","close_position","authenticate_broker"}
    assert forbidden.isdisjoint(set(dir(TrendPullbackStrategy)))

