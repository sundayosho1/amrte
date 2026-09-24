from dataclasses import FrozenInstanceError, replace
from datetime import datetime,timezone
from types import MappingProxyType

import pytest

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.features import FeatureHealth,FeatureSnapshot,FeatureValue,WarmupMetadata,WarmupState
from amrte.market.models import DataHealth,MarketDataSnapshot,SpreadHealth,SpreadOrigin,SpreadState,SynchronizationStatus
from amrte.market.regime import *
from amrte.market.structure import (
    Alignment,ConfidenceResult,ConsolidationResult,ConsolidationState,StructureHealth,
    StructureSnapshot,StructuralDirection,TimeframeStructure,
)

NOW=datetime(2026,1,1,tzinfo=timezone.utc)


def confidence(health=StructureHealth.HEALTHY):return ConfidenceResult(80,{"evidence":80},(),3,health)
def timeframe(name,direction=StructuralDirection.BULLISH,consolidating=False,health=StructureHealth.HEALTHY):
    return TimeframeStructure(name,NOW,DataHealth.HEALTHY,health,direction,(),(),(),
        ConsolidationResult(ConsolidationState.CONSOLIDATING if consolidating else ConsolidationState.NOT_CONSOLIDATING,
            99,101,2,NOW,NOW,90,("BOUNDED",)),(),confidence(health),(direction.name,))


def upstream(direction=StructuralDirection.BULLISH,consolidating=False,feature_values=None,
             data_health=DataHealth.HEALTHY,sync=SynchronizationStatus.SYNCHRONIZED,
             spread_health=SpreadHealth.UNAVAILABLE,identity="MD"):
    spread=SpreadState(None,None,None,None,None,spread_health,SpreadOrigin.UNAVAILABLE)
    market=MarketDataSnapshot(identity,NOW,NOW,"EXP","DS","FP","FICTIONAL_ALPHA",spread,(),(),(),sync,data_health,100,{},"CFG",0)
    structures=(timeframe("H4",direction,consolidating),timeframe("H1",direction,consolidating),timeframe("M15",direction,consolidating))
    structure=StructureSnapshot("STRUCT",NOW,NOW,"EXP","DS","FP","FICTIONAL_ALPHA",identity,*structures,
        Alignment.FULL_BULLISH_ALIGNMENT if direction is StructuralDirection.BULLISH else Alignment.NEUTRAL,
        80,StructureHealth.HEALTHY,confidence(),(),"CFG",0)
    warm=WarmupMetadata(WarmupState.READY,1,100,True,NOW)
    defaults={"ADX:{}:0":FeatureValue(80,FeatureHealth.VALID,NOW,"B",warm,(),"0-100"),
        "VOLATILITY_EXPANSION_RATIO:{}:0":FeatureValue(1.0,FeatureHealth.VALID,NOW,"B",warm,(),"ratio"),
        "ATR_ADJUSTED_DISPLACEMENT:{}:0":FeatureValue(2.0,FeatureHealth.VALID,NOW,"B",warm,(),"ATR"),
        "BOLLINGER_BANDWIDTH:{}:0":FeatureValue(.1,FeatureHealth.VALID,NOW,"B",warm,(),"ratio")}
    if feature_values:defaults.update(feature_values)
    features=FeatureSnapshot("FEATURE",NOW,NOW,"EXP","DS","FP","FICTIONAL_ALPHA",identity,"STRUCT",
        {role:dict(defaults) for role in ("context","strategy","execution")},FeatureHealth.VALID,(),"CFG",0)
    return market,structure,features


def engine(**changes):return RegimeEngine(FixedClock(NOW),InMemoryAuditSink(),RegimeConfiguration(**changes))


def test_invalid_configuration_rejected():
    with pytest.raises(ValueError):engine(entry_threshold=40,exit_threshold=50)
    with pytest.raises(ValueError):engine(timeframe_weights=(0,0,0))


