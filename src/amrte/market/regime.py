from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from types import MappingProxyType
from typing import Mapping

from amrte.core.identity import deterministic_id
from amrte.core.interfaces import IAuditSink, IClock
from amrte.core.observability import DecisionTraceBuilder
from amrte.core.observability_types import DecisionOutcome, DecisionStatus, DecisionTrace
from .features import FeatureHealth, FeatureSnapshot, FeatureValue,TemporalFeatureSeries,TemporalSeriesHealth
from .models import DataHealth, MarketDataSnapshot, SpreadHealth, SynchronizationStatus
from .structure import (
    Alignment, ConsolidationState, StructureHealth, StructureSnapshot,
    StructuralDirection, ZoneState,
)

REGIME_ENGINE_VERSION = "1.1"


class PrimaryRegime(Enum):
    TREND = auto(); RANGE = auto(); BREAKOUT_EXPANSION = auto()
    TRANSITION = auto(); ABNORMAL = auto(); UNKNOWN = auto()


class RegimeDirection(Enum): BULLISH = auto(); BEARISH = auto(); NEUTRAL = auto(); MIXED = auto(); UNKNOWN = auto()
class RegimeHealth(Enum): HEALTHY = auto(); DEGRADED = auto(); RESTRICTED = auto(); INSUFFICIENT_EVIDENCE = auto(); INVALID_INPUT = auto(); UNAVAILABLE = auto(); UNKNOWN = auto()
class AbnormalSeverity(Enum): NONE = auto(); ELEVATED = auto(); SEVERE = auto(); CRITICAL = auto()
class EligibilityState(Enum): ELIGIBLE = auto(); RESTRICTED = auto(); BLOCKED = auto(); UNKNOWN = auto()
class CompressionState(Enum):CONFIRMED=auto();PROBABLE=auto();WEAK=auto();NOT_CONFIRMED=auto();INSUFFICIENT_HISTORY=auto();INVALID=auto();UNKNOWN=auto()
class CompressionHealth(Enum):HEALTHY=auto();DEGRADED=auto();INCOMPLETE=auto();INSUFFICIENT_HISTORY=auto();INVALID=auto();UNKNOWN=auto()

@dataclass(frozen=True)
class CompressionConfiguration:
    minimum_compression_bars:int=3;maximum_lookback:int=12;minimum_persistence:int=2
    maximum_allowed_missing_observations:int=0;maximum_volatility_ratio:float=1.0
    maximum_bandwidth:float=.20;maximum_range_atr:float=2.0
    confirmed_score:float=70.0;probable_score:float=50.0
    required_features:tuple[str,...]=("VOLATILITY_EXPANSION_RATIO","BOLLINGER_BANDWIDTH")
    def validate(self):
        errors=[]
        if self.minimum_compression_bars<1 or self.maximum_lookback<self.minimum_compression_bars:errors.append("INVALID_COMPRESSION_WINDOW")
        if self.minimum_persistence<1 or self.minimum_persistence>self.maximum_lookback:errors.append("INVALID_COMPRESSION_PERSISTENCE")
        if self.maximum_allowed_missing_observations<0:errors.append("INVALID_COMPRESSION_MISSING_POLICY")
        if min(self.maximum_volatility_ratio,self.maximum_bandwidth,self.maximum_range_atr)<0:errors.append("INVALID_COMPRESSION_THRESHOLD")
        if not 0<=self.probable_score<=self.confirmed_score<=100:errors.append("INVALID_COMPRESSION_SCORE_THRESHOLD")
        return tuple(errors)

@dataclass(frozen=True)
class HistoricalCompressionEvidence:
    evidence_id:str;instrument_id:str;timeframe:str;window_start_utc:datetime|None
    window_end_utc:datetime|None;as_of_timestamp_utc:datetime;breakout_observation_time_utc:datetime|None
    observation_count:int;compression_state:CompressionState;compression_score:float
    range_evidence:float|None;volatility_evidence:float|None;bandwidth_evidence:float|None
    atr_contraction_evidence:float|None;realized_volatility_evidence:float|None;persistence:int
    supporting_evidence:tuple[str,...];conflicting_evidence:tuple[str,...];missing_evidence:tuple[str,...]
    health:CompressionHealth;temporal_feature_series_id:str;dataset_fingerprint:str
    configuration_snapshot_id:str;recovery_epoch:int


