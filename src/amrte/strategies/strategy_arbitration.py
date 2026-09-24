"""Deterministic research-hypothesis arbitration; no financial execution semantics."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum,auto
from itertools import combinations
from types import MappingProxyType

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation,DecisionOutcome,DecisionStatus,DecisionTrace
from amrte.market.intelligence import IntelligenceAvailability,IntelligenceHealth,MarketIntelligenceSnapshot
from amrte.market.regime import PrimaryRegime
from .framework import (CandidateStatus,FinalResearchAction,QualificationState,ScoreHealth,
    SignalDirection,StrategyEvaluation,StrategyFamily,StrategyHealth,StrategyReadiness)

ARBITRATION_ENGINE_VERSION="1.0";ARBITRATION_SCHEMA_VERSION="1.0"

class ResearchDirection(Enum):BULLISH=auto();BEARISH=auto();NEUTRAL=auto();NON_DIRECTIONAL=auto();UNKNOWN=auto()
class ConflictType(Enum):NO_CONFLICT=auto();DIRECTIONAL_CONFLICT=auto();REGIME_CONFLICT=auto();THESIS_CONFLICT=auto();EVIDENCE_CONFLICT=auto();TIMEFRAME_CONFLICT=auto();DUPLICATE_HYPOTHESIS=auto();OVERLAPPING_HYPOTHESIS=auto();HEALTH_CONFLICT=auto();RESTRICTION_CONFLICT=auto();SCORE_TIE=auto();INCOMPARABLE=auto();UNKNOWN=auto()
class CompatibilityState(Enum):COMPATIBLE=auto();CONDITIONALLY_COMPATIBLE=auto();CONFLICTING=auto();MUTUALLY_EXCLUSIVE=auto();DUPLICATE=auto();INCOMPARABLE=auto();UNKNOWN=auto()
class ConflictSeverity(Enum):NONE=auto();LOW=auto();MODERATE=auto();HIGH=auto();CRITICAL=auto();UNKNOWN=auto()
class ResolutionState(Enum):UNRESOLVED=auto();RESOLVED_PREFERRED=auto();RESOLVED_SUPPRESSED=auto();RESOLVED_COEXIST=auto();RESOLVED_NO_ACTION=auto();INVALID=auto();UNKNOWN=auto()
class ArbitrationPolicy(Enum):REJECT_CONFLICTS=auto();REGIME_NATIVE_PRIORITY=auto();CONFIDENCE_PRIORITY=auto();QUALITY_PRIORITY=auto();HYBRID_CONSERVATIVE=auto();COMPATIBILITY_ONLY=auto();CUSTOM_CONFIGURED=auto()
class CombinationMode(Enum):ALLOW_NONE=auto();ALLOW_SAME_DIRECTION_COMPATIBLE=auto();ALLOW_EXPLICIT_PAIRS_ONLY=auto()
class ArbitrationOutcome(Enum):NO_ACTION=auto();SINGLE_PREFERRED=auto();MULTIPLE_COMPATIBLE=auto();ALL_REJECTED=auto();BLOCKED=auto();INCOMPLETE=auto();UNKNOWN=auto()
class StrategySystemHealth(Enum):HEALTHY=auto();DEGRADED=auto();RESTRICTED=auto();CONFLICTED=auto();UNAVAILABLE=auto();INVALID=auto();UNKNOWN=auto()
class ResearchAvailability(Enum):AVAILABLE=auto();AVAILABLE_WITH_RESTRICTIONS=auto();NO_ACTION=auto();NOT_AVAILABLE=auto();UNKNOWN=auto()

@dataclass(frozen=True)
class ArbitrationConfiguration:
    enabled:bool=True;policy:ArbitrationPolicy=ArbitrationPolicy.HYBRID_CONSERVATIVE
    policy_version:str="1.0";configuration_snapshot_id:str="ARBITRATION_DEFAULT_RESEARCH"
    require_same_intelligence_snapshot:bool=True;reject_expired:bool=True;allow_degraded:bool=False
    regime_native_priority:bool=True;minimum_confidence:float=0;minimum_quality:float=0
    minimum_completeness:float=50;maximum_uncertainty:float=80
    minimum_confidence_difference:float=10;minimum_quality_difference:float=10;tie_tolerance:float=2
    combination_mode:CombinationMode=CombinationMode.ALLOW_EXPLICIT_PAIRS_ONLY
    allowed_pairs:tuple[tuple[str,str],...]=();strategy_priority:tuple[str,...]=();abstention_enabled:bool=True
    maximum_groups:int=256;maximum_decisions:int=256;maximum_conflicts:int=512;maximum_cache_entries:int=256
    def validate(self):
        errors=[]
        for value in (self.minimum_confidence,self.minimum_quality,self.minimum_completeness,self.maximum_uncertainty,self.minimum_confidence_difference,self.minimum_quality_difference,self.tie_tolerance):
            if not 0<=value<=100:errors.append("ARB_INVALID_THRESHOLD")
        if min(self.maximum_groups,self.maximum_decisions,self.maximum_conflicts,self.maximum_cache_entries)<1:errors.append("ARB_INVALID_BOUND")
        if len(self.strategy_priority)!=len(set(self.strategy_priority)):errors.append("ARB_DUPLICATE_PRIORITY")
        normalized=[tuple(sorted(pair)) for pair in self.allowed_pairs]
        if any(len(pair)!=2 or not all(pair) for pair in self.allowed_pairs) or len(normalized)!=len(set(normalized)):errors.append("ARB_INVALID_ALLOWED_PAIR")
        if not self.abstention_enabled and not self.strategy_priority:errors.append("ARB_NO_DETERMINISTIC_ABSTENTION_OR_TIEBREAK")
        return tuple(dict.fromkeys(errors))

@dataclass(frozen=True)
class StrategyOpinion:
    opinion_id:str;strategy_id:str;strategy_version:str;strategy_family:StrategyFamily;variant_id:str|None
    instrument_id:str;direction:ResearchDirection;candidate_id:str;research_signal_id:str|None
    qualification:QualificationState;score_id:str;overall_score:float;confidence:float;quality:float
    completeness:float;agreement:float;uncertainty:float;conflict_score:float
    strategy_health:StrategyHealth;strategy_readiness:StrategyReadiness;native_regimes:tuple[str,...]
    hard_restrictions:tuple[str,...];soft_restrictions:tuple[str,...]
    supporting_evidence_ids:tuple[str,...];conflicting_evidence_ids:tuple[str,...];missing_evidence_ids:tuple[str,...]
    created_at_utc:datetime;available_at_utc:datetime;expires_at_utc:datetime
    market_intelligence_snapshot_id:str;configuration_snapshot_id:str;recovery_epoch:int

@dataclass(frozen=True)
class ArbitrationGroup:
    arbitration_group_id:str;instrument_id:str;as_of_timestamp_utc:datetime;market_intelligence_snapshot_id:str
    opinions:tuple[StrategyOpinion,...];group_health:StrategySystemHealth;configuration_snapshot_id:str;recovery_epoch:int

@dataclass(frozen=True)
class StrategyCompatibilityAssessment:
    assessment_id:str;opinion_a_id:str;opinion_b_id:str;direction_relationship:str;thesis_relationship:str
    evidence_overlap:float;regime_relationship:str;timeframe_relationship:str;compatibility:CompatibilityState
    conflict_types:tuple[ConflictType,...];reason_codes:tuple[str,...]

@dataclass(frozen=True)
class StrategyConflict:
    conflict_id:str;arbitration_group_id:str;opinion_ids:tuple[str,...];conflict_types:tuple[ConflictType,...]
    severity:ConflictSeverity;description_code:str;evidence_references:tuple[str,...]
    resolution_status:ResolutionState;resolution_reason_codes:tuple[str,...]
    as_of_timestamp_utc:datetime;configuration_snapshot_id:str

@dataclass(frozen=True)
class ArbitrationAbstention:
    reason_codes:tuple[str,...];conflicting_opinion_ids:tuple[str,...]
    missing_evidence:tuple[str,...];required_resolution_conditions:tuple[str,...]

@dataclass(frozen=True)
class ArbitratedStrategyDecision:
    decision_id:str;arbitration_group_id:str;instrument_id:str;as_of_timestamp_utc:datetime
    outcome:ArbitrationOutcome;preferred_opinion_id:str|None;permitted_opinion_ids:tuple[str,...]
    suppressed_opinion_ids:tuple[str,...];rejected_opinion_ids:tuple[str,...];conflict_ids:tuple[str,...]
    arbitration_policy:ArbitrationPolicy;policy_version:str;regime_context:str;decision_confidence:float
    decision_quality:float;restrictions:tuple[str,...];reason_codes:tuple[str,...]
    market_intelligence_snapshot_id:str;configuration_snapshot_id:str;arbitration_engine_version:str
    recovery_epoch:int;abstention:ArbitrationAbstention|None

@dataclass(frozen=True)
class StrategyDecisionSnapshot:
    snapshot_id:str;instrument_id:str;as_of_timestamp_utc:datetime;market_intelligence_snapshot_id:str
    strategy_opinion_ids:tuple[str,...];arbitration_group_id:str;arbitration_decision_id:str
    outcome:ArbitrationOutcome;preferred_research_signal_id:str|None;permitted_research_signal_ids:tuple[str,...]
    suppressed_research_signal_ids:tuple[str,...];conflict_ids:tuple[str,...]
    overall_strategy_health:StrategySystemHealth;research_availability:ResearchAvailability
    restrictions:tuple[str,...];reason_codes:tuple[str,...];configuration_snapshot_id:str
    strategy_system_version:str;recovery_epoch:int

@dataclass(frozen=True)
class ArbitrationResult:
    group:ArbitrationGroup;assessments:tuple[StrategyCompatibilityAssessment,...]
    conflicts:tuple[StrategyConflict,...];decision:ArbitratedStrategyDecision;snapshot:StrategyDecisionSnapshot
    decision_trace:DecisionTrace

class ArbitrationPolicyRegistry:
    def __init__(self):self._policies={}
    def register(self,name:str,policy:ArbitrationPolicy):
        if not name or name in self._policies:raise ValueError("DUPLICATE_ARBITRATION_POLICY")
        self._policies[name]=policy
    def get(self,name):return self._policies[name]
    def all(self):return tuple((name,self._policies[name]) for name in sorted(self._policies))

def _direction(value):
    return {SignalDirection.LONG_BIAS:ResearchDirection.BULLISH,SignalDirection.SHORT_BIAS:ResearchDirection.BEARISH,SignalDirection.NEUTRAL:ResearchDirection.NEUTRAL,SignalDirection.BIDIRECTIONAL:ResearchDirection.NON_DIRECTIONAL}.get(value,ResearchDirection.UNKNOWN)

class StrategyArbitrationEngine:
    def __init__(self,configuration:ArbitrationConfiguration=ArbitrationConfiguration(),audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit;self._groups=OrderedDict();self._decisions=OrderedDict();self._conflicts=OrderedDict();self._cache=OrderedDict()
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
    def _opinion(self,evaluation,metadata,intelligence):
        candidate=evaluation.candidate;score=evaluation.score;signal=evaluation.research_signal
        if candidate is None or score is None:return None,"ARB_NO_CANDIDATE"
        if candidate.instrument_id!=intelligence.instrument_id or candidate.market_intelligence_snapshot_id!=intelligence.market_intelligence_snapshot_id:return None,"ARB_INVALID_LINEAGE"
        if candidate.as_of_timestamp_utc>intelligence.as_of_timestamp_utc:return None,"ARB_FUTURE_SIGNAL"
        if candidate.recovery_epoch!=intelligence.recovery_epoch:return None,"ARB_RECOVERY_MISMATCH"
        if candidate.candidate_status not in (CandidateStatus.QUALIFIED,CandidateStatus.CONDITIONALLY_QUALIFIED):return None,"ARB_CANDIDATE_NOT_QUALIFIED"
        if score.score_health in (ScoreHealth.INVALID,ScoreHealth.UNAVAILABLE,ScoreHealth.UNKNOWN):return None,"ARB_SCORE_UNHEALTHY"
        if evaluation.strategy_health in (StrategyHealth.INVALID,StrategyHealth.UNAVAILABLE,StrategyHealth.UNKNOWN):return None,"ARB_STRATEGY_UNHEALTHY"
        if not self.configuration.allow_degraded and evaluation.strategy_health is StrategyHealth.DEGRADED:return None,"ARB_STRATEGY_DEGRADED"
        if self.configuration.reject_expired and candidate.expires_at_utc<intelligence.as_of_timestamp_utc:return None,"ARB_EXPIRED_SIGNAL"
        if score.completeness<self.configuration.minimum_completeness or score.uncertainty>self.configuration.maximum_uncertainty:return None,"ARB_INCOMPLETE_EVIDENCE"
        if score.confidence<self.configuration.minimum_confidence or score.quality<self.configuration.minimum_quality:return None,"ARB_SCORE_BELOW_MINIMUM"
        support=tuple(sorted({item for e in candidate.supporting_evidence for item in (e.evidence_id,*e.upstream_evidence_ids)}));conflicting=tuple(sorted({item for e in candidate.conflicting_evidence for item in (e.evidence_id,*e.upstream_evidence_ids)}));missing=tuple(sorted({item for e in candidate.missing_evidence for item in (e.evidence_id,*e.upstream_evidence_ids)}))
        restrictions=tuple(sorted(signal.restrictions if signal else ()))
        opinion_id=deterministic_id("strategy_opinion",candidate.signal_candidate_id,score.signal_score_id,signal.research_signal_id if signal else "NO_SIGNAL",evaluation.strategy_health.name)
        variant=metadata.identity.strategy_id.rsplit("_",1)[-1] if metadata.identity.family is StrategyFamily.BREAKOUT else None
        return StrategyOpinion(opinion_id,metadata.identity.strategy_id,metadata.identity.version,metadata.identity.family,variant,candidate.instrument_id,_direction(candidate.direction),candidate.signal_candidate_id,signal.research_signal_id if signal else None,evaluation.qualification.status,score.signal_score_id,score.overall_score,score.confidence,score.quality,score.completeness,score.agreement,score.uncertainty,score.conflict_penalty,evaluation.strategy_health,evaluation.readiness,tuple(sorted(metadata.allowed_regimes)),restrictions,(),support,conflicting,missing,candidate.as_of_timestamp_utc,candidate.as_of_timestamp_utc,candidate.expires_at_utc,candidate.market_intelligence_snapshot_id,candidate.configuration_snapshot_id,candidate.recovery_epoch),None
    def _assess(self,a,b,regime):
        types=[];reasons=[];same=a.direction is b.direction;opposite={a.direction,b.direction}=={ResearchDirection.BULLISH,ResearchDirection.BEARISH}
        shared=set(a.supporting_evidence_ids)&set(b.supporting_evidence_ids);union=set(a.supporting_evidence_ids)|set(b.supporting_evidence_ids);overlap=len(shared)/len(union) if union else 0
        if a.candidate_id==b.candidate_id or (a.research_signal_id and a.research_signal_id==b.research_signal_id):types.append(ConflictType.DUPLICATE_HYPOTHESIS);reasons.append("ARB_DUPLICATE_HYPOTHESIS")
        if opposite:types.append(ConflictType.DIRECTIONAL_CONFLICT);reasons.append("ARB_OPPOSING_DIRECTION")
        if a.strategy_family is not b.strategy_family and {a.strategy_family,b.strategy_family}=={StrategyFamily.BREAKOUT,StrategyFamily.MEAN_REVERSION}:types.append(ConflictType.THESIS_CONFLICT);reasons.append("ARB_BREAKOUT_RANGE_THESIS_CONFLICT")
        if overlap>0:types.append(ConflictType.OVERLAPPING_HYPOTHESIS);reasons.append("ARB_SHARED_EVIDENCE")
        if regime.name not in a.native_regimes or regime.name not in b.native_regimes:types.append(ConflictType.REGIME_CONFLICT);reasons.append("ARB_REGIME_COMPATIBILITY_DIFFERS")
        if abs(a.overall_score-b.overall_score)<=self.configuration.tie_tolerance:types.append(ConflictType.SCORE_TIE);reasons.append("ARB_TIE")
        if ConflictType.DUPLICATE_HYPOTHESIS in types:state=CompatibilityState.DUPLICATE
        elif opposite:state=CompatibilityState.MUTUALLY_EXCLUSIVE
        elif ConflictType.THESIS_CONFLICT in types:state=CompatibilityState.CONFLICTING
        elif same:state=CompatibilityState.CONDITIONALLY_COMPATIBLE
        else:state=CompatibilityState.INCOMPARABLE
        identity=deterministic_id("compatibility",*sorted((a.opinion_id,b.opinion_id)),state.name,*(x.name for x in sorted(types,key=lambda x:x.name)))
        return StrategyCompatibilityAssessment(identity,*sorted((a.opinion_id,b.opinion_id)),"SAME" if same else "OPPOSITE" if opposite else "OTHER","DISTINCT_FAMILY" if a.strategy_family is not b.strategy_family else "SAME_FAMILY",overlap,"BOTH_NATIVE" if regime.name in a.native_regimes and regime.name in b.native_regimes else "MIXED","DECLARED_ROLES",state,tuple(sorted(set(types),key=lambda x:x.name)) or (ConflictType.NO_CONFLICT,),tuple(sorted(set(reasons))) or ("ARB_NO_CONFLICT",))
    def _conflict(self,group,assessment):
        material=tuple(x for x in assessment.conflict_types if x is not ConflictType.NO_CONFLICT)
        if not material:return None
        severity=ConflictSeverity.CRITICAL if ConflictType.DIRECTIONAL_CONFLICT in material else ConflictSeverity.HIGH if ConflictType.THESIS_CONFLICT in material else ConflictSeverity.MODERATE if ConflictType.DUPLICATE_HYPOTHESIS in material else ConflictSeverity.LOW
        identity=deterministic_id("strategy_conflict",group.arbitration_group_id,assessment.assessment_id,severity.name)
        return StrategyConflict(identity,group.arbitration_group_id,(assessment.opinion_a_id,assessment.opinion_b_id),material,severity,assessment.reason_codes[0],(),ResolutionState.UNRESOLVED,(),group.as_of_timestamp_utc,self.configuration.configuration_snapshot_id)
    def arbitrate(self,intelligence:MarketIntelligenceSnapshot,evaluations,metadata_by_strategy):
        self._record("arbitration_started",{"instrument_id":intelligence.instrument_id,"as_of":intelligence.as_of_timestamp_utc.isoformat()})
        cfg=self.configuration;opinions=[];rejected=[];reasons=[]
        if not cfg.enabled:return self._empty(intelligence,ArbitrationOutcome.BLOCKED,"ARB_DISABLED")
        if intelligence.overall_intelligence_health in (IntelligenceHealth.UNTRUSTED,IntelligenceHealth.UNAVAILABLE,IntelligenceHealth.UNKNOWN) or intelligence.intelligence_availability in (IntelligenceAvailability.NOT_AVAILABLE,IntelligenceAvailability.UNKNOWN):return self._empty(intelligence,ArbitrationOutcome.BLOCKED,"ARB_INTELLIGENCE_BLOCKED")
        for evaluation in evaluations:
            metadata=metadata_by_strategy.get(evaluation.strategy_id)
            if metadata is None:rejected.append(evaluation.strategy_id);reasons.append("ARB_UNKNOWN_STRATEGY");continue
            opinion,error=self._opinion(evaluation,metadata,intelligence)
            if opinion is None:rejected.append(evaluation.strategy_id);reasons.append(error);self._record("strategy_opinion_excluded",{"strategy_id":evaluation.strategy_id,"reason":error})
            else:opinions.append(opinion);self._record("strategy_opinion_accepted",{"opinion_id":opinion.opinion_id})
        opinions=tuple(sorted(opinions,key=lambda x:x.opinion_id))
        group_id=deterministic_id("arbitration_group",intelligence.instrument_id,intelligence.as_of_timestamp_utc.isoformat(),intelligence.market_intelligence_snapshot_id,cfg.configuration_snapshot_id,cfg.policy_version,*(x.opinion_id for x in opinions))
        group_health=StrategySystemHealth.UNAVAILABLE if not opinions else StrategySystemHealth.DEGRADED if rejected else StrategySystemHealth.HEALTHY
        group=ArbitrationGroup(group_id,intelligence.instrument_id,intelligence.as_of_timestamp_utc,intelligence.market_intelligence_snapshot_id,opinions,group_health,cfg.configuration_snapshot_id,intelligence.recovery_epoch)
        if group_id in self._cache:
            self._cache.move_to_end(group_id);return self._cache[group_id]
        assessments=tuple(self._assess(a,b,intelligence.regime.primary_regime) for a,b in combinations(opinions,2));conflicts=tuple(x for x in (self._conflict(group,a) for a in assessments) if x)
        decision=self._resolve(group,assessments,conflicts,tuple(sorted(set(rejected))),tuple(sorted(set(reasons))),intelligence.regime.primary_regime)
        signal_by_opinion={o.opinion_id:o.research_signal_id for o in opinions}
        health=StrategySystemHealth.CONFLICTED if conflicts and decision.outcome is ArbitrationOutcome.NO_ACTION else StrategySystemHealth.RESTRICTED if decision.outcome in (ArbitrationOutcome.BLOCKED,ArbitrationOutcome.ALL_REJECTED) else group_health
        availability=ResearchAvailability.AVAILABLE if decision.outcome in (ArbitrationOutcome.SINGLE_PREFERRED,ArbitrationOutcome.MULTIPLE_COMPATIBLE) else ResearchAvailability.NO_ACTION if decision.outcome is ArbitrationOutcome.NO_ACTION else ResearchAvailability.NOT_AVAILABLE
        snapshot_id=deterministic_id("strategy_decision_snapshot",decision.decision_id,group_id,ARBITRATION_ENGINE_VERSION)
        snapshot=StrategyDecisionSnapshot(snapshot_id,intelligence.instrument_id,intelligence.as_of_timestamp_utc,intelligence.market_intelligence_snapshot_id,tuple(o.opinion_id for o in opinions),group_id,decision.decision_id,decision.outcome,signal_by_opinion.get(decision.preferred_opinion_id),tuple(x for x in (signal_by_opinion.get(i) for i in decision.permitted_opinion_ids) if x),tuple(x for x in (signal_by_opinion.get(i) for i in decision.suppressed_opinion_ids) if x),decision.conflict_ids,health,availability,decision.restrictions,decision.reason_codes,cfg.configuration_snapshot_id,"0.16.0",intelligence.recovery_epoch)
        trace=self._trace(group,assessments,decision)
        result=ArbitrationResult(group,assessments,conflicts,decision,snapshot,trace);self._store(result);self._cache[group_id]=result
        while len(self._cache)>cfg.maximum_cache_entries:self._cache.popitem(last=False)
        self._record("arbitration_completed",{"decision_id":decision.decision_id,"outcome":decision.outcome.name});return result
    def _resolve(self,group,assessments,conflicts,rejected,input_reasons,regime):
        cfg=self.configuration;opinions=group.opinions;preferred=None;permitted=();suppressed=();reason=list(input_reasons);abstention=None
        if not opinions:outcome=ArbitrationOutcome.ALL_REJECTED;reason.append("ARB_NO_ELIGIBLE_STRATEGIES")
        elif len(opinions)==1:outcome=ArbitrationOutcome.SINGLE_PREFERRED;preferred=opinions[0].opinion_id;permitted=(preferred,);reason.append("ARB_SINGLE_ELIGIBLE")
        else:
            material=any(a.compatibility in (CompatibilityState.MUTUALLY_EXCLUSIVE,CompatibilityState.CONFLICTING,CompatibilityState.INCOMPARABLE,CompatibilityState.UNKNOWN) for a in assessments)
            duplicates=any(a.compatibility is CompatibilityState.DUPLICATE for a in assessments)
            explicit=all(tuple(sorted((a.strategy_id,b.strategy_id))) in {tuple(sorted(x)) for x in cfg.allowed_pairs} for a,b in combinations(opinions,2))
            if not material and not duplicates and (cfg.combination_mode is CombinationMode.ALLOW_SAME_DIRECTION_COMPATIBLE or (cfg.combination_mode is CombinationMode.ALLOW_EXPLICIT_PAIRS_ONLY and explicit)):
                outcome=ArbitrationOutcome.MULTIPLE_COMPATIBLE;permitted=tuple(o.opinion_id for o in opinions);reason.append("ARB_MULTIPLE_COMPATIBLE")
            else:
                winner=self._preferred(opinions,regime)
                if winner is not None and cfg.policy is not ArbitrationPolicy.REJECT_CONFLICTS:
                    outcome=ArbitrationOutcome.SINGLE_PREFERRED;preferred=winner.opinion_id;permitted=(preferred,);suppressed=tuple(o.opinion_id for o in opinions if o.opinion_id!=preferred);reason.append("ARB_MEANINGFUL_PREFERENCE")
                else:
                    outcome=ArbitrationOutcome.NO_ACTION;suppressed=tuple(o.opinion_id for o in opinions);reason.extend(("ARB_UNRESOLVED_CONFLICT","ARB_NO_ACTION"));abstention=ArbitrationAbstention(tuple(sorted(set(reason))),suppressed,(),("MEANINGFUL_QUALITY_OR_REGIME_SEPARATION",))
        confidence=100 if len(opinions)==1 else 70 if outcome is ArbitrationOutcome.SINGLE_PREFERRED else 60 if outcome is ArbitrationOutcome.MULTIPLE_COMPATIBLE else 0
        quality=sum(o.quality for o in opinions)/len(opinions) if opinions else 0
        decision_id=deterministic_id("arbitration_decision",group.arbitration_group_id,outcome.name,preferred or "NONE",*(sorted(permitted)),cfg.policy.name,cfg.policy_version)
        restrictions=tuple(sorted(set(x for o in opinions for x in o.hard_restrictions)))
        return ArbitratedStrategyDecision(decision_id,group.arbitration_group_id,group.instrument_id,group.as_of_timestamp_utc,outcome,preferred,tuple(sorted(permitted)),tuple(sorted(suppressed)),rejected,tuple(c.conflict_id for c in conflicts),cfg.policy,cfg.policy_version,regime.name,confidence,quality,restrictions,tuple(sorted(set(reason))),group.market_intelligence_snapshot_id,cfg.configuration_snapshot_id,ARBITRATION_ENGINE_VERSION,group.recovery_epoch,abstention)
    def _preferred(self,opinions,regime):
        cfg=self.configuration;native=[o for o in opinions if regime.name in o.native_regimes]
        if cfg.regime_native_priority and len(native)==1 and regime not in (PrimaryRegime.UNKNOWN,PrimaryRegime.ABNORMAL):return native[0]
        ranked=sorted(opinions,key=lambda o:(-o.completeness,o.uncertainty,-o.quality,-o.confidence,-o.overall_score,o.opinion_id))
        a,b=ranked[0],ranked[1]
        if cfg.policy is ArbitrationPolicy.CONFIDENCE_PRIORITY and a.confidence-b.confidence>=cfg.minimum_confidence_difference:return a
        if cfg.policy is ArbitrationPolicy.QUALITY_PRIORITY and a.quality-b.quality>=cfg.minimum_quality_difference:return a
        if cfg.policy is ArbitrationPolicy.HYBRID_CONSERVATIVE and (a.quality-b.quality>=cfg.minimum_quality_difference or a.confidence-b.confidence>=cfg.minimum_confidence_difference):return a
        for strategy_id in cfg.strategy_priority:
            match=next((o for o in opinions if o.strategy_id==strategy_id),None)
            if match:return match
        return None
    def _empty(self,intelligence,outcome,reason):
        group_id=deterministic_id("arbitration_group",intelligence.market_intelligence_snapshot_id,self.configuration.configuration_snapshot_id,"EMPTY")
        group=ArbitrationGroup(group_id,intelligence.instrument_id,intelligence.as_of_timestamp_utc,intelligence.market_intelligence_snapshot_id,(),StrategySystemHealth.UNAVAILABLE,self.configuration.configuration_snapshot_id,intelligence.recovery_epoch)
        decision_id=deterministic_id("arbitration_decision",group_id,outcome.name,reason)
        abstention=ArbitrationAbstention((reason,),(),(),("VALID_ELIGIBLE_OPINION",))
        decision=ArbitratedStrategyDecision(decision_id,group_id,intelligence.instrument_id,intelligence.as_of_timestamp_utc,outcome,None,(),(),(),(),self.configuration.policy,self.configuration.policy_version,intelligence.regime.primary_regime.name,0,0,intelligence.restrictions,(reason,),intelligence.market_intelligence_snapshot_id,self.configuration.configuration_snapshot_id,ARBITRATION_ENGINE_VERSION,intelligence.recovery_epoch,abstention)
        snapshot=StrategyDecisionSnapshot(deterministic_id("strategy_decision_snapshot",decision_id),intelligence.instrument_id,intelligence.as_of_timestamp_utc,intelligence.market_intelligence_snapshot_id,(),group_id,decision_id,outcome,None,(),(),(),StrategySystemHealth.UNAVAILABLE,ResearchAvailability.NOT_AVAILABLE,intelligence.restrictions,(reason,),self.configuration.configuration_snapshot_id,"0.16.0",intelligence.recovery_epoch)
        trace=self._trace(group,(),decision);result=ArbitrationResult(group,(),(),decision,snapshot,trace);self._store(result);return result
    def _trace(self,group,assessments,decision):
        checks=(
          DecisionEvaluation("INPUT_VALIDATION",DecisionStatus.PASSED,"ARB_INPUT_FROZEN","Immutable opinion set and lineage validated",tuple(o.opinion_id for o in group.opinions)),
          DecisionEvaluation("HEALTH_RESTRICTIONS_EXPIRATION",DecisionStatus.PASSED,"ARB_ELIGIBILITY_FILTERED","Health, restrictions, completeness and expiration applied",tuple(o.candidate_id for o in group.opinions)),
          DecisionEvaluation("PAIRWISE_COMPATIBILITY",DecisionStatus.PASSED,"ARB_COMPATIBILITY_CLASSIFIED","All deterministic opinion pairs classified",tuple(a.assessment_id for a in assessments)),
          DecisionEvaluation("POLICY",DecisionStatus.PASSED,"ARB_POLICY_APPLIED",decision.arbitration_policy.name,(decision.decision_id,)),)
        outcome=DecisionOutcome.ACCEPTED if decision.outcome in (ArbitrationOutcome.SINGLE_PREFERRED,ArbitrationOutcome.MULTIPLE_COMPATIBLE) else DecisionOutcome.BLOCKED if decision.outcome is ArbitrationOutcome.BLOCKED else DecisionOutcome.NO_ACTION
        return DecisionTrace(decision.decision_id,group.arbitration_group_id,group.as_of_timestamp_utc,checks,outcome,decision.reason_codes[-1] if decision.reason_codes else decision.outcome.name,group.as_of_timestamp_utc,None)
    def _store(self,result):
        for store,key,value,maximum in ((self._groups,result.group.arbitration_group_id,result.group,self.configuration.maximum_groups),(self._decisions,result.decision.decision_id,result.decision,self.configuration.maximum_decisions)):
            store[key]=value
            while len(store)>maximum:store.popitem(last=False)
        for conflict in result.conflicts:self._conflicts[conflict.conflict_id]=conflict
        while len(self._conflicts)>self.configuration.maximum_conflicts:self._conflicts.popitem(last=False)
    def recovery_state(self):return {"arbitration_engine_version":ARBITRATION_ENGINE_VERSION,"policy":self.configuration.policy.name,"policy_version":self.configuration.policy_version,"configuration_snapshot_id":self.configuration.configuration_snapshot_id,"last_group_id":next(reversed(self._groups),None),"last_decision_id":next(reversed(self._decisions),None)}
    def validate_recovery(self,state):return state.get("arbitration_engine_version")==ARBITRATION_ENGINE_VERSION and state.get("policy")==self.configuration.policy.name and state.get("policy_version")==self.configuration.policy_version and state.get("configuration_snapshot_id")==self.configuration.configuration_snapshot_id
