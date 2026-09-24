"""S3 range/mean-reversion research strategy; never creates executable actions."""
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
from amrte.market.regime import PrimaryRegime
from amrte.market.session import TemporalRestriction
from amrte.market.structure import ConsolidationState,StructuralDirection,ZoneState,ZoneType
from .framework import *

S3_STRATEGY_ID="S3_RANGE_MEAN_REVERSION";S3_VERSION="1.0.0";S3_ENGINE_VERSION="1.0"

class S3State(Enum):
    NOT_APPLICABLE=auto();RANGE_CANDIDATE=auto();RANGE_CONFIRMED=auto();BOUNDARY_WATCH=auto();EXTREME_DETECTED=auto();REJECTION_PENDING=auto();REJECTION_CONFIRMED=auto();REENTRY_PENDING=auto();REVERSION_CONFIRMED=auto();CANDIDATE=auto();SCORED=auto();RESEARCH_SIGNAL=auto();NO_ACTION=auto();RANGE_WEAKENING=auto();BREAKOUT_RISK=auto();REJECTED=auto();BLOCKED=auto();INVALIDATED=auto();EXPIRED=auto();INCOMPLETE=auto();UNKNOWN=auto()
class RangeState(Enum):FORMING=auto();CONFIRMED=auto();MATURE=auto();WEAKENING=auto();BREAKOUT_RISK=auto();BROKEN=auto();INVALIDATED=auto();EXPIRED=auto();UNKNOWN=auto()
class RangeHealth(Enum):HEALTHY=auto();DEGRADED=auto();WEAKENING=auto();BREAKOUT_RISK=auto();BROKEN=auto();INVALID=auto();UNKNOWN=auto()
class RangeMaturity(Enum):NEW_RANGE=auto();DEVELOPING_RANGE=auto();MATURE_RANGE=auto();AGING_RANGE=auto()
class BoundarySide(Enum):LOWER_BOUNDARY=auto();UPPER_BOUNDARY=auto();NONE=auto();UNKNOWN=auto()
class BoundaryHealth(Enum):HEALTHY=auto();TESTED=auto();WEAKENING=auto();PENETRATED=auto();BROKEN=auto();INVALID=auto();UNKNOWN=auto()
class MeanMethod(Enum):RANGE_MIDPOINT=auto();BOLLINGER_MIDDLE=auto();CONFIGURED_EXISTING_FEATURE_REFERENCE=auto()
class RejectionState(Enum):NONE=auto();POTENTIAL=auto();DETECTED=auto();CONFIRMED=auto();FAILED=auto();INVALIDATED=auto();UNKNOWN=auto()
class ReentryState(Enum):BOUNDARY_TOUCH=auto();BOUNDARY_PENETRATION=auto();OUTSIDE_RANGE=auto();REENTRY_PENDING=auto();REENTERED_RANGE=auto();BREAKOUT_CONFIRMED=auto();UNKNOWN=auto()
class DestinationType(Enum):RANGE_MEAN=auto();BOLLINGER_MIDDLE=auto();OPPOSITE_INNER_ZONE=auto();OPPOSITE_BOUNDARY_REFERENCE=auto();CUSTOM_EXISTING_REFERENCE=auto()
class DestinationHealth(Enum):HEALTHY=auto();DEGRADED=auto();UNAVAILABLE=auto();INVALID=auto();UNKNOWN=auto()
class ThesisState(Enum):INTACT=auto();WEAKENING=auto();INVALIDATED=auto();EXPIRED=auto();UNKNOWN=auto()

