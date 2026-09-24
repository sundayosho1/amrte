"""Point-in-time thesis invalidation research; never an executable stop system."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, localcontext
from enum import Enum, auto

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation,DecisionOutcome,DecisionStatus,DecisionTrace
from amrte.risk.sizing import (_decimal,CapitalSource,DistanceHealth,InvalidationDistanceContext,InvalidationSource,
    ResearchCapitalContext,ResearchCostBuffer,RiskSizingEngine,RiskSizingResult,SizingEligibility)
from amrte.risk.adaptive import (AdaptiveRiskEngine,AdaptiveRiskResult,HealthEvidence,ResearchEquityObservation,
    VolatilityEvidence)
from amrte.strategies.strategy_arbitration import ArbitrationOutcome,ResearchAvailability,StrategyDecisionSnapshot

INVALIDATION_ENGINE_VERSION="1.0";ZERO=Decimal("0")

class InvalidationMethod(Enum):STRUCTURE=auto();ATR_NORMALIZED=auto();HYBRID=auto();CUSTOM_REGISTERED=auto()
class HybridPolicy(Enum):STRUCTURE_PLUS_VOLATILITY_BUFFER=auto();MOST_CONSERVATIVE_VALID_DISTANCE=auto();STRATEGY_DEFINED=auto()
class BelowMinimumPolicy(Enum):REJECT=auto();WIDEN_TO_MINIMUM_IF_THESIS_VALID=auto()
class FrictionSource(Enum):CONFIGURED_NORMALIZED_BUFFER=auto();HISTORICAL_OFFLINE_FRICTION_SERIES=auto();SYNTHETIC_FIXTURE=auto();NONE=auto()
class MissingFrictionPolicy(Enum):NOT_REQUIRED=auto();USE_CONSERVATIVE_CONFIGURED_VALUE=auto();BLOCK=auto()
class EvidenceAvailability(Enum):AVAILABLE=auto();DEGRADED=auto();UNAVAILABLE=auto();NOT_APPLICABLE=auto();UNKNOWN=auto()
class InvalidationHealth(Enum):HEALTHY=auto();DEGRADED=auto();RESTRICTED=auto();INSUFFICIENT_DATA=auto();BLOCKED=auto();INVALID=auto();UNKNOWN=auto()
class InvalidationEligibility(Enum):ELIGIBLE=auto();ELIGIBLE_WITH_RESTRICTIONS=auto();NOT_ELIGIBLE=auto();BLOCKED=auto();INCOMPLETE=auto();UNKNOWN=auto()
class InvalidationLifecycle(Enum):UNAVAILABLE=auto();CANDIDATE=auto();VALIDATED=auto();ACTIVE=auto();APPROACHED=auto();INVALIDATED=auto();EXPIRED=auto();SUPERSEDED=auto();BLOCKED=auto();UNKNOWN=auto()
class InvalidationCondition(Enum):TOUCH=auto();CLOSE_BEYOND=auto();MULTI_CLOSE_BEYOND=auto();STRUCTURAL_CONFIRMATION=auto();STRATEGY_DEFINED=auto()
class ResearchDirection(Enum):BULLISH=auto();BEARISH=auto()
class ThesisState(Enum):THESIS_INTACT=auto();THESIS_WEAKENING=auto();THESIS_INVALIDATED=auto()

@dataclass(frozen=True)
class InvalidationProfile:
    profile_id:str;strategy_id:str;strategy_variant:str|None;method:InvalidationMethod;direction:ResearchDirection
    structural_required:bool=True;atr_allowed:bool=True;hybrid_policy:HybridPolicy=HybridPolicy.STRUCTURE_PLUS_VOLATILITY_BUFFER
    fallback_allowed:bool=False;fallback_methods:tuple[InvalidationMethod,...]=()

@dataclass(frozen=True)
class InvalidationConfiguration:
    enabled:bool=True;require_authoritative_invalidation:bool=True;minimum_distance:Decimal=Decimal("0.10");maximum_distance:Decimal=Decimal("10")
    below_minimum_policy:BelowMinimumPolicy=BelowMinimumPolicy.REJECT;atr_multiplier:Decimal=Decimal("1.5")
    friction_enabled:bool=False;friction_source:FrictionSource=FrictionSource.NONE;missing_friction_policy:MissingFrictionPolicy=MissingFrictionPolicy.NOT_REQUIRED;conservative_friction_buffer:Decimal=ZERO
    volatility_adjustment_enabled:bool=False;maximum_volatility_allowance:Decimal=Decimal("1")
    default_condition:InvalidationCondition=InvalidationCondition.CLOSE_BEYOND;multi_close_count:int=2
    maximum_candidates:int=256;maximum_decisions:int=256;maximum_events:int=256;maximum_ledger_entries:int=512;maximum_cache_entries:int=256
    precision:int=28;tolerance:Decimal=Decimal("0.00000001");configuration_snapshot_id:str="INVALIDATION_DEFAULT_RESEARCH"
    def validate(self):
        errors=[]
        try:
            minimum=_decimal(self.minimum_distance);maximum=_decimal(self.maximum_distance);atr=_decimal(self.atr_multiplier);friction=_decimal(self.conservative_friction_buffer);allowance=_decimal(self.maximum_volatility_allowance)
            if minimum<=0 or maximum<minimum:errors.append("INV_DISTANCE_CONFIGURATION_INVALID")
            if atr<0:errors.append("INV_ATR_MULTIPLIER_INVALID")
            if friction<0:errors.append("INV_FRICTION_INVALID")
            if allowance<0:errors.append("INV_VOLATILITY_ALLOWANCE_INVALID")
        except ValueError:errors.append("INV_NUMERICAL_INVALID")
        if self.multi_close_count<1:errors.append("INV_CONFIRMATION_POLICY_INVALID")
        if min(self.maximum_candidates,self.maximum_decisions,self.maximum_events,self.maximum_ledger_entries,self.maximum_cache_entries)<1:errors.append("INV_HISTORY_BOUND_INVALID")
        return tuple(dict.fromkeys(errors))

@dataclass(frozen=True)
class ResearchReferencePoint:
    reference_point_id:str;value:Decimal;source_artifact_id:str;source_type:str;available_at_utc:datetime;as_of_timestamp_utc:datetime;dataset_id:str;instrument_id:str;timeframe:str;configuration_snapshot_id:str
    @classmethod
    def create(cls,value,as_of,source_artifact_id,dataset_id,instrument_id,timeframe,configuration_snapshot_id="INVALIDATION_DEFAULT_RESEARCH"):
        v=_decimal(value);identity=deterministic_id("research_reference_point",str(v),as_of.isoformat(),source_artifact_id,dataset_id,instrument_id,timeframe,configuration_snapshot_id)
        return cls(identity,v,source_artifact_id,"RESEARCH_ARTIFACT",as_of,as_of,dataset_id,instrument_id,timeframe,configuration_snapshot_id)

@dataclass(frozen=True)
class StructuralInvalidationEvidence:
    evidence_id:str;strategy_decision_snapshot_id:str;research_signal_id:str;direction:ResearchDirection;structure_snapshot_id:str;structural_reference_id:str;structural_reference_type:str;reference_value:Decimal;confirmed_at_utc:datetime;invalidation_condition:InvalidationCondition;health:InvalidationHealth;availability:EvidenceAvailability;as_of_timestamp_utc:datetime;configuration_snapshot_id:str;dataset_id:str;instrument_id:str;timeframe:str
    @classmethod
    def create(cls,snapshot,signal_id,direction,reference_value,reference_id,structure_snapshot_id,confirmed_at,dataset_id,timeframe,condition=InvalidationCondition.CLOSE_BEYOND,configuration_snapshot_id="INVALIDATION_DEFAULT_RESEARCH"):
        v=_decimal(reference_value);identity=deterministic_id("structural_invalidation",snapshot.snapshot_id,signal_id,direction.name,str(v),reference_id,structure_snapshot_id,confirmed_at.isoformat(),dataset_id,timeframe)
        return cls(identity,snapshot.snapshot_id,signal_id,direction,structure_snapshot_id,reference_id,"AUTHORITATIVE_UPSTREAM_STRUCTURE",v,confirmed_at,condition,InvalidationHealth.HEALTHY,EvidenceAvailability.AVAILABLE,snapshot.as_of_timestamp_utc,configuration_snapshot_id,dataset_id,snapshot.instrument_id,timeframe)

@dataclass(frozen=True)
class ATRInvalidationEvidence:
    evidence_id:str;feature_snapshot_id:str;atr_feature_id:str;atr_value:Decimal;available_at_utc:datetime;health:InvalidationHealth;availability:EvidenceAvailability;dataset_id:str;instrument_id:str;timeframe:str;configuration_snapshot_id:str
    @classmethod
    def create(cls,value,as_of,feature_snapshot_id,atr_feature_id,dataset_id,instrument_id,timeframe,configuration_snapshot_id="INVALIDATION_DEFAULT_RESEARCH"):
        v=_decimal(value);identity=deterministic_id("atr_invalidation",str(v),as_of.isoformat(),feature_snapshot_id,atr_feature_id,dataset_id,instrument_id,timeframe)
        return cls(identity,feature_snapshot_id,atr_feature_id,v,as_of,InvalidationHealth.HEALTHY,EvidenceAvailability.AVAILABLE,dataset_id,instrument_id,timeframe,configuration_snapshot_id)

@dataclass(frozen=True)
class ResearchFrictionBuffer:
    buffer_id:str;normalized_value:Decimal|None;source:FrictionSource;source_artifact_id:str|None;available_at_utc:datetime;health:InvalidationHealth;configuration_snapshot_id:str
    @classmethod
    def create(cls,value,as_of,source=FrictionSource.SYNTHETIC_FIXTURE,source_artifact_id="OFFLINE_FRICTION",configuration_snapshot_id="INVALIDATION_DEFAULT_RESEARCH"):
        v=None if value is None else _decimal(value);return cls(deterministic_id("research_friction",str(v),as_of.isoformat(),source.name,source_artifact_id),v,source,source_artifact_id,as_of,InvalidationHealth.HEALTHY if v is not None else InvalidationHealth.INSUFFICIENT_DATA,configuration_snapshot_id)

@dataclass(frozen=True)
class VolatilityAdjustment:
    adjustment_id:str;normalized_allowance:Decimal;source_artifact_id:str;available_at_utc:datetime;health:InvalidationHealth;configuration_snapshot_id:str

@dataclass(frozen=True)
class InvalidationCandidate:
    candidate_id:str;method:InvalidationMethod;direction:ResearchDirection;reference_point_id:str;boundary:Decimal;raw_distance:Decimal;evidence_ids:tuple[str,...];health:InvalidationHealth;availability:EvidenceAvailability;reason_codes:tuple[str,...]

@dataclass(frozen=True)
class NormalizedInvalidationDistance:
    distance_id:str;strategy_decision_snapshot_id:str;invalidation_decision_id:str;direction:ResearchDirection;reference_point_id:str;boundary_id:str;raw_research_distance:Decimal;normalization_method:str;normalization_reference:Decimal;normalized_distance:Decimal;health:InvalidationHealth;availability:EvidenceAvailability;as_of_timestamp_utc:datetime;configuration_snapshot_id:str;engine_version:str

@dataclass(frozen=True)
class ThesisInvalidationDecision:
    decision_id:str;strategy_decision_snapshot_id:str;research_signal_id:str;strategy_id:str;strategy_variant:str|None;direction:ResearchDirection;method:InvalidationMethod;profile_id:str;reference_point_id:str;candidate_ids:tuple[str,...];selected_candidate_id:str|None;rejected_candidate_ids:tuple[str,...];structural_evidence_id:str|None;atr_feature_reference:str|None;friction_buffer_id:str|None;volatility_adjustment_id:str|None;research_invalidation_boundary:Decimal|None;normalized_distance:NormalizedInvalidationDistance|None;minimum_distance:Decimal;maximum_distance:Decimal;health:InvalidationHealth;eligibility:InvalidationEligibility;lifecycle:InvalidationLifecycle;thesis_state:ThesisState;restrictions:tuple[str,...];reason_codes:tuple[str,...];as_of_timestamp_utc:datetime;configuration_snapshot_id:str;invalidation_engine_version:str;recovery_epoch:int

@dataclass(frozen=True)
class InvalidationEvent:
    event_id:str;decision_id:str;boundary_id:str;condition:InvalidationCondition;observed_at_utc:datetime;confirmed_at_utc:datetime;observation_ids:tuple[str,...];lifecycle:InvalidationLifecycle;reason_codes:tuple[str,...]

@dataclass(frozen=True)
class InvalidationResult:
    decision:ThesisInvalidationDecision;decision_trace:DecisionTrace

@dataclass(frozen=True)
class RiskReconciliationResult:
    invalidation:InvalidationResult;prompt17:RiskSizingResult|None;prompt18:AdaptiveRiskResult|None;final_simulated_exposure:Decimal;final_simulated_risk:Decimal;reason_codes:tuple[str,...]

class InvalidationLedger:
    def __init__(self,maximum_entries=512):self.maximum_entries=maximum_entries;self.decisions=OrderedDict();self.events=OrderedDict();self.states={}
    def add_decision(self,decision):self.decisions[decision.decision_id]=decision;self.states[decision.decision_id]=decision.lifecycle;self._bound()
    def add_event(self,event):
        if event.event_id not in self.events:self.events[event.event_id]=event
        self.states[event.decision_id]=event.lifecycle;self._bound()
    def expire(self,decision_id):
        if self.states.get(decision_id) is not InvalidationLifecycle.INVALIDATED:self.states[decision_id]=InvalidationLifecycle.EXPIRED
    def supersede(self,decision_id):self.states[decision_id]=InvalidationLifecycle.SUPERSEDED
    def _bound(self):
        while len(self.decisions)+len(self.events)>self.maximum_entries:
            store=self.events if self.events else self.decisions;store.popitem(last=False)
    def state(self):return {"decision_ids":tuple(self.decisions),"events":tuple(self.events.values()),"states":dict(self.states),"maximum_entries":self.maximum_entries}
    def restore(self,state):
        if state.get("maximum_entries")!=self.maximum_entries:return False
        self.states=dict(state.get("states",{}));self.events=OrderedDict((e.event_id,e) for e in state.get("events",()));return True

class ThesisInvalidationEngine:
    def __init__(self,configuration=InvalidationConfiguration(),audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit;self.ledger=InvalidationLedger(configuration.maximum_ledger_entries);self._candidates=OrderedDict();self._decisions=OrderedDict();self._events=OrderedDict();self._cache=OrderedDict()
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
    def evaluate(self,snapshot:StrategyDecisionSnapshot,profile:InvalidationProfile,reference:ResearchReferencePoint|None,structure:StructuralInvalidationEvidence|None=None,atr:ATRInvalidationEvidence|None=None,friction:ResearchFrictionBuffer|None=None,volatility:VolatilityAdjustment|None=None):
        as_of=snapshot.as_of_timestamp_utc;self._record("invalidation_evaluation_started",{"snapshot_id":snapshot.snapshot_id});key=(snapshot.snapshot_id,profile.profile_id,reference.reference_point_id if reference else "MISSING",structure.evidence_id if structure else "NONE",atr.evidence_id if atr else "NONE",friction.buffer_id if friction else "NONE",volatility.adjustment_id if volatility else "NONE",self.configuration.configuration_snapshot_id,INVALIDATION_ENGINE_VERSION)
        if key in self._cache:self._cache.move_to_end(key);return self._cache[key]
        hard=[];reasons=[];candidates=[]
        if not self.configuration.enabled:hard.append("INV_DISABLED")
        if snapshot.outcome not in (ArbitrationOutcome.SINGLE_PREFERRED,ArbitrationOutcome.MULTIPLE_COMPATIBLE) or snapshot.research_availability not in (ResearchAvailability.AVAILABLE,ResearchAvailability.AVAILABLE_WITH_RESTRICTIONS):hard.append("INV_UPSTREAM_BLOCKED")
        signal=snapshot.preferred_research_signal_id or (snapshot.permitted_research_signal_ids[0] if len(snapshot.permitted_research_signal_ids)==1 else None)
        if signal is None:hard.append("INV_RESEARCH_SIGNAL_MISSING")
        if reference is None:hard.append("INV_REFERENCE_MISSING")
        elif reference.available_at_utc>as_of:hard.append("INV_REFERENCE_FUTURE")
        elif reference.instrument_id!=snapshot.instrument_id:hard.append("INV_LINEAGE_MISMATCH")
        elif reference.value<=0:hard.append("INV_REFERENCE_INVALID")
        if reference and structure:
            if structure.confirmed_at_utc>as_of:reasons.append("INV_STRUCTURE_UNCONFIRMED")
            elif structure.strategy_decision_snapshot_id!=snapshot.snapshot_id or structure.research_signal_id!=signal or not self._lineage(reference,structure):hard.append("INV_LINEAGE_MISMATCH")
            elif structure.health in (InvalidationHealth.INVALID,InvalidationHealth.BLOCKED,InvalidationHealth.UNKNOWN):reasons.append("INV_STRUCTURE_INVALID")
            else:candidates.append(self._structure_candidate(reference,structure));reasons.append("INV_STRUCTURE_ACCEPTED")
        elif profile.structural_required:reasons.append("INV_STRUCTURE_MISSING")
        if reference and atr:
            if atr.available_at_utc>as_of:reasons.append("INV_ATR_FUTURE")
            elif not self._lineage(reference,atr):hard.append("INV_LINEAGE_MISMATCH")
            elif atr.atr_value<=0 or atr.health in (InvalidationHealth.INVALID,InvalidationHealth.BLOCKED,InvalidationHealth.UNKNOWN):reasons.append("INV_ATR_INVALID")
            else:candidates.append(self._atr_candidate(reference,atr,profile));reasons.append("INV_ATR_ACCEPTED")
        if profile.method is InvalidationMethod.HYBRID and reference:
            structural=next((x for x in candidates if x.method is InvalidationMethod.STRUCTURE),None);atr_candidate=next((x for x in candidates if x.method is InvalidationMethod.ATR_NORMALIZED),None)
            if structural and atr_candidate:candidates.append(self._hybrid_candidate(reference,structural,atr_candidate,profile));reasons.append("INV_HYBRID_CREATED")
            else:reasons.append("INV_HYBRID_INCOMPLETE")
        eligible=self._eligible_candidates(candidates,profile)
        selected=self._select(eligible,profile)
        if selected is None:hard.append("INV_NO_AUTHORITATIVE_INVALIDATION")
        boundary=selected.boundary if selected else None;distance=selected.raw_distance if selected else None
        friction_value=ZERO
        if self.configuration.friction_enabled:
            if friction is None or friction.normalized_value is None:
                if self.configuration.missing_friction_policy is MissingFrictionPolicy.BLOCK:hard.append("INV_FRICTION_MISSING")
                elif self.configuration.missing_friction_policy is MissingFrictionPolicy.USE_CONSERVATIVE_CONFIGURED_VALUE:friction_value=_decimal(self.configuration.conservative_friction_buffer);reasons.append("INV_FRICTION_CONSERVATIVE")
            elif friction.available_at_utc>as_of:hard.append("INV_FRICTION_FUTURE")
            elif friction.normalized_value<0:hard.append("INV_FRICTION_INVALID")
            else:friction_value=friction.normalized_value;reasons.append("INV_FRICTION_APPLIED")
        allowance=ZERO
        if self.configuration.volatility_adjustment_enabled:
            if volatility is None:hard.append("INV_VOLATILITY_MISSING")
            elif volatility.available_at_utc>as_of:hard.append("INV_VOLATILITY_FUTURE")
            elif volatility.normalized_allowance<0 or volatility.normalized_allowance>self.configuration.maximum_volatility_allowance:hard.append("INV_VOLATILITY_ALLOWANCE_INVALID")
            else:allowance=volatility.normalized_allowance;reasons.append("INV_VOLATILITY_ALLOWANCE_APPLIED")
        if distance is not None:
            distance+=friction_value+allowance
            adverse=-1 if selected.direction is ResearchDirection.BULLISH else 1;boundary=selected.boundary+adverse*(friction_value+allowance)
            if distance<self.configuration.minimum_distance:
                if self.configuration.below_minimum_policy is BelowMinimumPolicy.WIDEN_TO_MINIMUM_IF_THESIS_VALID:
                    extra=self.configuration.minimum_distance-distance;distance=self.configuration.minimum_distance;boundary+=adverse*extra;reasons.append("INV_DISTANCE_WIDENED_TO_MINIMUM")
                else:hard.append("INV_DISTANCE_TOO_SMALL")
            if distance>self.configuration.maximum_distance:hard.append("INV_DISTANCE_TOO_LARGE")
        decision_seed=deterministic_id("thesis_invalidation_seed",snapshot.snapshot_id,profile.profile_id,selected.candidate_id if selected else "NONE",str(boundary),str(distance),*(sorted(hard)),self.configuration.configuration_snapshot_id,INVALIDATION_ENGINE_VERSION)
        normalized=None
        if not hard and selected and distance and distance>0:
            did=deterministic_id("normalized_invalidation_distance",decision_seed,selected.candidate_id,str(distance),"UPSTREAM_NORMALIZED_RESEARCH_DISTANCE")
            normalized=NormalizedInvalidationDistance(did,snapshot.snapshot_id,decision_seed,selected.direction,reference.reference_point_id,selected.candidate_id,abs(reference.value-boundary),"UPSTREAM_NORMALIZED_RESEARCH_DISTANCE",Decimal("1"),distance,InvalidationHealth.HEALTHY,EvidenceAvailability.AVAILABLE,as_of,self.configuration.configuration_snapshot_id,INVALIDATION_ENGINE_VERSION)
        blocked=bool(hard);lifecycle=InvalidationLifecycle.BLOCKED if blocked else InvalidationLifecycle.ACTIVE;health=InvalidationHealth.BLOCKED if blocked else InvalidationHealth.HEALTHY;eligibility=InvalidationEligibility.BLOCKED if blocked else InvalidationEligibility.ELIGIBLE_WITH_RESTRICTIONS if snapshot.restrictions else InvalidationEligibility.ELIGIBLE
        reason_codes=tuple(dict.fromkeys(tuple(reasons)+tuple(hard)+(("INV_NO_ACTION",) if blocked else ("INV_DISTANCE_CREATED","INV_BOUNDARY_ACTIVE"))))
        decision_id=deterministic_id("thesis_invalidation",decision_seed,normalized.distance_id if normalized else "NONE",lifecycle.name,*reason_codes)
        if normalized:normalized=replace(normalized,invalidation_decision_id=decision_id)
        decision=ThesisInvalidationDecision(decision_id,snapshot.snapshot_id,signal or "NONE",profile.strategy_id,profile.strategy_variant,selected.direction if selected else structure.direction if structure else ResearchDirection.BULLISH,profile.method,profile.profile_id,reference.reference_point_id if reference else "NONE",tuple(x.candidate_id for x in candidates),selected.candidate_id if selected else None,tuple(x.candidate_id for x in candidates if x is not selected),structure.evidence_id if structure else None,atr.atr_feature_id if atr else None,friction.buffer_id if friction else None,volatility.adjustment_id if volatility else None,boundary,normalized,_decimal(self.configuration.minimum_distance),_decimal(self.configuration.maximum_distance),health,eligibility,lifecycle,ThesisState.THESIS_INTACT if not blocked else ThesisState.THESIS_WEAKENING,tuple(dict.fromkeys(snapshot.restrictions+tuple(hard))),reason_codes,as_of,self.configuration.configuration_snapshot_id,INVALIDATION_ENGINE_VERSION,snapshot.recovery_epoch)
        status=DecisionStatus.FAILED if blocked else DecisionStatus.PASSED;checks=(DecisionEvaluation("THESIS_AUTHORITY",status,reason_codes[0],"Strategy decision and research-signal authority validated",(snapshot.snapshot_id,signal or "NONE")),DecisionEvaluation("INVALIDATION_EVIDENCE",status,reason_codes[-1],"Point-in-time structure/ATR candidates, boundary and normalized distance validated",tuple(x.candidate_id for x in candidates)))
        trace=DecisionTrace(decision_id,snapshot.snapshot_id,as_of,checks,DecisionOutcome.NO_ACTION if blocked else DecisionOutcome.ACCEPTED,reason_codes[-1],as_of,"THESIS_AUTHORITY" if blocked else None);result=InvalidationResult(decision,trace)
        for x in candidates:self._candidates[x.candidate_id]=x
        self._decisions[decision_id]=decision;self.ledger.add_decision(decision);self._cache[key]=result;self._bound();self._record("invalidation_no_action" if blocked else "invalidation_evaluation_completed",{"decision_id":decision_id});return result
    def reconcile(self,invalidation:InvalidationResult,snapshot:StrategyDecisionSnapshot,capital:ResearchCapitalContext,equity_history:tuple[ResearchEquityObservation,...],volatility_evidence:VolatilityEvidence,strategy_health:HealthEvidence,data_health:HealthEvidence,sizing_engine:RiskSizingEngine,adaptive_engine:AdaptiveRiskEngine,cost:ResearchCostBuffer|None=None):
        decision=invalidation.decision
        if decision.eligibility not in (InvalidationEligibility.ELIGIBLE,InvalidationEligibility.ELIGIBLE_WITH_RESTRICTIONS) or decision.normalized_distance is None:return RiskReconciliationResult(invalidation,None,None,ZERO,ZERO,("INV_NO_ACTION",))
        distance=InvalidationDistanceContext(decision.normalized_distance.distance_id,decision.normalized_distance.normalized_distance,InvalidationSource.STRUCTURE_RESEARCH_METADATA,decision.decision_id,decision.as_of_timestamp_utc,decision.as_of_timestamp_utc,DistanceHealth.VALID,decision.configuration_snapshot_id)
        p17=sizing_engine.size(snapshot,capital,distance,cost)
        if p17.exposure_decision.eligibility not in (SizingEligibility.ELIGIBLE,SizingEligibility.ELIGIBLE_WITH_RESTRICTIONS):return RiskReconciliationResult(invalidation,p17,None,ZERO,ZERO,("INV_PROMPT17_REJECTED","INV_NO_ACTION"))
        p18=adaptive_engine.evaluate(p17,equity_history,volatility_evidence,strategy_health,data_health);exposure=p18.decision.adapted_exposure.quantized_simulated_exposure;risk=p18.decision.adapted_exposure.recalculated_risk
        if risk>p18.decision.adaptive_risk_amount or p18.decision.adaptive_risk_amount>p17.risk_budget.base_risk_amount:raise ValueError("INV_FINAL_RISK_INVARIANT_FAILED")
        return RiskReconciliationResult(invalidation,p17,p18,exposure,risk,("INV_RISK_RECONCILED",) if exposure>0 else ("INV_NO_ACTION",))
    def observe(self,decision:ThesisInvalidationDecision,observed_value,observed_at,confirmed_at,observation_ids=()):
        if decision.lifecycle is not InvalidationLifecycle.ACTIVE or decision.research_invalidation_boundary is None:return None
        if confirmed_at<observed_at:raise ValueError("INV_CONFIRMATION_TIME_INVALID")
        value=_decimal(observed_value);boundary=decision.research_invalidation_boundary;condition=self.configuration.default_condition
        beyond=value<=boundary if decision.direction is ResearchDirection.BULLISH else value>=boundary
        if not beyond:return None
        identity=deterministic_id("invalidation_event",decision.decision_id,str(boundary),condition.name,observed_at.isoformat(),confirmed_at.isoformat(),*observation_ids)
        event=InvalidationEvent(identity,decision.decision_id,decision.selected_candidate_id or "NONE",condition,observed_at,confirmed_at,tuple(observation_ids),InvalidationLifecycle.INVALIDATED,("INV_THESIS_INVALIDATED",))
        self._events[identity]=event;self.ledger.add_event(event);self._bound();self._record("thesis_invalidated",{"event_id":identity});return event
    def _lineage(self,reference,evidence):return reference.dataset_id==evidence.dataset_id and reference.instrument_id==evidence.instrument_id and reference.timeframe==evidence.timeframe
    def _structure_candidate(self,reference,evidence):
        raw=(reference.value-evidence.reference_value) if evidence.direction is ResearchDirection.BULLISH else (evidence.reference_value-reference.value)
        health=InvalidationHealth.HEALTHY if raw>0 else InvalidationHealth.INVALID;identity=deterministic_id("invalidation_candidate","STRUCTURE",reference.reference_point_id,evidence.evidence_id,str(evidence.reference_value),str(raw))
        return InvalidationCandidate(identity,InvalidationMethod.STRUCTURE,evidence.direction,reference.reference_point_id,evidence.reference_value,raw,(evidence.evidence_id,),health,EvidenceAvailability.AVAILABLE,("INV_STRUCTURE_ACCEPTED",) if raw>0 else ("INV_STRUCTURE_DIRECTION_INVALID",))
    def _atr_candidate(self,reference,atr,profile):
        direction=profile.direction;raw=atr.atr_value*self.configuration.atr_multiplier;boundary=reference.value-raw if direction is ResearchDirection.BULLISH else reference.value+raw;identity=deterministic_id("invalidation_candidate","ATR",reference.reference_point_id,atr.evidence_id,str(raw),direction.name)
        return InvalidationCandidate(identity,InvalidationMethod.ATR_NORMALIZED,direction,reference.reference_point_id,boundary,raw,(atr.evidence_id,),InvalidationHealth.HEALTHY,EvidenceAvailability.AVAILABLE,("INV_ATR_ACCEPTED",))
    def _hybrid_candidate(self,reference,structure,atr,profile):
        if profile.hybrid_policy is HybridPolicy.MOST_CONSERVATIVE_VALID_DISTANCE:raw=max(structure.raw_distance,atr.raw_distance)
        else:raw=structure.raw_distance+atr.raw_distance
        boundary=reference.value-raw if structure.direction is ResearchDirection.BULLISH else reference.value+raw;identity=deterministic_id("invalidation_candidate","HYBRID",structure.candidate_id,atr.candidate_id,profile.hybrid_policy.name,str(raw))
        return InvalidationCandidate(identity,InvalidationMethod.HYBRID,structure.direction,reference.reference_point_id,boundary,raw,(structure.candidate_id,atr.candidate_id),InvalidationHealth.HEALTHY,EvidenceAvailability.AVAILABLE,("INV_HYBRID_SELECTED",))
    def _eligible_candidates(self,candidates,profile):
        valid=tuple(x for x in candidates if x.health is InvalidationHealth.HEALTHY and x.raw_distance>0)
        primary=tuple(x for x in valid if x.method is profile.method)
        if primary:return primary
        if not profile.fallback_allowed:return ()
        return tuple(x for x in valid if x.method in profile.fallback_methods)
    def _select(self,candidates,profile):return max(candidates,key=lambda x:(x.raw_distance,x.candidate_id),default=None)
    def _bound(self):
        for store,limit in ((self._candidates,self.configuration.maximum_candidates),(self._decisions,self.configuration.maximum_decisions),(self._events,self.configuration.maximum_events),(self._cache,self.configuration.maximum_cache_entries)):
            while len(store)>limit:store.popitem(last=False)
    def recovery_state(self):return {"engine_version":INVALIDATION_ENGINE_VERSION,"configuration_snapshot_id":self.configuration.configuration_snapshot_id,"ledger":self.ledger.state(),"last_decision_id":next(reversed(self._decisions),None)}
    def restore(self,state):return self.validate_recovery(state) and self.ledger.restore(state.get("ledger",{}))
    def validate_recovery(self,state):return state.get("engine_version")==INVALIDATION_ENGINE_VERSION and state.get("configuration_snapshot_id")==self.configuration.configuration_snapshot_id