def test_valid_lineage_and_mismatches():
    m,s,f=upstream(); valid,reasons=engine().validate_lineage(m,s,f); assert valid and not reasons
    valid,reasons=engine().validate_lineage(m,replace(s,dataset_fingerprint="OTHER"),f)
    assert not valid and "DATASET_FINGERPRINT_MISMATCH" in reasons
    assert engine().analyze(m,replace(s,source_market_data_snapshot_id="OTHER"),f) is None


def test_bullish_and_bearish_trend_direction_are_separate():
    for direction,expected in ((StructuralDirection.BULLISH,RegimeDirection.BULLISH),(StructuralDirection.BEARISH,RegimeDirection.BEARISH)):
        result=engine(confirmation_observations=1,minimum_classification_margin=0).analyze(*upstream(direction))
        assert result.primary_regime is PrimaryRegime.TREND and result.direction is expected
        assert result.component_scores.trend>=60


def test_stable_range_and_unknown_are_distinct():
    result=engine(confirmation_observations=1,minimum_classification_margin=0).analyze(*upstream(StructuralDirection.SIDEWAYS,True))
    assert result.primary_regime is PrimaryRegime.RANGE and result.direction is RegimeDirection.NEUTRAL
    unavailable=FeatureValue(None,FeatureHealth.INSUFFICIENT_HISTORY,NOW,"B",WarmupMetadata(WarmupState.INSUFFICIENT_HISTORY,20,2,False,None))
    unknown=engine(confirmation_observations=1).analyze(*upstream(StructuralDirection.UNKNOWN,False,feature_values={
        "ADX:{}:0":unavailable,"ATR_ADJUSTED_DISPLACEMENT:{}:0":unavailable}))
    assert unknown.primary_regime is PrimaryRegime.UNKNOWN


def test_abnormal_and_unknown_distinction_and_precedence():
    e=engine(confirmation_observations=1)
    abnormal=e.analyze(*upstream(data_health=DataHealth.INVALID))
    assert abnormal.primary_regime is PrimaryRegime.ABNORMAL and "DATA_INVALID" in abnormal.reason_codes
    assert abnormal.regime_health in (RegimeHealth.RESTRICTED,RegimeHealth.INVALID_INPUT)
    assert all(state is EligibilityState.BLOCKED for state in abnormal.eligibility.values())


def test_extreme_spread_is_abnormal_positive_evidence():
    result=engine(confirmation_observations=1).analyze(*upstream(spread_health=SpreadHealth.EXTREME))
    assert result.primary_regime is PrimaryRegime.ABNORMAL and "EXTREME_SPREAD" in result.reason_codes


def test_score_bounds_margin_and_confidence_health_constraint():
    result=engine(confirmation_observations=1).analyze(*upstream())
    assert all(0<=value<=100 for value in result.component_scores.__dict__.values())
    assert 0<=result.confidence.score<=100 and result.confidence.classification_margin>=0
    abnormal=engine(confirmation_observations=1).analyze(*upstream(data_health=DataHealth.INVALID))
    assert abnormal.confidence.health_constraint is not RegimeHealth.HEALTHY


def test_per_timeframe_and_composite_results_are_present():
    result=engine(confirmation_observations=1,minimum_classification_margin=0).analyze(*upstream())
    assert {result.context_regime.timeframe,result.strategy_regime.timeframe,result.execution_regime.timeframe}=={"H4","H1","M15"}
    assert result.context_regime.component_scores.trend>0


def test_hysteresis_confirmation_hold_and_change():
    e=engine(confirmation_observations=2,minimum_classification_margin=0,cooldown_observations=0)
    first=e.analyze(*upstream(identity="MD1")); assert first.raw_candidate is PrimaryRegime.TREND and first.primary_regime is PrimaryRegime.UNKNOWN and first.hysteresis_state.held
    m,s,f=upstream(identity="MD2"); s=replace(s,source_market_data_snapshot_id="MD2"); f=replace(f,source_market_data_snapshot_id="MD2")
    second=e.analyze(m,s,f); assert second.primary_regime is PrimaryRegime.TREND and not second.hysteresis_state.held


