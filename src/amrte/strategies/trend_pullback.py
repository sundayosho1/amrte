"""S1 trend-pullback research strategy. Produces hypotheses, never orders."""
from __future__ import annotations

from dataclasses import dataclass,replace
from datetime import datetime
from enum import Enum,auto
from math import isfinite
from types import MappingProxyType
from typing import Mapping

from amrte.core.identity import deterministic_id
from amrte.market.events import NewsPolicyState,NewsRiskHealth
from amrte.market.features import FeatureHealth,FeatureValue
from amrte.market.intelligence import IntelligenceAvailability,IntelligenceHealth
from amrte.market.regime import EligibilityState,PrimaryRegime,RegimeDirection,RegimeHealth
from amrte.market.session import SessionHealth,TemporalRestriction
from amrte.market.structure import (Alignment,BreakDirection,ConsolidationState,ShiftDirection,
    ShiftStatus,StructuralDirection,StructureHealth,ZoneState,ZoneType)
from .framework import (ApplicabilityState,CapabilityStatus,CandidateStatus,DetectionResult,
    DetectionState,EvidenceAvailability,EvidenceCategory,EvidenceSource,QualificationResult,
    QualificationState,RequirementType,RuleType,SignalDirection,SignalEvidence,StrategyApplicability,
    StrategyEvaluationContext,StrategyFamily,StrategyIdentity,StrategyMetadata,StrategyRequirement)

S1_STRATEGY_ID="S1_TREND_PULLBACK"
S1_STRATEGY_VERSION="1.0.0"
S1_ENGINE_VERSION="1.0"

class S1State(Enum):
    NOT_APPLICABLE=auto();TREND_CONTEXT_CONFIRMED=auto();PULLBACK_WATCH=auto();PULLBACK_DETECTED=auto();PULLBACK_QUALIFIED=auto();RESUMPTION_PENDING=auto();RESUMPTION_CONFIRMED=auto();CANDIDATE=auto();SCORED=auto();RESEARCH_SIGNAL=auto();NO_ACTION=auto();REJECTED=auto();BLOCKED=auto();DEFERRED=auto();INVALIDATED=auto();EXPIRED=auto();UNKNOWN=auto()
class ContextBias(Enum):BULLISH=auto();BEARISH=auto();NEUTRAL=auto();MIXED=auto();UNKNOWN=auto()
class PullbackState(Enum):NONE=auto();POTENTIAL=auto();DEVELOPING=auto();QUALIFIED=auto();RESUMPTION_PENDING=auto();COMPLETED=auto();INVALIDATED=auto();EXPIRED=auto();REJECTED=auto();UNKNOWN=auto()
class PullbackClassification(Enum):PULLBACK=auto();NOISE=auto();CONSOLIDATION=auto();REVERSAL=auto();MIXED=auto();UNKNOWN=auto()
class StructuralIntegrity(Enum):TREND_INTACT=auto();TREND_WEAKENED=auto();STRUCTURAL_WARNING=auto();STRUCTURAL_INVALIDATION=auto();UNKNOWN=auto()
class EMAInteraction(Enum):APPROACH=auto();TOUCH=auto();PENETRATION=auto();REJECTION=auto();DEEP_PENETRATION=auto();NO_INTERACTION=auto();UNKNOWN=auto()
class ExitContextState(Enum):THESIS_INTACT=auto();THESIS_WEAKENING=auto();THESIS_INVALIDATED=auto();MOMENTUM_DERIORATING=auto();STRUCTURE_DERIORATING=auto();REGIME_CHANGED=auto();UNKNOWN=auto()
class InvalidationSeverity(Enum):WARNING=auto();HARD=auto();UNKNOWN=auto()