@dataclass(frozen=True)
class S3Configuration:
    enabled:bool=True;context_timeframe:str="H4";range_timeframe:str="H1";confirmation_timeframe:str="M15"
    supported_timeframes:tuple[str,...]=("M15","H1","H4","D1");strict_range:bool=True
    minimum_observations:int=2;minimum_boundary_tests:int=1;minimum_normalized_width:float=.25;maximum_normalized_width:float=8.0
    lower_extreme:float=.10;upper_extreme:float=.90;maximum_excursion:float=.35
    rsi_lower:float=35;rsi_upper:float=65;require_rsi:bool=False;require_bollinger:bool=True
    wick_rejection_allowed:bool=False;minimum_wick_ratio:float=.45;minimum_reversion_displacement:float=.05
    mean_method:MeanMethod=MeanMethod.RANGE_MIDPOINT;destination_type:DestinationType=DestinationType.RANGE_MEAN
    transition_allowed:bool=True;breakout_risk_blocks:bool=True;candidate_ttl_minutes:int=60;cooldown_observations:int=1
    maximum_history:int=100;maximum_cache_entries:int=256;configuration_snapshot_id:str="S3_DEFAULT_RESEARCH"
    def validate(self):
        errors=[];roles=(self.context_timeframe,self.range_timeframe,self.confirmation_timeframe)
        if len(set(roles))!=3 or any(x not in self.supported_timeframes for x in roles):errors.append("S3_INVALID_TIMEFRAME_ROLES")
        if min(self.minimum_observations,self.minimum_boundary_tests,self.candidate_ttl_minutes,self.maximum_history,self.maximum_cache_entries)<1:errors.append("S3_INVALID_POSITIVE_BOUND")
        if not 0<self.minimum_normalized_width<=self.maximum_normalized_width:errors.append("S3_INVALID_RANGE_WIDTH")
        if not 0<=self.lower_extreme<.5<self.upper_extreme<=1:errors.append("S3_INVALID_EXTREMES")
        if self.maximum_excursion<0 or not 0<=self.minimum_wick_ratio<=1 or self.minimum_reversion_displacement<0:errors.append("S3_INVALID_THRESHOLD")
        if not 0<=self.rsi_lower<50<self.rsi_upper<=100:errors.append("S3_INVALID_RSI")
        if not self.require_bollinger:errors.append("S3_BOLLINGER_REQUIRED_FOR_POINT_IN_TIME_POSITION")
        return tuple(errors)

@dataclass(frozen=True)
class RangeBoundary:
    boundary_id:str;side:BoundarySide;lower_value:float;upper_value:float;test_count:int
    health:BoundaryHealth;available_at_utc:datetime;source_snapshot_id:str;source_zone_ids:tuple[str,...]

@dataclass(frozen=True)
class MeanReference:
    mean_id:str;method:MeanMethod;reference_value:float;as_of_timestamp_utc:datetime;source_evidence_id:str

@dataclass(frozen=True)
class RangeEvidence:
    range_id:str;range_version_id:str;instrument_id:str;timeframe:str;start_time_utc:datetime
    as_of_timestamp_utc:datetime;lower_boundary:RangeBoundary;upper_boundary:RangeBoundary;mean_reference:MeanReference
    width:float;normalized_width:float;duration_observations:int;observation_count:int
    lower_boundary_tests:int;upper_boundary_tests:int;range_state:RangeState;range_health:RangeHealth
    maturity:RangeMaturity;supporting_evidence:tuple[str,...];conflicting_evidence:tuple[str,...]
    missing_evidence:tuple[str,...];market_intelligence_snapshot_id:str;configuration_snapshot_id:str;recovery_epoch:int

@dataclass(frozen=True)
class MeanReversionDestination:
    destination_id:str;strategy_id:str;range_id:str;setup_id:str;destination_type:DestinationType
    reference_value:float;source_evidence_id:str;as_of_timestamp_utc:datetime;health:DestinationHealth
    reason_codes:tuple[str,...];configuration_snapshot_id:str

@dataclass(frozen=True)
class S3Setup:
    setup_id:str;range_id:str;instrument_id:str;boundary_side:BoundarySide;direction:SignalDirection
    extreme_detected_at_utc:datetime;latest_as_of_utc:datetime;range_position:float
    rejection_state:RejectionState;reentry_state:ReentryState;thesis_state:ThesisState
    source_intelligence_snapshot_id:str;configuration_snapshot_id:str;recovery_epoch:int

def _feature(context,role,name):
    for key,value in context.market_intelligence.features.features.get(role,{}).items():
        if key.split(":",1)[0]==name and value.health in (FeatureHealth.VALID,FeatureHealth.VALID_WITH_WARNINGS):
            if isinstance(value.value,(int,float)) and isfinite(float(value.value)):return float(value.value)
    return None