class HistoricalCompressionAnalyzer:
    def __init__(self,configuration:CompressionConfiguration=CompressionConfiguration(),audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit
    @staticmethod
    def _value(observation,name):
        values=[value for key,value in observation.values.items() if key.split(":",1)[0]==name]
        if not values:return None
        value=values[0]
        return float(value.value) if isinstance(value.value,(int,float)) and value.health in (FeatureHealth.VALID,FeatureHealth.VALID_WITH_WARNINGS) else None
    def analyze(self,series:TemporalFeatureSeries,*,breakout_observation_time:datetime|None=None):
        cfg=self.configuration
        observations=tuple(item for item in series.observations if breakout_observation_time is None or item.available_at_utc<breakout_observation_time)[-cfg.maximum_lookback:]
        missing=max(0,cfg.minimum_compression_bars-len(observations));support=[];conflicts=[];scores=[];persistence=0
        for item in observations:
            vol=self._value(item,"VOLATILITY_EXPANSION_RATIO");band=self._value(item,"BOLLINGER_BANDWIDTH");rng=self._value(item,"RANGE_ATR")
            dimensions=[]
            if vol is not None:dimensions.append(100 if vol<=cfg.maximum_volatility_ratio else 0)
            if band is not None:dimensions.append(100 if band<=cfg.maximum_bandwidth else 0)
            if rng is not None:dimensions.append(100 if rng<=cfg.maximum_range_atr else 0)
            current=sum(dimensions)/len(dimensions) if dimensions else 0;scores.append(current)
            if current>=cfg.probable_score:persistence+=1;support.append(item.observation_id)
            else:conflicts.append(item.observation_id)
        score=sum(scores)/len(scores) if scores else 0
        if series.health in (TemporalSeriesHealth.INVALID_INPUT,TemporalSeriesHealth.UNKNOWN):state=CompressionState.INVALID;health=CompressionHealth.INVALID
        elif len(observations)<cfg.minimum_compression_bars or missing>cfg.maximum_allowed_missing_observations:state=CompressionState.INSUFFICIENT_HISTORY;health=CompressionHealth.INSUFFICIENT_HISTORY
        elif score>=cfg.confirmed_score and persistence>=cfg.minimum_persistence:state=CompressionState.CONFIRMED;health=CompressionHealth.HEALTHY
        elif score>=cfg.probable_score:state=CompressionState.PROBABLE;health=CompressionHealth.DEGRADED
        elif score>0:state=CompressionState.WEAK;health=CompressionHealth.DEGRADED
        else:state=CompressionState.NOT_CONFIRMED;health=CompressionHealth.HEALTHY
        average=lambda name:(sum(self._value(x,name) or 0 for x in observations)/len(observations) if observations else None)
        identity=deterministic_id("historical_compression",series.series_id,breakout_observation_time.isoformat() if breakout_observation_time else "none",cfg.minimum_compression_bars,cfg.maximum_lookback,state.name)
        result=HistoricalCompressionEvidence(identity,series.instrument_id,series.timeframe,observations[0].bar_time_utc if observations else None,observations[-1].bar_time_utc if observations else None,series.as_of_timestamp_utc,breakout_observation_time,len(observations),state,score,average("RANGE_ATR"),average("VOLATILITY_EXPANSION_RATIO"),average("BOLLINGER_BANDWIDTH"),average("ATR_PERCENT_PRICE"),average("REALIZED_VOLATILITY"),persistence,tuple(support),tuple(conflicts),tuple(cfg.required_features if not observations else ()),health,series.series_id,series.dataset_fingerprint,series.configuration_snapshot_id,series.recovery_epoch)
        if self.audit:self.audit.record("compression_detected" if state is CompressionState.CONFIRMED else "compression_rejected",{"evidence_id":identity,"state":state.name})
        return result


@dataclass(frozen=True)
class RegimeConfiguration:
    trend_threshold: float = 60.0
    range_threshold: float = 60.0
    breakout_threshold: float = 65.0
    transition_threshold: float = 55.0
    abnormal_threshold: float = 70.0
    minimum_confidence: float = 50.0
    minimum_classification_margin: float = 8.0
    entry_threshold: float = 60.0
    exit_threshold: float = 45.0
    confirmation_observations: int = 2
    minimum_persistence: int = 1
    cooldown_observations: int = 1
    unknown_grace_observations: int = 1
    maximum_history: int = 100
    timeframe_weights: tuple[float, float, float] = (0.5, 0.3, 0.2)
    strict: bool = True

    def validate(self) -> tuple[str, ...]:
        errors=[]
        for name,value in (("trend",self.trend_threshold),("range",self.range_threshold),
            ("breakout",self.breakout_threshold),("transition",self.transition_threshold),
            ("abnormal",self.abnormal_threshold),("confidence",self.minimum_confidence),
            ("margin",self.minimum_classification_margin),("entry",self.entry_threshold),
            ("exit",self.exit_threshold)):
            if not 0<=value<=100: errors.append(f"{name} threshold outside 0..100")
        if self.exit_threshold>self.entry_threshold: errors.append("exit threshold exceeds entry threshold")
        if min(self.confirmation_observations,self.minimum_persistence,self.maximum_history)<1: errors.append("counts must be positive")
        if self.cooldown_observations<0 or self.unknown_grace_observations<0: errors.append("cooldown/grace must be non-negative")
        if len(self.timeframe_weights)!=3 or any(item<0 for item in self.timeframe_weights) or sum(self.timeframe_weights)<=0: errors.append("timeframe weights invalid")
        return tuple(errors)


@dataclass(frozen=True)
class RegimeEvidence:
    evidence_code: str; source_module: str; source_snapshot_id: str
    timeframe: str; observed_value: str; normalized_score: float; weight: float
    contribution: float; direction: RegimeDirection; health: str; explanation: str


@dataclass(frozen=True)
class ComponentScores:
    trend: float; range: float; breakout: float; transition: float; abnormal: float


@dataclass(frozen=True)
class RegimeConfidence:
    score: float; winning_score: float; classification_margin: float
    evidence_coverage: float; evidence_agreement: float; timeframe_agreement: float
    persistence_contribution: float; health_constraint: RegimeHealth
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class TimeframeRegime:
    timeframe: str; primary_candidate: PrimaryRegime; direction: RegimeDirection
    component_scores: ComponentScores; confidence: float
    structure_health: StructureHealth; feature_health: FeatureHealth
    evidence: tuple[RegimeEvidence, ...]; missing_evidence: tuple[str, ...]


@dataclass(frozen=True)
class HysteresisState:
    stable_regime: PrimaryRegime; raw_candidate: PrimaryRegime
    candidate_count: int; persistence_count: int; cooldown_remaining: int
    held: bool; reason: str


@dataclass(frozen=True)
class RegimeHistoryEntry:
    timestamp: datetime; regime: PrimaryRegime; direction: RegimeDirection
    confidence: float; source_snapshot_id: str; duration_observations: int


@dataclass(frozen=True)
class RegimeSnapshot:
    regime_snapshot_id: str; created_at: datetime; as_of_timestamp: datetime
    experiment_id: str; dataset_id: str; dataset_fingerprint: str; instrument_id: str
    source_market_data_snapshot_id: str; source_structure_snapshot_id: str
    source_feature_snapshot_id: str; raw_candidate: PrimaryRegime
    primary_regime: PrimaryRegime; direction: RegimeDirection
    component_scores: ComponentScores; confidence: RegimeConfidence
    context_regime: TimeframeRegime; strategy_regime: TimeframeRegime
    execution_regime: TimeframeRegime; supporting_evidence: tuple[RegimeEvidence,...]
    conflicting_evidence: tuple[RegimeEvidence,...]; missing_evidence: tuple[str,...]
    reason_codes: tuple[str,...]; eligibility: Mapping[str,EligibilityState]
    data_health: DataHealth; structure_health: StructureHealth
    feature_health: FeatureHealth; regime_health: RegimeHealth
    hysteresis_state: HysteresisState; decision_trace: DecisionTrace
    configuration_snapshot_id: str; recovery_epoch: int
    regime_engine_version: str = REGIME_ENGINE_VERSION
    historical_compression: HistoricalCompressionEvidence|None = None

    def __post_init__(self): object.__setattr__(self,"eligibility",MappingProxyType(dict(self.eligibility)))


def _bounded(value: float) -> float: return max(0.0,min(100.0,value))


class RegimeEngine:
    def __init__(self,clock:IClock,audit:IAuditSink,configuration:RegimeConfiguration=RegimeConfiguration()):
        errors=configuration.validate()
        if errors: raise ValueError("; ".join(errors))
        self.clock=clock; self.audit=audit; self.configuration=configuration
        self._stable=PrimaryRegime.UNKNOWN; self._candidate=PrimaryRegime.UNKNOWN
        self._candidate_count=0; self._persistence=0; self._cooldown=0; self._unknown_count=0
        self._history:list[RegimeHistoryEntry]=[]; self._last_context:tuple[str,str,str]|None=None

    def validate_lineage(self,market:MarketDataSnapshot,structure:StructureSnapshot,features:FeatureSnapshot)->tuple[bool,tuple[str,...]]:
        reasons=[]
        if not (market.dataset_id==structure.dataset_id==features.dataset_id): reasons.append("DATASET_ID_MISMATCH")
        if not (market.dataset_fingerprint==structure.dataset_fingerprint==features.dataset_fingerprint): reasons.append("DATASET_FINGERPRINT_MISMATCH")
        if not (market.instrument_id==structure.instrument_id==features.instrument_id): reasons.append("INSTRUMENT_MISMATCH")
        if not (market.as_of_timestamp==structure.as_of_timestamp==features.as_of_timestamp): reasons.append("AS_OF_MISMATCH")
        if structure.source_market_data_snapshot_id!=market.snapshot_id: reasons.append("STRUCTURE_LINEAGE_MISMATCH")
        if features.source_market_data_snapshot_id!=market.snapshot_id: reasons.append("FEATURE_LINEAGE_MISMATCH")
        if features.source_structure_snapshot_id not in (None,structure.structure_snapshot_id): reasons.append("FEATURE_STRUCTURE_LINEAGE_MISMATCH")
        if not (market.configuration_snapshot_id==structure.configuration_snapshot_id==features.configuration_snapshot_id): reasons.append("CONFIGURATION_MISMATCH")
        return not reasons,tuple(reasons)

    def _feature(self,features:FeatureSnapshot,role:str,prefix:str)->FeatureValue|None:
        return next((value for key,value in features.features.get(role,{}).items() if key.startswith(prefix.upper()+":")),None)

    def _direction(self,structure_direction:StructuralDirection)->RegimeDirection:
        return {StructuralDirection.BULLISH:RegimeDirection.BULLISH,StructuralDirection.BEARISH:RegimeDirection.BEARISH,
                StructuralDirection.SIDEWAYS:RegimeDirection.NEUTRAL,StructuralDirection.MIXED:RegimeDirection.MIXED}.get(structure_direction,RegimeDirection.UNKNOWN)

    def _timeframe(self,role:str,structure,features:FeatureSnapshot)->TimeframeRegime:
        evidence=[]; missing=[]; scores={"trend":[],"range":[],"breakout":[],"transition":[],"abnormal":[]}
        def add(bucket,code,value,weight=1.0,module="Structure",direction=RegimeDirection.UNKNOWN,explanation=""):
            value=_bounded(value); scores[bucket].append((value,weight)); evidence.append(RegimeEvidence(code,module,
                features.source_structure_snapshot_id or features.feature_snapshot_id,structure.timeframe,str(value),value,weight,
                value*weight,direction,"VALID",explanation or code))
        direction=self._direction(structure.direction)
        if structure.direction in (StructuralDirection.BULLISH,StructuralDirection.BEARISH): add("trend","DIRECTIONAL_STRUCTURE",90,2,direction=direction)
        elif structure.direction is StructuralDirection.SIDEWAYS: add("range","SIDEWAYS_STRUCTURE",90,2,direction=RegimeDirection.NEUTRAL)
        elif structure.direction is StructuralDirection.MIXED: add("transition","MIXED_STRUCTURE",70,1.5,direction=RegimeDirection.MIXED)
        else: missing.append("STRUCTURE_DIRECTION")
        if structure.consolidation.state is ConsolidationState.CONSOLIDATING: add("range","CONSOLIDATION",structure.consolidation.confidence,2)
        if structure.breaks:
            latest=structure.breaks[-1]; bd=RegimeDirection.BULLISH if latest.direction.name.startswith("BULLISH") else RegimeDirection.BEARISH
            add("trend","CONFIRMED_BOS",80,1.5,direction=bd); add("breakout","BOUNDARY_BREAK",85,2,direction=bd)
        if structure.shifts: add("transition","STRUCTURAL_SHIFT",85,2,direction=RegimeDirection.MIXED)
        if any(zone.state is ZoneState.ROLE_FLIPPED for zone in structure.zones): add("breakout","ZONE_ROLE_FLIP",70,1)
        adx=self._feature(features,role,"ADX"); expansion=self._feature(features,role,"VOLATILITY_EXPANSION_RATIO")
        displacement=self._feature(features,role,"ATR_ADJUSTED_DISPLACEMENT"); bandwidth=self._feature(features,role,"BOLLINGER_BANDWIDTH")
        for name,item in (("ADX",adx),("VOLATILITY_EXPANSION_RATIO",expansion),("ATR_ADJUSTED_DISPLACEMENT",displacement),("BOLLINGER_BANDWIDTH",bandwidth)):
            if item is None or item.health not in (FeatureHealth.VALID,FeatureHealth.VALID_WITH_WARNINGS) or not isinstance(item.value,(int,float)): missing.append(name)
        if adx and adx.health in (FeatureHealth.VALID,FeatureHealth.VALID_WITH_WARNINGS) and isinstance(adx.value,(int,float)):
            add("trend","ADX_STRENGTH",float(adx.value),1,module="Features")
            add("range","ADX_WEAKNESS",100-float(adx.value),1,module="Features")
        if expansion and expansion.health in (FeatureHealth.VALID,FeatureHealth.VALID_WITH_WARNINGS) and isinstance(expansion.value,(int,float)):
            ratio=float(expansion.value); add("breakout","VOLATILITY_EXPANSION",_bounded((ratio-1)*100),2,module="Features")
            if ratio>1.2:add("transition","VOLATILITY_CHANGE",_bounded((ratio-1)*80),1,module="Features")
        if displacement and displacement.health in (FeatureHealth.VALID,FeatureHealth.VALID_WITH_WARNINGS) and isinstance(displacement.value,(int,float)):
            raw=float(displacement.value); dd=RegimeDirection.BULLISH if raw>0 else RegimeDirection.BEARISH
            add("trend","DIRECTIONAL_DISPLACEMENT",_bounded(abs(raw)*35),1,module="Features",direction=dd)
            add("breakout","EXPANSION_DISPLACEMENT",_bounded(abs(raw)*40),1.5,module="Features",direction=dd)
        if bandwidth and bandwidth.health in (FeatureHealth.VALID,FeatureHealth.VALID_WITH_WARNINGS) and isinstance(bandwidth.value,(int,float)) and float(bandwidth.value)<.05:add("range","BANDWIDTH_COMPRESSION",80,1,module="Features")
        if features.health not in (FeatureHealth.VALID,FeatureHealth.VALID_WITH_WARNINGS): add("abnormal","FEATURE_HEALTH_FAILURE",80,3,module="Features")
        def normalized(bucket):
            items=scores[bucket]; return _bounded(sum(v*w for v,w in items)/sum(w for _,w in items)) if items else 0.0
        normalized_scores={name:normalized(name) for name in ("trend","range","breakout","transition","abnormal")}
        evidence_codes={item.evidence_code for item in evidence}
        breakout_dimensions={"BOUNDARY_BREAK","VOLATILITY_EXPANSION","EXPANSION_DISPLACEMENT"}
        if not breakout_dimensions.issubset(evidence_codes):
            normalized_scores["breakout"]=min(normalized_scores["breakout"],self.configuration.breakout_threshold-1)
        component=ComponentScores(*(normalized_scores[name] for name in ("trend","range","breakout","transition","abnormal")))
        ordinary=((PrimaryRegime.TREND,component.trend,self.configuration.trend_threshold),(PrimaryRegime.RANGE,component.range,self.configuration.range_threshold),
                  (PrimaryRegime.BREAKOUT_EXPANSION,component.breakout,self.configuration.breakout_threshold),(PrimaryRegime.TRANSITION,component.transition,self.configuration.transition_threshold))
        winner=max(ordinary,key=lambda item:item[1]); candidate=winner[0] if winner[1]>=winner[2] else PrimaryRegime.UNKNOWN
        if component.abnormal>=self.configuration.abnormal_threshold:candidate=PrimaryRegime.ABNORMAL
        available=sum(1 for name in (adx,expansion,displacement,bandwidth) if name is not None); confidence=_bounded(winner[1]*(.6+.1*available))
        return TimeframeRegime(structure.timeframe,candidate,direction,component,confidence,structure.structure_health,features.health,tuple(evidence),tuple(sorted(set(missing))))

    def _composite(self,timeframes:tuple[TimeframeRegime,...])->tuple[ComponentScores,PrimaryRegime,float,float]:
        weights=self.configuration.timeframe_weights; total=sum(weights)
        def weighted(name):return _bounded(sum(getattr(tf.component_scores,name)*w for tf,w in zip(timeframes,weights))/total)
        scores=ComponentScores(*(weighted(name) for name in ("trend","range","breakout","transition","abnormal")))
        ordinary=[(PrimaryRegime.TREND,scores.trend,self.configuration.trend_threshold),(PrimaryRegime.RANGE,scores.range,self.configuration.range_threshold),
                  (PrimaryRegime.BREAKOUT_EXPANSION,scores.breakout,self.configuration.breakout_threshold),(PrimaryRegime.TRANSITION,scores.transition,self.configuration.transition_threshold)]
        ranked=sorted(ordinary,key=lambda item:item[1],reverse=True); margin=ranked[0][1]-ranked[1][1]
        candidate=ranked[0][0] if ranked[0][1]>=ranked[0][2] and margin>=self.configuration.minimum_classification_margin else PrimaryRegime.UNKNOWN
        if scores.abnormal>=self.configuration.abnormal_threshold:candidate=PrimaryRegime.ABNORMAL
        confidence=_bounded((ranked[0][1]*.6)+(min(100,margin*5)*.25)+(sum(tf.confidence for tf in timeframes)/3*.15))
        if confidence<self.configuration.minimum_confidence and candidate not in (PrimaryRegime.ABNORMAL,):candidate=PrimaryRegime.UNKNOWN
        return scores,candidate,confidence,margin

    def _publish(self,candidate:PrimaryRegime,winning_score:float,scores:ComponentScores)->HysteresisState:
        previous=self._stable
        if candidate is PrimaryRegime.ABNORMAL:
            self._stable=candidate; self._candidate=candidate; self._candidate_count=1; self._persistence=1; self._cooldown=0
            return HysteresisState(self._stable,candidate,1,1,0,False,"ABNORMAL_OVERRIDE")
        if candidate is self._stable:
            self._candidate=candidate; self._candidate_count=0; self._persistence+=1
            self._cooldown=max(0,self._cooldown-1); self._unknown_count=0
            return HysteresisState(self._stable,candidate,0,self._persistence,self._cooldown,False,"REGIME_PERSISTED")
        if candidate is PrimaryRegime.UNKNOWN:
            self._unknown_count+=1
            if self._unknown_count<=self.configuration.unknown_grace_observations and self._stable is not PrimaryRegime.UNKNOWN:
                return HysteresisState(self._stable,candidate,self._unknown_count,self._persistence,self._cooldown,True,"TEMPORARY_UNCERTAINTY_HELD")
        stable_score={PrimaryRegime.TREND:scores.trend,PrimaryRegime.RANGE:scores.range,
            PrimaryRegime.BREAKOUT_EXPANSION:scores.breakout,PrimaryRegime.TRANSITION:scores.transition}.get(self._stable,0.0)
        if self._stable not in (PrimaryRegime.UNKNOWN,PrimaryRegime.ABNORMAL) and stable_score>=self.configuration.exit_threshold:
            self._persistence+=1
            return HysteresisState(self._stable,candidate,self._candidate_count,self._persistence,self._cooldown,True,"EXIT_THRESHOLD_HELD")
        if self._stable is not PrimaryRegime.UNKNOWN and self._persistence<self.configuration.minimum_persistence:
            self._persistence+=1
            return HysteresisState(self._stable,candidate,self._candidate_count,self._persistence,self._cooldown,True,"MINIMUM_PERSISTENCE_HELD")
        if self._cooldown>0:
            self._cooldown-=1; return HysteresisState(self._stable,candidate,self._candidate_count,self._persistence,self._cooldown,True,"COOLDOWN_HELD")
        if candidate is self._candidate:self._candidate_count+=1
        else:self._candidate=candidate; self._candidate_count=1
        required=self.configuration.confirmation_observations
        if winning_score>=self.configuration.entry_threshold and self._candidate_count>=required:
            self._stable=candidate; self._persistence=1; self._cooldown=self.configuration.cooldown_observations; self._unknown_count=0
            return HysteresisState(self._stable,candidate,self._candidate_count,1,self._cooldown,False,"REGIME_CHANGED")
        return HysteresisState(self._stable,candidate,self._candidate_count,self._persistence,self._cooldown,True,"CONFIRMATION_PENDING")

    def analyze(self,market:MarketDataSnapshot,structure:StructureSnapshot,features:FeatureSnapshot,*,configuration_hash:str="",temporal_feature_series:TemporalFeatureSeries|None=None,compression_configuration:CompressionConfiguration=CompressionConfiguration())->RegimeSnapshot|None:
        self.audit.record("regime_analysis_started",{"market_snapshot_id":market.snapshot_id})
        valid,reasons=self.validate_lineage(market,structure,features)
        if not valid:
            self.audit.record("regime_snapshot_rejected",{"reason":"REGIME_LINEAGE_MISMATCH","details":reasons}); return None
        trace=DecisionTraceBuilder(self.clock,deterministic_id("regime_decision",market.snapshot_id),deterministic_id("correlation",market.snapshot_id))
        trace.evaluate("lineage",DecisionStatus.PASSED,"LINEAGE_VALID","upstream snapshots share a coherent lineage")
        abnormal_reasons=[]
        if market.data_health is DataHealth.INVALID:abnormal_reasons.append("DATA_INVALID")
        if market.synchronization_status is not SynchronizationStatus.SYNCHRONIZED:abnormal_reasons.append("DATA_UNSYNCHRONIZED")
        if market.bid_ask_state.health is SpreadHealth.EXTREME:abnormal_reasons.append("EXTREME_SPREAD")
        structures=(structure.context_structure,structure.strategy_structure,structure.execution_structure)
        timeframe=(self._timeframe("context",structures[0],features),self._timeframe("strategy",structures[1],features),self._timeframe("execution",structures[2],features))
        scores,candidate,confidence_score,margin=self._composite(timeframe)
        if abnormal_reasons:candidate=PrimaryRegime.ABNORMAL; scores=ComponentScores(scores.trend,scores.range,scores.breakout,scores.transition,100.0)
        winning={PrimaryRegime.TREND:scores.trend,PrimaryRegime.RANGE:scores.range,PrimaryRegime.BREAKOUT_EXPANSION:scores.breakout,PrimaryRegime.TRANSITION:scores.transition,PrimaryRegime.ABNORMAL:scores.abnormal,PrimaryRegime.UNKNOWN:0}[candidate]
        hysteresis=self._publish(candidate,winning,scores); published=hysteresis.stable_regime
        health=RegimeHealth.HEALTHY
        if published is PrimaryRegime.UNKNOWN:health=RegimeHealth.INSUFFICIENT_EVIDENCE
        if published is PrimaryRegime.ABNORMAL:health=RegimeHealth.RESTRICTED
        if market.data_health is DataHealth.INVALID or structure.overall_structure_health is StructureHealth.INVALID_INPUT:health=RegimeHealth.INVALID_INPUT
        all_directions=[tf.direction for tf in timeframe]
        direction_candidates=[item for item in all_directions if item not in (RegimeDirection.UNKNOWN,RegimeDirection.NEUTRAL)]
        if direction_candidates:
            direction=direction_candidates[0] if all(item is direction_candidates[0] for item in direction_candidates) else RegimeDirection.MIXED
        elif all(item is RegimeDirection.NEUTRAL for item in all_directions):
            direction=RegimeDirection.NEUTRAL
        else:
            direction=RegimeDirection.UNKNOWN
        all_evidence=tuple(item for tf in timeframe for item in tf.evidence)
        supporting=tuple(item for item in all_evidence if (published is PrimaryRegime.TREND and item.evidence_code in ("DIRECTIONAL_STRUCTURE","CONFIRMED_BOS","ADX_STRENGTH","DIRECTIONAL_DISPLACEMENT")) or
            (published is PrimaryRegime.RANGE and item.evidence_code in ("SIDEWAYS_STRUCTURE","CONSOLIDATION","ADX_WEAKNESS","BANDWIDTH_COMPRESSION")) or
            (published is PrimaryRegime.BREAKOUT_EXPANSION and item.evidence_code in ("BOUNDARY_BREAK","VOLATILITY_EXPANSION","EXPANSION_DISPLACEMENT","ZONE_ROLE_FLIP")) or
            (published is PrimaryRegime.TRANSITION and item.evidence_code in ("MIXED_STRUCTURE","STRUCTURAL_SHIFT","VOLATILITY_CHANGE")))
        conflicting=tuple(item for item in all_evidence if item not in supporting and item.normalized_score>=60)
        missing=tuple(sorted(set(code for tf in timeframe for code in tf.missing_evidence)))
        reason_codes=tuple(abnormal_reasons or (("LOW_CONFIDENCE",) if candidate is PrimaryRegime.UNKNOWN and confidence_score<self.configuration.minimum_confidence else ("SCORE_MARGIN_TOO_SMALL",) if candidate is PrimaryRegime.UNKNOWN and margin<self.configuration.minimum_classification_margin else (candidate.name,)))
        coverage=_bounded(len(all_evidence)/15*100); agreement=_bounded(100-len(conflicting)*10)
        tf_agreement=_bounded(max(sum(tf.primary_candidate is regime for tf in timeframe) for regime in PrimaryRegime)/3*100)
        confidence=RegimeConfidence(0.0 if health in (RegimeHealth.INVALID_INPUT,RegimeHealth.UNKNOWN) else confidence_score,
            winning,margin,coverage,agreement,tf_agreement,min(100,self._persistence*20),health,
            ("HEALTH_CONSTRAINED",) if health is not RegimeHealth.HEALTHY else ())
        eligibility={"DIRECTIONAL_RESEARCH":EligibilityState.ELIGIBLE if published is PrimaryRegime.TREND else EligibilityState.BLOCKED,
                     "RANGE_RESEARCH":EligibilityState.ELIGIBLE if published is PrimaryRegime.RANGE else EligibilityState.BLOCKED,
                     "EXPANSION_RESEARCH":EligibilityState.ELIGIBLE if published is PrimaryRegime.BREAKOUT_EXPANSION else EligibilityState.BLOCKED}
        if published in (PrimaryRegime.TRANSITION,PrimaryRegime.UNKNOWN):eligibility={key:EligibilityState.RESTRICTED for key in eligibility}
        if published is PrimaryRegime.ABNORMAL:eligibility={key:EligibilityState.BLOCKED for key in eligibility}
        trace.evaluate("health",DecisionStatus.PASSED if health is RegimeHealth.HEALTHY else DecisionStatus.FAILED,
                       health.name,"regime health gate evaluated")
        decision_trace=trace.complete(DecisionOutcome.NO_ACTION,"classification metadata only")
        compression=HistoricalCompressionAnalyzer(compression_configuration,self.audit).analyze(temporal_feature_series) if temporal_feature_series is not None else None
        identity=deterministic_id("regime",market.snapshot_id,structure.structure_snapshot_id,features.feature_snapshot_id,
            configuration_hash,REGIME_ENGINE_VERSION,published.name,hysteresis.candidate_count,hysteresis.persistence_count,compression.evidence_id if compression else "no_temporal_series")
        result=RegimeSnapshot(identity,self.clock.now(),market.as_of_timestamp,market.experiment_id,market.dataset_id,
            market.dataset_fingerprint,market.instrument_id,market.snapshot_id,structure.structure_snapshot_id,
            features.feature_snapshot_id,candidate,published,direction,scores,confidence,*timeframe,supporting,
            conflicting,missing,reason_codes,eligibility,market.data_health,structure.overall_structure_health,
            features.health,health,hysteresis,decision_trace,market.configuration_snapshot_id,market.recovery_epoch,historical_compression=compression)
        if not self._history or self._history[-1].source_snapshot_id!=market.snapshot_id:
            duration=self._history[-1].duration_observations+1 if self._history and self._history[-1].regime is published else 1
            self._history.append(RegimeHistoryEntry(market.as_of_timestamp,published,direction,confidence.score,market.snapshot_id,duration))
            self._history=self._history[-self.configuration.maximum_history:]
        self._last_context=(market.dataset_fingerprint,configuration_hash,REGIME_ENGINE_VERSION)
        self.audit.record("regime_snapshot_created",{"regime_snapshot_id":identity,"raw":candidate.name,"published":published.name,"health":health.name})
        return result

    @property
    def history(self):return tuple(self._history)
    def recovery_state(self):return {"regime_engine_version":REGIME_ENGINE_VERSION,"stable_regime":self._stable.name,
        "candidate_regime":self._candidate.name,"candidate_count":self._candidate_count,"persistence":self._persistence,
        "cooldown":self._cooldown,"history":tuple((item.timestamp.isoformat(),item.regime.name,item.source_snapshot_id) for item in self._history),"context":self._last_context}
    def validate_recovery(self,state:Mapping[str,object],dataset_fingerprint:str,configuration_hash:str)->bool:
        return state.get("regime_engine_version")==REGIME_ENGINE_VERSION and tuple(state.get("context") or ())==(dataset_fingerprint,configuration_hash,REGIME_ENGINE_VERSION)
    def rebuild(self,timeline,*,configuration_hash=""):
        self.audit.record("regime_rebuild_started",{}); self._stable=PrimaryRegime.UNKNOWN; self._candidate=PrimaryRegime.UNKNOWN; self._candidate_count=self._persistence=self._cooldown=self._unknown_count=0; self._history=[]
        results=tuple(self.analyze(m,s,f,configuration_hash=configuration_hash) for m,s,f in timeline)
        self.audit.record("regime_rebuild_completed",{"count":len(results)}); return results
    def readiness(self,snapshot:RegimeSnapshot|None):
        ready=snapshot is not None and snapshot.regime_health is RegimeHealth.HEALTHY
        return ready,() if ready else ("regime:NOT_READY",)