@dataclass(frozen=True)
class S1Configuration:
    enabled:bool=True;context_timeframe:str="H4";strategy_timeframe:str="H1";execution_timeframe:str="M15"
    supported_timeframes:tuple[str,...]=("M15","H1","H4","D1")
    allowed_regimes:tuple[str,...]=("TREND",);conditional_regimes:tuple[str,...]=("BREAKOUT_EXPANSION","TRANSITION")
    minimum_regime_confidence:float=45.0;minimum_structure_confidence:float=45.0
    minimum_adx:float=20.0;minimum_trend_persistence:int=1
    minimum_pullback_depth:float=.10;maximum_pullback_depth:float=3.0
    minimum_pullback_duration:int=1;maximum_pullback_duration:int=12
    minimum_resumption_strength:float=.10;maximum_volatility_expansion:float=3.0
    ema_approach_tolerance:float=.35;ema_touch_tolerance:float=.10;ema_deep_penetration:float=1.5
    confirmation_bars:int=1;candidate_ttl_minutes:int=60;cooldown_observations:int=0
    maximum_history:int=100;maximum_cache_entries:int=256;closed_bar_only:bool=True
    mandatory_features:tuple[str,...]=("ADX","ATR_ADJUSTED_DISPLACEMENT","VOLATILITY_EXPANSION_RATIO")
    scoring_model_id:str="AMRTE_TREND_RESEARCH_SCORE"
    configuration_snapshot_id:str="S1_DEFAULT_RESEARCH"
    def validate(self):
        errors=[];roles=(self.context_timeframe,self.strategy_timeframe,self.execution_timeframe)
        if not self.enabled:return ()
        if len(set(roles))!=3:errors.append("S1_INVALID_TIMEFRAME_HIERARCHY")
        if any(role not in self.supported_timeframes for role in roles):errors.append("S1_UNSUPPORTED_TIMEFRAME")
        if not 0<=self.minimum_regime_confidence<=100 or not 0<=self.minimum_structure_confidence<=100:errors.append("S1_INVALID_CONFIDENCE")
        if self.minimum_adx<0 or self.minimum_adx>100:errors.append("S1_INVALID_ADX")
        if self.minimum_pullback_depth<0 or self.minimum_pullback_depth>self.maximum_pullback_depth:errors.append("S1_INVALID_PULLBACK_DEPTH")
        if self.minimum_pullback_duration<1 or self.minimum_pullback_duration>self.maximum_pullback_duration:errors.append("S1_INVALID_PULLBACK_DURATION")
        if min(self.minimum_trend_persistence,self.confirmation_bars,self.candidate_ttl_minutes,self.maximum_history,self.maximum_cache_entries)<1:errors.append("S1_INVALID_POSITIVE_BOUND")
        if self.minimum_resumption_strength<0 or self.maximum_volatility_expansion<=0:errors.append("S1_INVALID_NORMALIZED_THRESHOLD")
        if not self.mandatory_features:errors.append("S1_MANDATORY_FEATURES_EMPTY")
        if not self.scoring_model_id:errors.append("S1_INVALID_SCORING_MODEL")
        return tuple(errors)

@dataclass(frozen=True)
class TrendContextEvidence:
    bias:ContextBias;context_direction:str;strategy_direction:str;regime:str
    regime_confidence:float;structure_confidence:float;adx:float|None
    ema_alignment:str;ema_slope:float|None;ema_separation:float|None
    directional_movement:str;timeframe_agreement:str;reason_codes:tuple[str,...]

@dataclass(frozen=True)
class PullbackEvidence:
    pullback_id:str;pullback_version_id:str;instrument_id:str;direction:SignalDirection
    state:PullbackState;classification:PullbackClassification;start_time_utc:datetime
    as_of_timestamp_utc:datetime;depth_atr:float|None;duration_observations:int
    quality_components:Mapping[str,float];ema_interaction:EMAInteraction
    zone_interaction:str;structural_integrity:StructuralIntegrity
    resumption_strength:float|None;evidence_references:tuple[str,...]
    configuration_snapshot_id:str
    def __post_init__(self):object.__setattr__(self,"quality_components",MappingProxyType(dict(self.quality_components)))

@dataclass(frozen=True)
class StrategyInvalidationEvidence:
    invalidation_id:str;strategy_id:str;pullback_id:str;candidate_id:str|None
    as_of_timestamp_utc:datetime;invalidation_type:str;source_module:str
    source_snapshot_id:str;severity:InvalidationSeverity;reason_codes:tuple[str,...]
    configuration_snapshot_id:str

@dataclass(frozen=True)
class StrategyExitContext:
    context_id:str;strategy_id:str;pullback_id:str;as_of_timestamp_utc:datetime
    state:ExitContextState;reason_codes:tuple[str,...];source_snapshot_ids:tuple[str,...]
    configuration_snapshot_id:str

@dataclass(frozen=True)
class S1ContinuationState:
    strategy_id:str;strategy_version:str;instrument_id:str;active_pullback_id:str|None
    pullback_state:PullbackState;pullback_start_time_utc:datetime|None;duration_observations:int
    last_evaluation_id:str|None;last_intelligence_snapshot_id:str|None
    configuration_snapshot_id:str;dataset_fingerprint:str;recovery_epoch:int

