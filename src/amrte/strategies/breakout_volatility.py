"""S2 compression-breakout research strategy; no executable trading capability."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum,auto
from math import isfinite
from types import MappingProxyType

from amrte.core.identity import deterministic_id
from amrte.market.events import NewsPolicyState
from amrte.market.features import FeatureHealth
from amrte.market.intelligence import IntelligenceAvailability,IntelligenceHealth
from amrte.market.regime import CompressionState,PrimaryRegime
from amrte.market.session import TemporalRestriction
from amrte.market.structure import (BreakConfirmation,BreakDirection,ShiftDirection,ShiftStatus,
    StructuralDirection,ZoneState,ZoneType)
from .framework import *

S2_BASE_ID="S2_BREAKOUT_VOLATILITY_EXPANSION";S2_VERSION="1.0.0";S2_ENGINE_VERSION="1.0"
class S2Variant(Enum):IMMEDIATE=auto();RETEST=auto()
class BreakoutDirection(Enum):BULLISH_BREAKOUT=auto();BEARISH_BREAKOUT=auto()
class BreakType(Enum):WICK_TEST=auto();WICK_BREAK=auto();CLOSE_BREAK=auto();CONFIRMED_BREAK=auto()
class BreakoutState(Enum):POTENTIAL=auto();DETECTED=auto();CONFIRMATION_PENDING=auto();CONFIRMED=auto();FAILED=auto();FALSE_BREAK=auto();INVALIDATED=auto();EXPIRED=auto();UNKNOWN=auto()
class RetestState(Enum):NOT_STARTED=auto();WAITING=auto();APPROACHING=auto();TESTING=auto();HELD=auto();FAILED=auto();RESUMPTION_PENDING=auto();RESUMPTION_CONFIRMED=auto();EXPIRED=auto();UNKNOWN=auto()
class BreakoutHealth(Enum):HEALTHY=auto();DEGRADED=auto();INCOMPLETE=auto();INVALID=auto();UNKNOWN=auto()

@dataclass(frozen=True)
class S2Configuration:
    enabled:bool=True;variant:S2Variant=S2Variant.IMMEDIATE;immediate_enabled:bool=True;retest_enabled:bool=True
    context_timeframe:str="H4";breakout_timeframe:str="H1";confirmation_timeframe:str="M15"
    supported_timeframes:tuple[str,...]=("M15","H1","H4","D1")
    strict_compression:bool=True;minimum_compression_score:float=70;minimum_compression_bars:int=3;maximum_compression_lookback:int=12
    minimum_penetration:float=0.0;minimum_expansion_ratio:float=1.1;minimum_displacement:float=.10
    wick_break_allowed:bool=False;confirmation_bars:int=1
    minimum_retest_delay:int=1;maximum_retest_bars:int=8;retest_tolerance:float=.5
    candidate_ttl_minutes:int=60;maximum_history:int=100;configuration_snapshot_id:str="S2_DEFAULT_RESEARCH"
    def validate(self):
        errors=[];roles=(self.context_timeframe,self.breakout_timeframe,self.confirmation_timeframe)
        if self.enabled and not (self.immediate_enabled or self.retest_enabled):errors.append("S2_NO_VARIANT_ENABLED")
        if len(set(roles))!=3 or any(role not in self.supported_timeframes for role in roles):errors.append("S2_INVALID_TIMEFRAME_ROLES")
        if self.minimum_compression_bars<1 or self.maximum_compression_lookback<self.minimum_compression_bars:errors.append("S2_INVALID_COMPRESSION_WINDOW")
        if not 0<=self.minimum_compression_score<=100:errors.append("S2_INVALID_COMPRESSION_SCORE")
        if min(self.minimum_penetration,self.minimum_displacement,self.retest_tolerance)<0 or self.minimum_expansion_ratio<=0:errors.append("S2_INVALID_NORMALIZED_THRESHOLD")
        if self.confirmation_bars<1 or self.minimum_retest_delay<0 or self.maximum_retest_bars<self.minimum_retest_delay:errors.append("S2_INVALID_CONFIRMATION_WINDOW")
        if min(self.candidate_ttl_minutes,self.maximum_history)<1:errors.append("S2_INVALID_BOUND")
        if self.variant is S2Variant.IMMEDIATE and not self.immediate_enabled:errors.append("S2_SELECTED_VARIANT_DISABLED")
        if self.variant is S2Variant.RETEST and not self.retest_enabled:errors.append("S2_SELECTED_VARIANT_DISABLED")
        return tuple(errors)

@dataclass(frozen=True)
class BoundaryEvidence:
    boundary_id:str;source_type:str;source_id:str;direction:BreakoutDirection
    level:float;quality:float;source_snapshot_id:str;available_at_utc:datetime;reason_codes:tuple[str,...]

@dataclass(frozen=True)
class BreakoutEvent:
    breakout_event_id:str;instrument_id:str;direction:BreakoutDirection;compression_evidence_id:str
    boundary_id:str;detection_time_utc:datetime;confirmation_time_utc:datetime|None
    break_type:BreakType;penetration_evidence:float;close_evidence:bool
    expansion_evidence:float|None;displacement_evidence:float|None
    supporting_evidence:tuple[str,...];conflicting_evidence:tuple[str,...]
    health:BreakoutHealth;status:BreakoutState;market_intelligence_snapshot_id:str
    configuration_snapshot_id:str;recovery_epoch:int

@dataclass(frozen=True)
class RetestEvidence:
    retest_id:str;breakout_event_id:str;state:RetestState;observations_since_break:int
    role_reversal:bool;hold_quality:float;resumption_strength:float|None
    as_of_timestamp_utc:datetime;reason_codes:tuple[str,...]

@dataclass(frozen=True)
class BreakoutInvalidationEvidence:
    invalidation_id:str;breakout_event_id:str;as_of_timestamp_utc:datetime
    cause:str;source_snapshot_id:str;boundary_id:str;reference_value:float
    confirmed_at_utc:datetime;reason_codes:tuple[str,...]

def _feature(context,role,name):
    for key,value in context.market_intelligence.features.features.get(role,{}).items():
        if key.split(":",1)[0]==name and value.health in (FeatureHealth.VALID,FeatureHealth.VALID_WITH_WARNINGS) and isinstance(value.value,(int,float)) and isfinite(float(value.value)):return float(value.value)
    return None

class BreakoutVolatilityStrategy:
    def __init__(self,configuration:S2Configuration=S2Configuration(),audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit;self._events={};self._retests={};self._history=[];self._invalidations=[];self._latest={}
        suffix=configuration.variant.name;strategy_id=f"{S2_BASE_ID}_{suffix}"
        self._metadata=StrategyMetadata(StrategyIdentity(strategy_id,StrategyFamily.BREAKOUT,f"Breakout & Volatility Expansion — {suffix.title()}",S2_VERSION,configuration_namespace=f"strategies.s2.{suffix.lower()}",required_capabilities=("PHASE2_INTELLIGENCE","PROMPT12_SCORING")),"Strict historical-compression breakout research",(configuration.context_timeframe,configuration.breakout_timeframe,configuration.confirmation_timeframe),("VOLATILITY_EXPANSION_RATIO","ATR_ADJUSTED_DISPLACEMENT"),("BOUNDARY","BOS"),("BREAKOUT_EXPANSION","RANGE","TRANSITION","TREND"),True,True,IntelligenceHealth.HEALTHY,(
          StrategyRequirement("S2_COMPRESSION",RequirementType.MANDATORY,EvidenceSource.REGIME,"HISTORICAL_COMPRESSION",configuration.breakout_timeframe),
          StrategyRequirement("S2_BOUNDARY",RequirementType.MANDATORY,EvidenceSource.STRUCTURE,"BOUNDARY",configuration.breakout_timeframe),
          StrategyRequirement("S2_EXPANSION",RequirementType.MANDATORY,EvidenceSource.FEATURE,"VOLATILITY_EXPANSION_RATIO",configuration.breakout_timeframe),
          StrategyRequirement("S2_DISPLACEMENT",RequirementType.MANDATORY,EvidenceSource.FEATURE,"ATR_ADJUSTED_DISPLACEMENT",configuration.breakout_timeframe)))
    @property
    def metadata(self):return self._metadata
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
    def applicability(self,context):
        intel=context.market_intelligence;regime=intel.regime.primary_regime
        if not self.configuration.enabled:return self._app(context,ApplicabilityState.NOT_APPLICABLE,"S2_DISABLED")
        if intel.intelligence_availability in (IntelligenceAvailability.NOT_AVAILABLE,IntelligenceAvailability.UNKNOWN) or intel.overall_intelligence_health in (IntelligenceHealth.UNTRUSTED,IntelligenceHealth.UNAVAILABLE,IntelligenceHealth.UNKNOWN):return self._app(context,ApplicabilityState.BLOCKED,"S2_INVALID_INTELLIGENCE")
        if regime in (PrimaryRegime.ABNORMAL,PrimaryRegime.UNKNOWN):return self._app(context,ApplicabilityState.BLOCKED,"S2_REGIME_BLOCKED")
        if intel.session.temporal_restriction is not TemporalRestriction.ALLOW_CONTEXT:return self._app(context,ApplicabilityState.BLOCKED,"S2_SESSION_RESTRICTED")
        if intel.news_risk.policy_state is not NewsPolicyState.ALLOW_CONTEXT:return self._app(context,ApplicabilityState.BLOCKED,"S2_NEWS_RESTRICTED")
        compression=intel.regime.historical_compression
        if compression is None:return self._app(context,ApplicabilityState.BLOCKED,"S2_COMPRESSION_EVIDENCE_UNAVAILABLE")
        if self.configuration.strict_compression and compression.compression_state is not CompressionState.CONFIRMED:return self._app(context,ApplicabilityState.NOT_APPLICABLE,"S2_COMPRESSION_NOT_CONFIRMED")
        return self._app(context,ApplicabilityState.CONDITIONAL if regime is PrimaryRegime.TRANSITION else ApplicabilityState.APPLICABLE,"S2_APPLICABLE")
    def _app(self,context,state,reason):return StrategyApplicability(deterministic_id("s2_app",context.evaluation_id,state.name),context.strategy_id,state,CapabilityStatus.SUPPORTED,(reason,),())
    def _boundary(self,context):
        structure=context.market_intelligence.structure.strategy_structure
        breaks=[item for item in structure.breaks if item.confirmation_status and item.break_timestamp<=context.as_of_timestamp_utc]
        if not breaks:return None,None
        event=sorted(breaks,key=lambda item:(item.break_timestamp,item.break_id))[-1]
        direction=BreakoutDirection.BULLISH_BREAKOUT if event.direction is BreakDirection.BULLISH_BOS else BreakoutDirection.BEARISH_BREAKOUT
        boundary=BoundaryEvidence(event.reference_swing_id,"PROMPT6_SWING",event.reference_swing_id,direction,event.reference_level,event.confidence,context.market_intelligence.structure_snapshot_id,event.break_timestamp,("S2_AUTHORITATIVE_BOUNDARY",))
        return boundary,event
    def _event(self,context):
        compression=context.market_intelligence.regime.historical_compression;boundary,structural_break=self._boundary(context)
        if not compression or not boundary:return None
        expansion=_feature(context,"strategy","VOLATILITY_EXPANSION_RATIO");displacement=_feature(context,"strategy","ATR_ADJUSTED_DISPLACEMENT")
        directional=None if displacement is None else displacement if boundary.direction is BreakoutDirection.BULLISH_BREAKOUT else -displacement
        break_type=BreakType.WICK_BREAK if structural_break.confirmation_type is BreakConfirmation.WICK_BREAK else BreakType.CLOSE_BREAK if structural_break.confirmation_type is BreakConfirmation.CLOSE_BREAK else BreakType.CONFIRMED_BREAK
        wick_blocked=break_type is BreakType.WICK_BREAK and not self.configuration.wick_break_allowed
        opposing_shift=any(item.status is ShiftStatus.CONFIRMED_SHIFT and ((boundary.direction is BreakoutDirection.BULLISH_BREAKOUT and item.potential_new_direction is ShiftDirection.BEARISH_STRUCTURE_SHIFT) or (boundary.direction is BreakoutDirection.BEARISH_BREAKOUT and item.potential_new_direction is ShiftDirection.BULLISH_STRUCTURE_SHIFT)) for item in context.market_intelligence.structure.strategy_structure.shifts)
        confirmed=not wick_blocked and structural_break.penetration>=self.configuration.minimum_penetration and expansion is not None and expansion>=self.configuration.minimum_expansion_ratio and directional is not None and directional>=self.configuration.minimum_displacement and not opposing_shift
        status=BreakoutState.FALSE_BREAK if opposing_shift else BreakoutState.CONFIRMATION_PENDING if not confirmed else BreakoutState.CONFIRMED
        logical=deterministic_id("s2_breakout",context.market_intelligence.dataset_fingerprint,context.instrument_id,compression.evidence_id,boundary.boundary_id,boundary.direction.name,self.configuration.configuration_snapshot_id)
        event=BreakoutEvent(logical,context.instrument_id,boundary.direction,compression.evidence_id,boundary.boundary_id,structural_break.break_timestamp,context.as_of_timestamp_utc if confirmed else None,break_type,structural_break.penetration,break_type is not BreakType.WICK_BREAK,expansion,directional,(compression.evidence_id,boundary.boundary_id,structural_break.break_id),(("S2_FALSE_BREAK",) if opposing_shift else ()),BreakoutHealth.HEALTHY if confirmed else BreakoutHealth.INCOMPLETE,status,context.market_intelligence.market_intelligence_snapshot_id,self.configuration.configuration_snapshot_id,context.recovery_epoch)
        self._events[context.instrument_id]=event;self._history.append(event);self._history=self._history[-self.configuration.maximum_history:]
        if opposing_shift:
            invalid=BreakoutInvalidationEvidence(deterministic_id("s2_invalidation",logical,context.market_intelligence.structure_snapshot_id),logical,context.as_of_timestamp_utc,"OPPOSING_STRUCTURE",context.market_intelligence.structure_snapshot_id,boundary.boundary_id,boundary.level,context.as_of_timestamp_utc,("S2_FALSE_BREAK",))
            self._invalidations.append(invalid);self._invalidations=self._invalidations[-self.configuration.maximum_history:]
        return event
    def _retest(self,context,event):
        prior=self._retests.get(event.breakout_event_id);count=(prior.observations_since_break+1 if prior else 1)
        zones=context.market_intelligence.structure.execution_structure.zones
        desired=ZoneType.SUPPORT if event.direction is BreakoutDirection.BULLISH_BREAKOUT else ZoneType.RESISTANCE
        role=any(zone.zone_type is desired and zone.state is ZoneState.ROLE_FLIPPED for zone in zones)
        displacement=_feature(context,"execution","ATR_ADJUSTED_DISPLACEMENT");directional=None if displacement is None else displacement if event.direction is BreakoutDirection.BULLISH_BREAKOUT else -displacement
        if count>self.configuration.maximum_retest_bars:state=RetestState.EXPIRED
        elif not role:state=RetestState.WAITING
        elif directional is None or directional<self.configuration.minimum_displacement:state=RetestState.RESUMPTION_PENDING
        else:state=RetestState.RESUMPTION_CONFIRMED
        identity=deterministic_id("s2_retest",event.breakout_event_id,state.name,count,context.market_intelligence.structure_snapshot_id)
        result=RetestEvidence(identity,event.breakout_event_id,state,count,role,100 if role else 0,directional,context.as_of_timestamp_utc,(f"S2_RETEST_{state.name}",));self._retests[event.breakout_event_id]=result;return result
    def _evidence(self,context,event,retest=None):
        compression=context.market_intelligence.regime.historical_compression;direction=SignalDirection.LONG_BIAS if event.direction is BreakoutDirection.BULLISH_BREAKOUT else SignalDirection.SHORT_BIAS;items=[]
        def add(kind,source,snapshot,value,strength,code,category=EvidenceCategory.SUPPORTING):items.append(SignalEvidence(deterministic_id("s2_evidence",context.evaluation_id,kind,code),kind,category,source,snapshot,context.instrument_id,self.configuration.breakout_timeframe,value,None,direction,strength,EvidenceAvailability.AVAILABLE if value is not None else EvidenceAvailability.UNAVAILABLE,"HEALTHY" if value is not None else "UNAVAILABLE",code,(event.breakout_event_id,compression.evidence_id)))
        add("COMPRESSION_QUALITY",EvidenceSource.REGIME,context.market_intelligence.regime_snapshot_id,compression.compression_state.name,compression.compression_score,"S2_COMPRESSION_CONFIRMED")
        add("STRUCTURE_BOUNDARY",EvidenceSource.STRUCTURE,context.market_intelligence.structure_snapshot_id,event.boundary_id,80,"S2_BOUNDARY_VALID")
        add("BREAK_QUALITY",EvidenceSource.STRUCTURE,context.market_intelligence.structure_snapshot_id,event.penetration_evidence,min(100,event.penetration_evidence*100),"S2_BREAK_CONFIRMED")
        add("VOLATILITY_EXPANSION",EvidenceSource.FEATURE,context.market_intelligence.feature_snapshot_id,event.expansion_evidence,min(100,(event.expansion_evidence or 0)*50),"S2_EXPANSION_CONFIRMED")
        add("MOMENTUM_DISPLACEMENT",EvidenceSource.FEATURE,context.market_intelligence.feature_snapshot_id,event.displacement_evidence,min(100,(event.displacement_evidence or 0)*50),"S2_DISPLACEMENT_SUPPORT")
        if retest:add("RETEST_QUALITY",EvidenceSource.STRUCTURE,context.market_intelligence.structure_snapshot_id,retest.state.name,retest.hold_quality,"S2_RETEST_HELD")
        return tuple(items)
    def detect(self,context):
        self._record("s2_evaluation_started",{"evaluation_id":context.evaluation_id,"variant":self.configuration.variant.name});event=self._event(context)
        if event is None:status=DetectionState.INCOMPLETE;evidence=();reason="S2_NO_BOUNDARY"
        elif event.status is BreakoutState.FALSE_BREAK:status=DetectionState.BLOCKED;evidence=self._evidence(context,event);reason="S2_FALSE_BREAK"
        elif event.status is not BreakoutState.CONFIRMED:status=DetectionState.NOT_DETECTED;evidence=self._evidence(context,event);reason="S2_CONFIRMATION_PENDING"
        elif self.configuration.variant is S2Variant.IMMEDIATE:status=DetectionState.DETECTED;evidence=self._evidence(context,event);reason="S2_IMMEDIATE_CONFIRMED";self._latest[context.evaluation_id]=(event,None)
        else:
            retest=self._retest(context,event);evidence=self._evidence(context,event,retest);self._latest[context.evaluation_id]=(event,retest)
            status=DetectionState.DETECTED if retest.state is RetestState.RESUMPTION_CONFIRMED else DetectionState.NOT_DETECTED;reason=f"S2_RETEST_{retest.state.name}"
        self._record("s2_evaluation_completed",{"evaluation_id":context.evaluation_id,"status":status.name,"reason":reason})
        return DetectionResult(deterministic_id("s2_detection",context.evaluation_id,status.name,self.configuration.variant.name),context.strategy_id,context.instrument_id,context.as_of_timestamp_utc,status,evidence,tuple(x for x in evidence if x.availability is not EvidenceAvailability.AVAILABLE),tuple(x for x in evidence if x.category in (EvidenceCategory.CONFLICTING,EvidenceCategory.DISQUALIFYING)),context.market_intelligence.market_intelligence_snapshot_id,context.strategy_configuration_snapshot_id)
    def qualify(self,context,detection):
        latest=self._latest.get(context.evaluation_id)
        if detection.status is not DetectionState.DETECTED or latest is None:return QualificationResult(deterministic_id("s2_qualification",detection.detection_id),context.strategy_id,QualificationState.INCOMPLETE,(),(),(),("S2_DETECTION_INCOMPLETE",),())
        event,retest=latest;passed=("S2_COMPRESSION_CONFIRMED","S2_BOUNDARY_VALID","S2_BREAK_CONFIRMED","S2_EXPANSION_CONFIRMED","S2_DISPLACEMENT_SUPPORT")+(("S2_RETEST_RESUMPTION_CONFIRMED",) if retest else ())
        return QualificationResult(deterministic_id("s2_qualification",detection.detection_id,self.configuration.variant.name),context.strategy_id,QualificationState.QUALIFIED,passed,(),(),(),())
    def direction(self,context,detection):
        event=self._latest.get(context.evaluation_id,(None,None))[0]
        if not event:return SignalDirection.UNKNOWN
        return SignalDirection.LONG_BIAS if event.direction is BreakoutDirection.BULLISH_BREAKOUT else SignalDirection.SHORT_BIAS
    @property
    def breakout_history(self):return tuple(self._history)
    @property
    def invalidations(self):return tuple(self._invalidations)
    def recovery_state(self):return {"s2_engine_version":S2_ENGINE_VERSION,"strategy_version":S2_VERSION,"configuration_snapshot_id":self.configuration.configuration_snapshot_id,"events":tuple((key,value.breakout_event_id,value.status.name) for key,value in sorted(self._events.items())),"retests":tuple((key,value.retest_id,value.state.name) for key,value in sorted(self._retests.items()))}
    def validate_recovery(self,state):return state.get("s2_engine_version")==S2_ENGINE_VERSION and state.get("strategy_version")==S2_VERSION and state.get("configuration_snapshot_id")==self.configuration.configuration_snapshot_id

def register_s2(registry,configuration:S2Configuration=S2Configuration(),audit=None):
    strategy=BreakoutVolatilityStrategy(configuration,audit);registry.register(strategy);return strategy