class RangeMeanReversionStrategy:
    def __init__(self,configuration:S3Configuration=S3Configuration(),audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit;self._ranges={};self._setups={};self._history=[];self._destinations={};self._latest={};self._cooldowns={}
        identity=StrategyIdentity(S3_STRATEGY_ID,StrategyFamily.MEAN_REVERSION,"Range & Mean-Reversion Strategy",S3_VERSION,configuration_namespace="strategies.s3_range_mean_reversion",required_capabilities=("PHASE2_INTELLIGENCE","PROMPT12_SCORING"))
        requirements=(StrategyRequirement("S3_RANGE",RequirementType.MANDATORY,EvidenceSource.STRUCTURE,"CONSOLIDATION",configuration.range_timeframe),StrategyRequirement("S3_REGIME",RequirementType.MANDATORY,EvidenceSource.REGIME,"RANGE_REGIME",configuration.context_timeframe),StrategyRequirement("S3_BOLLINGER_POSITION",RequirementType.MANDATORY,EvidenceSource.FEATURE,"BOLLINGER_PERCENT_B",configuration.range_timeframe),StrategyRequirement("S3_REVERSION",RequirementType.MANDATORY,EvidenceSource.FEATURE,"ATR_ADJUSTED_DISPLACEMENT",configuration.confirmation_timeframe),StrategyRequirement("S3_SESSION",RequirementType.MANDATORY,EvidenceSource.SESSION,"SESSION_CONTEXT"),StrategyRequirement("S3_NEWS",RequirementType.MANDATORY,EvidenceSource.NEWS_RISK,"NEWS_CONTEXT"))
        self._metadata=StrategyMetadata(identity,"Research-only range rejection and mean-reversion hypothesis",(configuration.context_timeframe,configuration.range_timeframe,configuration.confirmation_timeframe),("BOLLINGER_PERCENT_B","RSI","ATR_ADJUSTED_DISPLACEMENT"),("CONSOLIDATION","ZONES","BREAKS"),("RANGE","TRANSITION"),True,True,IntelligenceHealth.HEALTHY,requirements)
    @property
    def metadata(self):return self._metadata
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
    def applicability(self,context):
        intel=context.market_intelligence;regime=intel.regime.primary_regime
        if not self.configuration.enabled:return self._app(context,ApplicabilityState.NOT_APPLICABLE,"S3_DISABLED")
        if intel.intelligence_availability in (IntelligenceAvailability.NOT_AVAILABLE,IntelligenceAvailability.UNKNOWN) or intel.overall_intelligence_health in (IntelligenceHealth.UNTRUSTED,IntelligenceHealth.UNAVAILABLE,IntelligenceHealth.UNKNOWN):return self._app(context,ApplicabilityState.BLOCKED,"S3_INVALID_INTELLIGENCE")
        if regime in (PrimaryRegime.TREND,PrimaryRegime.BREAKOUT_EXPANSION,PrimaryRegime.ABNORMAL,PrimaryRegime.UNKNOWN):return self._app(context,ApplicabilityState.BLOCKED,f"S3_{regime.name}_BLOCK")
        c=intel.structure.context_structure;s=intel.structure.strategy_structure
        if c.direction in (StructuralDirection.BULLISH,StructuralDirection.BEARISH) and s.direction is c.direction:return self._app(context,ApplicabilityState.BLOCKED,"S3_STRONG_TREND_BLOCK")
        if any(x.confirmation_status and x.break_timestamp<=context.as_of_timestamp_utc for x in s.breaks):return self._app(context,ApplicabilityState.BLOCKED,"S3_CONFIRMED_BREAKOUT_BLOCK")
        if intel.session.temporal_restriction is not TemporalRestriction.ALLOW_CONTEXT:return self._app(context,ApplicabilityState.BLOCKED,"S3_SESSION_RESTRICTED")
        if intel.news_risk.policy_state is not NewsPolicyState.ALLOW_CONTEXT:return self._app(context,ApplicabilityState.BLOCKED,"S3_NEWS_RESTRICTED")
        if regime is PrimaryRegime.TRANSITION:return self._app(context,ApplicabilityState.CONDITIONAL if self.configuration.transition_allowed else ApplicabilityState.BLOCKED,"S3_TRANSITION_CONDITIONAL")
        return self._app(context,ApplicabilityState.APPLICABLE,"S3_RANGE_APPLICABLE")
    def _app(self,context,state,reason):return StrategyApplicability(deterministic_id("s3_app",context.evaluation_id,state.name),S3_STRATEGY_ID,state,CapabilityStatus.SUPPORTED,(reason,),())
    def _range(self,context):
        cfg=self.configuration;structure=context.market_intelligence.structure.strategy_structure;con=structure.consolidation
        if con.state is not ConsolidationState.CONSOLIDATING or con.lower_boundary is None or con.upper_boundary is None:return None
        lower=float(con.lower_boundary);upper=float(con.upper_boundary);width=upper-lower
        if width<=0:return None
        zones=tuple(z for z in structure.zones if z.confirmed_at<=context.as_of_timestamp_utc and z.state not in (ZoneState.BROKEN,ZoneState.EXPIRED,ZoneState.INVALID))
        lows=tuple(z for z in zones if z.zone_type in (ZoneType.SUPPORT,ZoneType.DUAL_ROLE));highs=tuple(z for z in zones if z.zone_type in (ZoneType.RESISTANCE,ZoneType.DUAL_ROLE))
        lt=sum(z.test_count for z in lows);ut=sum(z.test_count for z in highs);observations=max(lt+ut,1)
        normalized=_feature(context,"strategy","RANGE_ATR")
        if normalized is None:normalized=_feature(context,"strategy","BOLLINGER_BANDWIDTH")
        normalized=float(normalized) if normalized is not None else width/max(abs((upper+lower)/2),1e-12)
        broken=any(x.confirmation_status and x.break_timestamp<=context.as_of_timestamp_utc for x in structure.breaks)
        two_sided=lt>=cfg.minimum_boundary_tests and ut>=cfg.minimum_boundary_tests
        width_ok=cfg.minimum_normalized_width<=normalized<=cfg.maximum_normalized_width
        confirmed=observations>=cfg.minimum_observations and two_sided and width_ok and not broken
        maturity=RangeMaturity.MATURE_RANGE if observations>=2*cfg.minimum_observations else RangeMaturity.DEVELOPING_RANGE if confirmed else RangeMaturity.NEW_RANGE
        state=RangeState.BROKEN if broken else RangeState.MATURE if confirmed and maturity is RangeMaturity.MATURE_RANGE else RangeState.CONFIRMED if confirmed else RangeState.FORMING
        health=RangeHealth.BROKEN if broken else RangeHealth.HEALTHY if confirmed else RangeHealth.DEGRADED
        start=con.created_at or context.as_of_timestamp_utc;logical=deterministic_id("s3_range",context.market_intelligence.dataset_fingerprint,context.instrument_id,cfg.range_timeframe,lower,upper,start.isoformat())
        version=deterministic_id("s3_range_version",logical,lower,upper,con.last_updated_at.isoformat() if con.last_updated_at else context.as_of_timestamp_utc.isoformat(),context.market_intelligence.structure_snapshot_id)
        lb=RangeBoundary(deterministic_id("s3_boundary",logical,"LOWER"),BoundarySide.LOWER_BOUNDARY,lower,lower,lt,BoundaryHealth.TESTED if lt else BoundaryHealth.UNKNOWN,con.last_updated_at or start,context.market_intelligence.structure_snapshot_id,tuple(z.zone_id for z in lows))
        ub=RangeBoundary(deterministic_id("s3_boundary",logical,"UPPER"),BoundarySide.UPPER_BOUNDARY,upper,upper,ut,BoundaryHealth.TESTED if ut else BoundaryHealth.UNKNOWN,con.last_updated_at or start,context.market_intelligence.structure_snapshot_id,tuple(z.zone_id for z in highs))
        middle=(lower+upper)/2;mean=MeanReference(deterministic_id("s3_mean",logical,cfg.mean_method.name,middle),cfg.mean_method,middle,context.as_of_timestamp_utc,context.market_intelligence.structure_snapshot_id)
        missing=tuple(x for x,ok in (("S3_LOWER_BOUNDARY",bool(lows)),("S3_UPPER_BOUNDARY",bool(highs)),("S3_RANGE_WIDTH",width_ok)) if not ok)
        result=RangeEvidence(logical,version,context.instrument_id,cfg.range_timeframe,start,context.as_of_timestamp_utc,lb,ub,mean,width,normalized,observations,observations,lt,ut,state,health,maturity,("S3_RANGE_CONFIRMED",) if confirmed else (),(),missing,context.market_intelligence.market_intelligence_snapshot_id,cfg.configuration_snapshot_id,context.recovery_epoch)
        self._ranges[context.instrument_id]=result;return result
    def _evidence(self,context,range_e,setup,reentered,displacement):
        direction=setup.direction;items=[]
        def add(kind,source,snapshot,value,strength,code,category=EvidenceCategory.SUPPORTING):items.append(SignalEvidence(deterministic_id("s3_evidence",context.evaluation_id,kind),kind,category,source,snapshot,context.instrument_id,self.configuration.range_timeframe,value,None,direction,strength,EvidenceAvailability.AVAILABLE if value is not None else EvidenceAvailability.UNAVAILABLE,"HEALTHY" if value is not None else "UNAVAILABLE",code,(range_e.range_version_id,setup.setup_id)))
        add("RANGE_QUALITY",EvidenceSource.STRUCTURE,context.market_intelligence.structure_snapshot_id,range_e.range_state.name,90 if range_e.range_state in (RangeState.CONFIRMED,RangeState.MATURE) else 30,"S3_RANGE_CONFIRMED")
        add("STRUCTURE_BOUNDARY",EvidenceSource.STRUCTURE,context.market_intelligence.structure_snapshot_id,setup.boundary_side.name,80,"S3_BOUNDARY_VALID")
        add("VOLATILITY_RANGE_WIDTH",EvidenceSource.FEATURE,context.market_intelligence.feature_snapshot_id,range_e.normalized_width,75,"S3_RANGE_WIDTH_VALID")
        add("MOMENTUM_REVERSION",EvidenceSource.FEATURE,context.market_intelligence.feature_snapshot_id,displacement,min(100,50+abs(displacement or 0)*25),"S3_REVERSION_CONFIRMED")
        add("SETUP_QUALITY_REENTRY",EvidenceSource.STRATEGY_DERIVED,context.market_intelligence.market_intelligence_snapshot_id,reentered,90 if reentered else 0,"S3_RANGE_REENTRY_CONFIRMED")
        return tuple(items)
    def detect(self,context):
        self._record("s3_evaluation_started",{"evaluation_id":context.evaluation_id});cfg=self.configuration;range_e=self._range(context)
        if range_e is None:return self._det(context,DetectionState.INCOMPLETE,(),"S3_NO_VALID_RANGE")
        self._history.append(range_e);self._history=self._history[-cfg.maximum_history:]
        if range_e.range_state not in (RangeState.CONFIRMED,RangeState.MATURE):return self._det(context,DetectionState.NOT_DETECTED,(),"S3_RANGE_NOT_CONFIRMED")
        position=_feature(context,"strategy","BOLLINGER_PERCENT_B");rsi=_feature(context,"strategy","RSI")
        if position is None:return self._det(context,DetectionState.INCOMPLETE,(),"S3_BOLLINGER_UNAVAILABLE")
        prior=self._setups.get(context.instrument_id);side=BoundarySide.LOWER_BOUNDARY if position<=cfg.lower_extreme else BoundarySide.UPPER_BOUNDARY if position>=cfg.upper_extreme else BoundarySide.NONE
        if side is not BoundarySide.NONE:
            if position < -cfg.maximum_excursion or position > 1+cfg.maximum_excursion:return self._det(context,DetectionState.BLOCKED,(),"S3_EXCESSIVE_EXCURSION")
            direction=SignalDirection.LONG_BIAS if side is BoundarySide.LOWER_BOUNDARY else SignalDirection.SHORT_BIAS
            setup_id=deterministic_id("s3_setup",S3_STRATEGY_ID,range_e.range_id,side.name,context.market_intelligence.market_intelligence_snapshot_id,cfg.configuration_snapshot_id)
            setup=S3Setup(setup_id,range_e.range_id,context.instrument_id,side,direction,context.as_of_timestamp_utc,context.as_of_timestamp_utc,position,RejectionState.POTENTIAL,ReentryState.OUTSIDE_RANGE,ThesisState.INTACT,context.market_intelligence.market_intelligence_snapshot_id,cfg.configuration_snapshot_id,context.recovery_epoch)
            self._setups[context.instrument_id]=setup;self._record("s3_extreme_detected",{"setup_id":setup_id,"side":side.name});return self._det(context,DetectionState.NOT_DETECTED,(),"S3_REJECTION_PENDING")
        if prior is None or prior.range_id!=range_e.range_id:return self._det(context,DetectionState.NOT_DETECTED,(),"S3_NO_EXTREME")
        displacement=_feature(context,"execution","ATR_ADJUSTED_DISPLACEMENT");toward=displacement is not None and (displacement>=cfg.minimum_reversion_displacement if prior.direction is SignalDirection.LONG_BIAS else displacement<=-cfg.minimum_reversion_displacement)
        rsi_ok=not cfg.require_rsi or (rsi is not None and (rsi>=cfg.rsi_lower if prior.direction is SignalDirection.LONG_BIAS else rsi<=cfg.rsi_upper))
        reentered=(cfg.lower_extreme<position<cfg.upper_extreme)
        setup=S3Setup(prior.setup_id,prior.range_id,prior.instrument_id,prior.boundary_side,prior.direction,prior.extreme_detected_at_utc,context.as_of_timestamp_utc,position,RejectionState.CONFIRMED if reentered else RejectionState.FAILED,ReentryState.REENTERED_RANGE if reentered else ReentryState.REENTRY_PENDING,ThesisState.INTACT if reentered else ThesisState.WEAKENING,context.market_intelligence.market_intelligence_snapshot_id,cfg.configuration_snapshot_id,context.recovery_epoch);self._setups[context.instrument_id]=setup
        evidence=self._evidence(context,range_e,setup,reentered,displacement)
        if not (reentered and toward and rsi_ok):return self._det(context,DetectionState.NOT_DETECTED,evidence,"S3_REVERSION_NOT_CONFIRMED")
        destination=MeanReversionDestination(deterministic_id("s3_destination",setup.setup_id,range_e.mean_reference.mean_id),S3_STRATEGY_ID,range_e.range_id,setup.setup_id,cfg.destination_type,range_e.mean_reference.reference_value,range_e.mean_reference.source_evidence_id,context.as_of_timestamp_utc,DestinationHealth.HEALTHY,("S3_RANGE_MEAN_DESTINATION",),cfg.configuration_snapshot_id)
        self._destinations[setup.setup_id]=destination;self._latest[context.evaluation_id]=(range_e,setup,destination);self._record("s3_reversion_confirmed",{"setup_id":setup.setup_id});return self._det(context,DetectionState.DETECTED,evidence,"S3_REVERSION_CONFIRMED")
    def _det(self,context,status,evidence,reason):
        self._record("s3_evaluation_completed",{"evaluation_id":context.evaluation_id,"status":status.name,"reason":reason});return DetectionResult(deterministic_id("s3_detection",context.evaluation_id,status.name,reason),S3_STRATEGY_ID,context.instrument_id,context.as_of_timestamp_utc,status,tuple(evidence),tuple(x for x in evidence if x.availability is not EvidenceAvailability.AVAILABLE),tuple(x for x in evidence if x.category in (EvidenceCategory.CONFLICTING,EvidenceCategory.DISQUALIFYING)),context.market_intelligence.market_intelligence_snapshot_id,self.configuration.configuration_snapshot_id)
    def qualify(self,context,detection):
        if detection.status is not DetectionState.DETECTED or context.evaluation_id not in self._latest:return QualificationResult(deterministic_id("s3_qualification",detection.detection_id),S3_STRATEGY_ID,QualificationState.INCOMPLETE,(),(),(),("S3_SETUP_INCOMPLETE",),())
        return QualificationResult(deterministic_id("s3_qualification",detection.detection_id,"QUALIFIED"),S3_STRATEGY_ID,QualificationState.QUALIFIED,("S3_RANGE_CONFIRMED","S3_REJECTION_CONFIRMED","S3_RANGE_REENTRY_CONFIRMED","S3_REVERSION_CONFIRMED"),(),(),(),())
    def direction(self,context,detection):
        latest=self._latest.get(context.evaluation_id);return latest[1].direction if latest else SignalDirection.UNKNOWN
    @property
    def range_history(self):return tuple(self._history)
    @property
    def destinations(self):return MappingProxyType(dict(self._destinations))
    def recovery_state(self):return {"s3_engine_version":S3_ENGINE_VERSION,"strategy_version":S3_VERSION,"configuration_snapshot_id":self.configuration.configuration_snapshot_id,"ranges":tuple((k,v.range_id,v.range_version_id,v.range_state.name) for k,v in sorted(self._ranges.items())),"setups":tuple((k,v.setup_id,v.range_id,v.rejection_state.name,v.reentry_state.name) for k,v in sorted(self._setups.items()))}
    def validate_recovery(self,state):return state.get("s3_engine_version")==S3_ENGINE_VERSION and state.get("strategy_version")==S3_VERSION and state.get("configuration_snapshot_id")==self.configuration.configuration_snapshot_id

def register_s3(registry,configuration:S3Configuration=S3Configuration(),audit=None):
    strategy=RangeMeanReversionStrategy(configuration,audit);registry.register(strategy);return strategy