def _feature(context:StrategyEvaluationContext,role:str,name:str)->FeatureValue|None:
    values=context.market_intelligence.features.features.get(role,{})
    matches=[value for key,value in values.items() if key.split(":",1)[0]==name]
    return matches[0] if matches else None

def _number(value:FeatureValue|None)->float|None:
    if value is None or value.health not in (FeatureHealth.VALID,FeatureHealth.VALID_WITH_WARNINGS):return None
    return float(value.value) if isinstance(value.value,(int,float)) and isfinite(float(value.value)) else None

class TrendPullbackStrategy:
    def __init__(self,configuration:S1Configuration=S1Configuration(),audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit;self._states={};self._history=[];self._invalidations=[];self._cache={};self._latest={}
        identity=StrategyIdentity(S1_STRATEGY_ID,StrategyFamily.TREND,"Trend Pullback Strategy",S1_STRATEGY_VERSION,configuration_namespace="strategies.s1_trend_pullback",required_capabilities=("PHASE2_INTELLIGENCE","PROMPT12_SCORING"))
        requirements=(
          StrategyRequirement("S1_REGIME",RequirementType.MANDATORY,EvidenceSource.REGIME,"TREND_REGIME",configuration.context_timeframe),
          StrategyRequirement("S1_CONTEXT_STRUCTURE",RequirementType.MANDATORY,EvidenceSource.STRUCTURE,"DIRECTION",configuration.context_timeframe),
          StrategyRequirement("S1_STRATEGY_STRUCTURE",RequirementType.MANDATORY,EvidenceSource.STRUCTURE,"DIRECTION",configuration.strategy_timeframe),
          StrategyRequirement("S1_EXECUTION_STRUCTURE",RequirementType.MANDATORY,EvidenceSource.STRUCTURE,"DIRECTION",configuration.execution_timeframe),
          *(StrategyRequirement(f"S1_{name}",RequirementType.MANDATORY,EvidenceSource.FEATURE,name,configuration.strategy_timeframe) for name in configuration.mandatory_features),
          StrategyRequirement("S1_SESSION",RequirementType.MANDATORY,EvidenceSource.SESSION,"SESSION_CONTEXT"),
          StrategyRequirement("S1_NEWS",RequirementType.MANDATORY,EvidenceSource.NEWS_RISK,"NEWS_CONTEXT"))
        self._metadata=StrategyMetadata(identity,"Research-only trend continuation pullback hypothesis",(configuration.context_timeframe,configuration.strategy_timeframe,configuration.execution_timeframe),configuration.mandatory_features,("DIRECTION","CONSOLIDATION","BOS","SHIFTS"),("TREND",),True,True,IntelligenceHealth.HEALTHY,requirements)
    @property
    def metadata(self):return self._metadata
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
    def _structures(self,context):
        s=context.market_intelligence.structure;return s.context_structure,s.strategy_structure,s.execution_structure
    def _bias(self,context):
        intel=context.market_intelligence;c,s,e=self._structures(context);regime=intel.regime
        bullish=(c.direction is StructuralDirection.BULLISH and s.direction is StructuralDirection.BULLISH and regime.direction is RegimeDirection.BULLISH)
        bearish=(c.direction is StructuralDirection.BEARISH and s.direction is StructuralDirection.BEARISH and regime.direction is RegimeDirection.BEARISH)
        if bullish:return ContextBias.BULLISH
        if bearish:return ContextBias.BEARISH
        directions={c.direction,s.direction}
        if StructuralDirection.UNKNOWN in directions:return ContextBias.UNKNOWN
        if StructuralDirection.MIXED in directions or len(directions)>1:return ContextBias.MIXED
        return ContextBias.NEUTRAL
    def applicability(self,context):
        intel=context.market_intelligence;cfg=self.configuration;reasons=[];restrictions=[]
        if not cfg.enabled:state=ApplicabilityState.NOT_APPLICABLE;reasons=("S1_DISABLED",)
        elif intel.overall_intelligence_health in (IntelligenceHealth.UNTRUSTED,IntelligenceHealth.UNAVAILABLE,IntelligenceHealth.UNKNOWN) or intel.intelligence_availability in (IntelligenceAvailability.NOT_AVAILABLE,IntelligenceAvailability.UNKNOWN):state=ApplicabilityState.BLOCKED;reasons=("S1_INVALID_INTELLIGENCE",)
        elif intel.regime.primary_regime in (PrimaryRegime.ABNORMAL,PrimaryRegime.UNKNOWN):state=ApplicabilityState.BLOCKED;reasons=("S1_REGIME_UNSUPPORTED",)
        elif intel.regime.primary_regime is PrimaryRegime.RANGE:state=ApplicabilityState.NOT_APPLICABLE;reasons=("S1_RANGE_NOT_APPLICABLE",)
        elif intel.regime.primary_regime.name in cfg.conditional_regimes:state=ApplicabilityState.CONDITIONAL;reasons=("S1_REGIME_CONDITIONAL",)
        elif intel.regime.primary_regime.name not in cfg.allowed_regimes:state=ApplicabilityState.NOT_APPLICABLE;reasons=("S1_REGIME_UNSUPPORTED",)
        elif intel.regime.confidence.score<cfg.minimum_regime_confidence:state=ApplicabilityState.CONDITIONAL;reasons=("S1_REGIME_CONFIDENCE_LOW",)
        elif intel.session.temporal_restriction is not TemporalRestriction.ALLOW_CONTEXT:state=ApplicabilityState.BLOCKED;reasons=("S1_SESSION_RESTRICTED",);restrictions=(intel.session.temporal_restriction.name,)
        elif intel.news_risk.policy_state is not NewsPolicyState.ALLOW_CONTEXT:state=ApplicabilityState.BLOCKED;reasons=("S1_NEWS_RESTRICTED",);restrictions=(intel.news_risk.policy_state.name,)
        else:state=ApplicabilityState.APPLICABLE;reasons=("S1_APPLICABLE",)
        return StrategyApplicability(deterministic_id("s1_applicability",context.evaluation_id,state.name),S1_STRATEGY_ID,state,CapabilityStatus.SUPPORTED,tuple(reasons),tuple(restrictions))
    def trend_context(self,context):
        intel=context.market_intelligence;c,s,e=self._structures(context);bias=self._bias(context)
        adx=_number(_feature(context,"strategy","ADX"));slope=_number(_feature(context,"strategy","EMA_SLOPE"));separation=_number(_feature(context,"strategy","EMA_SEPARATION"))
        plus=_number(_feature(context,"strategy","PLUS_DI"));minus=_number(_feature(context,"strategy","MINUS_DI"))
        directional="UNAVAILABLE" if plus is None or minus is None else "BULLISH" if plus>minus else "BEARISH" if minus>plus else "NEUTRAL"
        ema="UNAVAILABLE" if slope is None and separation is None else "BULLISH" if (slope or 0)>0 and (separation or 0)>=0 else "BEARISH" if (slope or 0)<0 and (separation or 0)<=0 else "CONFLICTING"
        agreement=intel.structure.alignment.name
        reasons=(f"S1_CONTEXT_{bias.name}","S1_TREND_CONFIRMED" if bias in (ContextBias.BULLISH,ContextBias.BEARISH) else "S1_CONTEXT_CONFLICTING", "S1_ADX_SUPPORTIVE" if adx is not None and adx>=self.configuration.minimum_adx else "S1_ADX_WEAK")
        return TrendContextEvidence(bias,c.direction.name,s.direction.name,intel.regime.primary_regime.name,intel.regime.confidence.score,s.confidence.score,adx,ema,slope,separation,directional,agreement,reasons)
    def _integrity(self,context,bias):
        _,s,e=self._structures(context)
        if bias is ContextBias.BULLISH:
            if any(x.status is ShiftStatus.CONFIRMED_SHIFT and x.potential_new_direction is ShiftDirection.BEARISH_STRUCTURE_SHIFT for x in s.shifts):return StructuralIntegrity.STRUCTURAL_INVALIDATION
            if s.direction is StructuralDirection.BEARISH:return StructuralIntegrity.STRUCTURAL_INVALIDATION
        if bias is ContextBias.BEARISH:
            if any(x.status is ShiftStatus.CONFIRMED_SHIFT and x.potential_new_direction is ShiftDirection.BULLISH_STRUCTURE_SHIFT for x in s.shifts):return StructuralIntegrity.STRUCTURAL_INVALIDATION
            if s.direction is StructuralDirection.BULLISH:return StructuralIntegrity.STRUCTURAL_INVALIDATION
        if s.direction in (StructuralDirection.MIXED,StructuralDirection.SIDEWAYS):return StructuralIntegrity.STRUCTURAL_WARNING
        if s.structure_health is not StructureHealth.HEALTHY:return StructuralIntegrity.TREND_WEAKENED
        return StructuralIntegrity.TREND_INTACT
    def _pullback(self,context,trend):
        cfg=self.configuration;_,s,e=self._structures(context);direction=SignalDirection.LONG_BIAS if trend.bias is ContextBias.BULLISH else SignalDirection.SHORT_BIAS
        displacement=_number(_feature(context,"strategy","ATR_ADJUSTED_DISPLACEMENT"));execution=_number(_feature(context,"execution","ATR_ADJUSTED_DISPLACEMENT"));distance=_number(_feature(context,"strategy","PRICE_DISTANCE_EMA"));volatility=_number(_feature(context,"strategy","VOLATILITY_EXPANSION_RATIO"))
        counter=None if displacement is None else (-displacement if direction is SignalDirection.LONG_BIAS else displacement)
        resumption=None if execution is None else (execution if direction is SignalDirection.LONG_BIAS else -execution)
        state=self._states.get(context.instrument_id);continuing=state is not None and state.pullback_state not in (PullbackState.INVALIDATED,PullbackState.EXPIRED,PullbackState.REJECTED)
        duration=(state.duration_observations+1 if continuing else 1)
        start=state.pullback_start_time_utc if continuing and state.pullback_start_time_utc else context.as_of_timestamp_utc
        logical=state.active_pullback_id if continuing and state.active_pullback_id else deterministic_id("s1_pullback",context.market_intelligence.dataset_fingerprint,context.instrument_id,direction.name,start.isoformat(),cfg.configuration_snapshot_id)
        integrity=self._integrity(context,trend.bias)
        if integrity is StructuralIntegrity.STRUCTURAL_INVALIDATION:classification=PullbackClassification.REVERSAL;pb_state=PullbackState.INVALIDATED
        elif s.consolidation.state is ConsolidationState.CONSOLIDATING:classification=PullbackClassification.CONSOLIDATION;pb_state=PullbackState.REJECTED
        elif counter is None:classification=PullbackClassification.UNKNOWN;pb_state=PullbackState.UNKNOWN
        elif counter<=0:classification=PullbackClassification.NOISE;pb_state=PullbackState.NONE
        elif counter<cfg.minimum_pullback_depth:classification=PullbackClassification.NOISE;pb_state=PullbackState.POTENTIAL
        elif counter>cfg.maximum_pullback_depth:classification=PullbackClassification.REVERSAL;pb_state=PullbackState.INVALIDATED
        elif duration>cfg.maximum_pullback_duration:classification=PullbackClassification.PULLBACK;pb_state=PullbackState.EXPIRED
        else:classification=PullbackClassification.PULLBACK;pb_state=PullbackState.QUALIFIED if duration>=cfg.minimum_pullback_duration else PullbackState.DEVELOPING
        if pb_state is PullbackState.QUALIFIED:pb_state=PullbackState.COMPLETED if resumption is not None and resumption>=cfg.minimum_resumption_strength else PullbackState.RESUMPTION_PENDING
        interaction=EMAInteraction.UNKNOWN if distance is None else EMAInteraction.TOUCH if abs(distance)<=cfg.ema_touch_tolerance else EMAInteraction.APPROACH if abs(distance)<=cfg.ema_approach_tolerance else EMAInteraction.DEEP_PENETRATION if abs(distance)>=cfg.ema_deep_penetration else EMAInteraction.PENETRATION
        zone="NO_INTERACTION";active=[z for z in s.zones if z.state in (ZoneState.ACTIVE,ZoneState.TESTED,ZoneState.ROLE_FLIPPED)]
        desired=ZoneType.SUPPORT if direction is SignalDirection.LONG_BIAS else ZoneType.RESISTANCE
        if any(z.zone_type is desired for z in active):zone=f"{desired.name}_AVAILABLE"
        quality={"depth":0 if counter is None else max(0,100-abs(counter-(cfg.minimum_pullback_depth+cfg.maximum_pullback_depth)/2)*30),"duration":max(0,100-duration*3),"structural_integrity":100 if integrity is StructuralIntegrity.TREND_INTACT else 50 if integrity is StructuralIntegrity.TREND_WEAKENED else 0,"volatility":0 if volatility is None else 100 if volatility<=cfg.maximum_volatility_expansion else 0,"resumption":0 if resumption is None else max(0,min(100,resumption*50))}
        version=deterministic_id("s1_pullback_version",logical,context.market_intelligence.market_intelligence_snapshot_id,pb_state.name,counter,duration,resumption)
        return PullbackEvidence(logical,version,context.instrument_id,direction,pb_state,classification,start,context.as_of_timestamp_utc,counter,duration,quality,interaction,zone,integrity,resumption,(context.market_intelligence.structure_snapshot_id,context.market_intelligence.feature_snapshot_id,context.market_intelligence.regime_snapshot_id),cfg.configuration_snapshot_id)
    def _evidence(self,context,trend,pullback):
        items=[]
        def add(kind,category,source,snapshot,observed,strength,code,timeframe=None,direction=None):
            items.append(SignalEvidence(deterministic_id("s1_evidence",context.evaluation_id,kind,code),kind,category,source,snapshot,context.instrument_id,timeframe,observed,None,direction or pullback.direction,strength,EvidenceAvailability.AVAILABLE if observed is not None else EvidenceAvailability.UNAVAILABLE,"HEALTHY" if observed is not None else "UNAVAILABLE",code,(pullback.pullback_id,*pullback.evidence_references)))
        add("CONTEXT_TREND",EvidenceCategory.SUPPORTING,EvidenceSource.REGIME,context.market_intelligence.regime_snapshot_id,trend.bias.name,trend.regime_confidence,"S1_TREND_CONFIRMED",self.configuration.context_timeframe)
        add("STRUCTURE",EvidenceCategory.SUPPORTING if pullback.structural_integrity is StructuralIntegrity.TREND_INTACT else EvidenceCategory.DISQUALIFYING,EvidenceSource.STRUCTURE,context.market_intelligence.structure_snapshot_id,pullback.structural_integrity.name,trend.structure_confidence,"S1_STRUCTURE_SUPPORTIVE" if pullback.structural_integrity is StructuralIntegrity.TREND_INTACT else "S1_STRUCTURE_INVALIDATED",self.configuration.strategy_timeframe)
        add("PULLBACK_QUALITY",EvidenceCategory.SUPPORTING if pullback.classification is PullbackClassification.PULLBACK else EvidenceCategory.MISSING,EvidenceSource.STRATEGY_DERIVED,context.market_intelligence.market_intelligence_snapshot_id,pullback.depth_atr,sum(pullback.quality_components.values())/len(pullback.quality_components),"S1_PULLBACK_DETECTED" if pullback.classification is PullbackClassification.PULLBACK else "S1_PULLBACK_NOT_QUALIFIED",self.configuration.strategy_timeframe)
        add("MOMENTUM_RESUMPTION",EvidenceCategory.SUPPORTING if pullback.state is PullbackState.COMPLETED else EvidenceCategory.MISSING,EvidenceSource.FEATURE,context.market_intelligence.feature_snapshot_id,pullback.resumption_strength,0 if pullback.resumption_strength is None else min(100,pullback.resumption_strength*50),"S1_RESUMPTION_CONFIRMED" if pullback.state is PullbackState.COMPLETED else "S1_RESUMPTION_MISSING",self.configuration.execution_timeframe)
        volatility=_number(_feature(context,"strategy","VOLATILITY_EXPANSION_RATIO"));add("VOLATILITY",EvidenceCategory.SUPPORTING if volatility is not None and volatility<=self.configuration.maximum_volatility_expansion else EvidenceCategory.CONFLICTING,EvidenceSource.FEATURE,context.market_intelligence.feature_snapshot_id,volatility,None if volatility is None else 100 if volatility<=self.configuration.maximum_volatility_expansion else 20,"S1_VOLATILITY_ACCEPTABLE" if volatility is not None and volatility<=self.configuration.maximum_volatility_expansion else "S1_VOLATILITY_CONFLICT",self.configuration.strategy_timeframe)
        for name in ("ROC","MACD_HISTOGRAM","MACD_HISTOGRAM_SLOPE","RSI","CANDLE_BODY_RATIO"):
            value=_number(_feature(context,"execution",name))
            if value is None:continue
            directional=value if pullback.direction is SignalDirection.LONG_BIAS else -value
            supportive=(name in ("RSI","CANDLE_BODY_RATIO")) or directional>=0
            add(f"MOMENTUM_{name}",EvidenceCategory.SUPPORTING if supportive else EvidenceCategory.CONFLICTING,EvidenceSource.FEATURE,context.market_intelligence.feature_snapshot_id,value,max(0,min(100,50+directional*10)) if name not in ("RSI","CANDLE_BODY_RATIO") else max(0,min(100,value)),"S1_MOMENTUM_SUPPORTIVE" if supportive else "S1_MOMENTUM_CONFLICT",self.configuration.execution_timeframe)
        return tuple(items)
    def detect(self,context):
        self._record("s1_evaluation_started",{"evaluation_id":context.evaluation_id,"instrument_id":context.instrument_id})
        trend=self.trend_context(context)
        if trend.bias not in (ContextBias.BULLISH,ContextBias.BEARISH):status=DetectionState.NOT_DETECTED;evidence=();missing=();conflicts=();reason="S1_NO_TREND"
        else:
            pullback=self._pullback(context,trend);self._latest[context.evaluation_id]=(trend,pullback);evidence=self._evidence(context,trend,pullback)
            missing=tuple(x for x in evidence if x.category is EvidenceCategory.MISSING);conflicts=tuple(x for x in evidence if x.category in (EvidenceCategory.CONFLICTING,EvidenceCategory.DISQUALIFYING))
            if pullback.state is PullbackState.INVALIDATED:status=DetectionState.BLOCKED;reason="S1_PULLBACK_INVALIDATED"
            elif pullback.state in (PullbackState.UNKNOWN,):status=DetectionState.INCOMPLETE;reason="S1_INSUFFICIENT_EVIDENCE"
            elif pullback.state is PullbackState.COMPLETED:status=DetectionState.DETECTED;reason="S1_RESUMPTION_CONFIRMED"
            else:status=DetectionState.NOT_DETECTED;reason="S1_RESUMPTION_PENDING" if pullback.state is PullbackState.RESUMPTION_PENDING else "S1_NO_QUALIFIED_PULLBACK"
            self._update_state(context,pullback)
        result=DetectionResult(deterministic_id("s1_detection",context.evaluation_id,status.name),S1_STRATEGY_ID,context.instrument_id,context.as_of_timestamp_utc,status,evidence,missing,conflicts,context.market_intelligence.market_intelligence_snapshot_id,context.strategy_configuration_snapshot_id)
        self._record("s1_evaluation_completed",{"evaluation_id":context.evaluation_id,"status":status.name,"reason":reason});return result
    def qualify(self,context,detection):
        if detection.status is not DetectionState.DETECTED:return QualificationResult(deterministic_id("s1_qualification",detection.detection_id),S1_STRATEGY_ID,QualificationState.INCOMPLETE,(),(),(),("S1_DETECTION_NOT_COMPLETE",),())
        trend,pullback=self._latest[context.evaluation_id];passed=[];failed=[];conditional=[];blocking=[]
        checks=(("S1_CONTEXT_TREND",trend.bias in (ContextBias.BULLISH,ContextBias.BEARISH)),("S1_PULLBACK_QUALIFIED",pullback.classification is PullbackClassification.PULLBACK),("S1_STRUCTURE_INTACT",pullback.structural_integrity is StructuralIntegrity.TREND_INTACT),("S1_RESUMPTION_CONFIRMED",pullback.state is PullbackState.COMPLETED))
        for name,ok in checks:(passed if ok else failed).append(name)
        if context.market_intelligence.session.temporal_restriction is not TemporalRestriction.ALLOW_CONTEXT:blocking.append("S1_SESSION_RESTRICTED")
        if context.market_intelligence.news_risk.policy_state is not NewsPolicyState.ALLOW_CONTEXT:blocking.append("S1_NEWS_RESTRICTED")
        if blocking:status=QualificationState.BLOCKED
        elif failed:status=QualificationState.REJECTED
        elif context.market_intelligence.overall_intelligence_health is IntelligenceHealth.DEGRADED:status=QualificationState.CONDITIONALLY_QUALIFIED;conditional.append("S1_DEGRADED_INTELLIGENCE")
        else:status=QualificationState.QUALIFIED
        return QualificationResult(deterministic_id("s1_qualification",detection.detection_id,status.name),S1_STRATEGY_ID,status,tuple(passed),tuple(failed),tuple(conditional),(),tuple(blocking))
    def direction(self,context,detection):
        latest=self._latest.get(context.evaluation_id);return latest[1].direction if latest else SignalDirection.UNKNOWN
    def _update_state(self,context,pullback):
        state=S1ContinuationState(S1_STRATEGY_ID,S1_STRATEGY_VERSION,context.instrument_id,pullback.pullback_id,pullback.state,pullback.start_time_utc,pullback.duration_observations,context.evaluation_id,context.market_intelligence.market_intelligence_snapshot_id,self.configuration.configuration_snapshot_id,context.market_intelligence.dataset_fingerprint,context.recovery_epoch)
        self._states[context.instrument_id]=state
        if not self._history or self._history[-1].pullback_version_id!=pullback.pullback_version_id:self._history.append(pullback);self._history=self._history[-self.configuration.maximum_history:]
        event={PullbackState.POTENTIAL:"s1_pullback_started",PullbackState.DEVELOPING:"s1_pullback_updated",PullbackState.QUALIFIED:"s1_pullback_qualified",PullbackState.RESUMPTION_PENDING:"s1_resumption_pending",PullbackState.COMPLETED:"s1_resumption_confirmed",PullbackState.EXPIRED:"s1_pullback_expired",PullbackState.REJECTED:"s1_pullback_rejected"}.get(pullback.state)
        if event:self._record(event,{"pullback_id":pullback.pullback_id,"version_id":pullback.pullback_version_id})
        if pullback.state is PullbackState.INVALIDATED:
            item=StrategyInvalidationEvidence(deterministic_id("s1_invalidation",pullback.pullback_version_id),S1_STRATEGY_ID,pullback.pullback_id,None,context.as_of_timestamp_utc,"STRUCTURAL_OR_DEPTH_INVALIDATION","Prompt6/13",context.market_intelligence.structure_snapshot_id,InvalidationSeverity.HARD,("S1_STRUCTURE_INVALIDATED",),self.configuration.configuration_snapshot_id)
            if not self._invalidations or self._invalidations[-1].invalidation_id!=item.invalidation_id:self._invalidations.append(item);self._invalidations=self._invalidations[-self.configuration.maximum_history:];self._record("s1_pullback_invalidated",{"pullback_id":pullback.pullback_id})
    def exit_context(self,context):
        latest=self._latest.get(context.evaluation_id)
        if not latest:return StrategyExitContext(deterministic_id("s1_exit",context.evaluation_id,"unknown"),S1_STRATEGY_ID,"",context.as_of_timestamp_utc,ExitContextState.UNKNOWN,("S1_NO_ACTIVE_PULLBACK",),(context.market_intelligence.market_intelligence_snapshot_id,),self.configuration.configuration_snapshot_id)
        pullback=latest[1];state=ExitContextState.THESIS_INVALIDATED if pullback.state is PullbackState.INVALIDATED else ExitContextState.THESIS_WEAKENING if pullback.structural_integrity is not StructuralIntegrity.TREND_INTACT else ExitContextState.THESIS_INTACT
        return StrategyExitContext(deterministic_id("s1_exit",pullback.pullback_version_id,state.name),S1_STRATEGY_ID,pullback.pullback_id,context.as_of_timestamp_utc,state,(f"S1_{state.name}",),pullback.evidence_references,self.configuration.configuration_snapshot_id)
    @property
    def pullback_history(self):return tuple(self._history)
    @property
    def invalidations(self):return tuple(self._invalidations)
    def state(self,instrument_id):return self._states.get(instrument_id)
    def recovery_state(self):
        return {"s1_engine_version":S1_ENGINE_VERSION,"strategy_version":S1_STRATEGY_VERSION,"configuration_snapshot_id":self.configuration.configuration_snapshot_id,"states":tuple((key,value.dataset_fingerprint,value.recovery_epoch,value.active_pullback_id,value.pullback_state.name,value.last_intelligence_snapshot_id) for key,value in sorted(self._states.items()))}
    def validate_recovery(self,state,dataset_fingerprint,instrument_id,recovery_epoch):
        if state.get("s1_engine_version")!=S1_ENGINE_VERSION or state.get("strategy_version")!=S1_STRATEGY_VERSION or state.get("configuration_snapshot_id")!=self.configuration.configuration_snapshot_id:return False
        return any(row[0]==instrument_id and row[1]==dataset_fingerprint and row[2]==recovery_epoch and row[4] in PullbackState.__members__ for row in state.get("states",()))

def register_s1(registry,configuration:S1Configuration=S1Configuration(),audit=None):
    strategy=TrendPullbackStrategy(configuration,audit);registry.register(strategy);return strategy