def test_temporary_uncertainty_grace_holds_stable_regime():
    e=engine(confirmation_observations=1,minimum_classification_margin=0,unknown_grace_observations=1,cooldown_observations=0)
    stable=e.analyze(*upstream(identity="MD1")); assert stable.primary_regime is PrimaryRegime.TREND
    unavailable=FeatureValue(None,FeatureHealth.INSUFFICIENT_HISTORY,NOW,"B",WarmupMetadata(WarmupState.INSUFFICIENT_HISTORY,20,2,False,None))
    m,s,f=upstream(StructuralDirection.UNKNOWN,feature_values={
        "ADX:{}:0":unavailable,"ATR_ADJUSTED_DISPLACEMENT:{}:0":unavailable},identity="MD2")
    s=replace(s,source_market_data_snapshot_id="MD2"); f=replace(f,source_market_data_snapshot_id="MD2")
    uncertain=e.analyze(m,s,f); assert uncertain.raw_candidate is PrimaryRegime.UNKNOWN and uncertain.primary_regime is PrimaryRegime.TREND


def test_advisory_eligibility_is_metadata_and_no_action_trace():
    result=engine(confirmation_observations=1,minimum_classification_margin=0).analyze(*upstream())
    assert result.eligibility["DIRECTIONAL_RESEARCH"] is EligibilityState.ELIGIBLE
    assert result.decision_trace.outcome.name=="NO_ACTION"


def test_snapshot_history_immutability_order_and_duplicate_suppression():
    e=engine(confirmation_observations=1,minimum_classification_margin=0,maximum_history=2)
    result=e.analyze(*upstream(identity="MD1")); e.analyze(*upstream(identity="MD1"))
    assert len(e.history)==1
    with pytest.raises(FrozenInstanceError):result.primary_regime=PrimaryRegime.RANGE
    with pytest.raises(TypeError):result.eligibility["x"]=EligibilityState.ELIGIBLE


def test_recovery_validation_and_bounded_history():
    e=engine(confirmation_observations=1,minimum_classification_margin=0,maximum_history=2)
    for identity in ("MD1","MD2","MD3"):
        m,s,f=upstream(identity=identity); s=replace(s,source_market_data_snapshot_id=identity); f=replace(f,source_market_data_snapshot_id=identity)
        e.analyze(m,s,f,configuration_hash="HASH")
    state=e.recovery_state(); assert len(e.history)==2
    assert e.validate_recovery(state,"FP","HASH") and not e.validate_recovery(state,"OTHER","HASH")


def test_deterministic_rebuild_equivalence():
    timeline=[]
    for identity in ("MD1","MD2"):
        m,s,f=upstream(identity=identity); timeline.append((m,replace(s,source_market_data_snapshot_id=identity),replace(f,source_market_data_snapshot_id=identity)))
    incremental_engine=engine(confirmation_observations=1,minimum_classification_margin=0,cooldown_observations=0)
    incremental=tuple(incremental_engine.analyze(*items) for items in timeline)
    rebuilt=engine(confirmation_observations=1,minimum_classification_margin=0,cooldown_observations=0).rebuild(timeline)
    assert tuple(item.primary_regime for item in incremental)==tuple(item.primary_regime for item in rebuilt)
    assert tuple(item.regime_snapshot_id for item in incremental)==tuple(item.regime_snapshot_id for item in rebuilt)


def test_observability_and_readiness():
    audit=InMemoryAuditSink(); e=RegimeEngine(FixedClock(NOW),audit,RegimeConfiguration(confirmation_observations=1,minimum_classification_margin=0))
    result=e.analyze(*upstream()); assert e.readiness(result)[0]
    assert {name for name,_ in audit.events}>={"regime_analysis_started","regime_snapshot_created"}
