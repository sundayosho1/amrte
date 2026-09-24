from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass,field,replace
from datetime import datetime,timedelta
from enum import Enum,auto
from types import MappingProxyType
from typing import Mapping,Protocol

from amrte.core.identity import deterministic_id
from amrte.core.interfaces import IAuditSink,IClock
from amrte.core.observability import DecisionTraceBuilder
from amrte.core.observability_types import DecisionOutcome,DecisionStatus,DecisionTrace
from amrte.market.intelligence import IntelligenceAvailability,IntelligenceHealth,MarketIntelligenceSnapshot

STRATEGY_FRAMEWORK_VERSION="1.0"
STRATEGY_SCHEMA_VERSION="1.0"


class StrategyFamily(Enum):TREND=auto();BREAKOUT=auto();MEAN_REVERSION=auto();CUSTOM=auto()
class RequirementType(Enum):MANDATORY=auto();OPTIONAL=auto();SUPPORTING=auto();CONFLICTING=auto();DISQUALIFYING=auto()
class CapabilityStatus(Enum):SUPPORTED=auto();PARTIALLY_SUPPORTED=auto();UNSUPPORTED=auto();UNAVAILABLE=auto();UNKNOWN=auto()
class ApplicabilityState(Enum):APPLICABLE=auto();CONDITIONAL=auto();NOT_APPLICABLE=auto();BLOCKED=auto();UNKNOWN=auto()
class DetectionState(Enum):DETECTED=auto();NOT_DETECTED=auto();INCOMPLETE=auto();BLOCKED=auto();UNKNOWN=auto()
class EvidenceCategory(Enum):SUPPORTING=auto();CONFLICTING=auto();MISSING=auto();DISQUALIFYING=auto();INFORMATIONAL=auto()
class EvidenceSource(Enum):MARKET_DATA=auto();STRUCTURE=auto();FEATURE=auto();REGIME=auto();SESSION=auto();NEWS_RISK=auto();STRATEGY_DERIVED=auto()
class EvidenceAvailability(Enum):AVAILABLE=auto();UNAVAILABLE=auto();UNKNOWN=auto()
class QualificationState(Enum):QUALIFIED=auto();CONDITIONALLY_QUALIFIED=auto();REJECTED=auto();BLOCKED=auto();INCOMPLETE=auto();UNKNOWN=auto()
class RuleType(Enum):HARD_REQUIREMENT=auto();SOFT_REQUIREMENT=auto();SUPPORTING_REQUIREMENT=auto();DISQUALIFIER=auto()
class ScoreHealth(Enum):VALID=auto();HEALTHY=auto();DEGRADED=auto();INCOMPLETE=auto();UNAVAILABLE=auto();INVALID=auto();UNKNOWN=auto()
class SignalDirection(Enum):LONG_BIAS=auto();SHORT_BIAS=auto();NEUTRAL=auto();BIDIRECTIONAL=auto();UNKNOWN=auto()
class CandidateStatus(Enum):DETECTED=auto();QUALIFIED=auto();CONDITIONALLY_QUALIFIED=auto();REJECTED=auto();BLOCKED=auto();DEFERRED=auto();EXPIRED=auto();INVALIDATED=auto();UNKNOWN=auto()
class StrategyDecision(Enum):CANDIDATE=auto();QUALIFIED_CANDIDATE=auto();REJECT=auto();DEFER=auto();BLOCK=auto();NO_ACTION=auto();UNKNOWN=auto()
class FinalResearchAction(Enum):NO_ACTION=auto();RESEARCH_CANDIDATE=auto();RESEARCH_SIGNAL=auto();DEFERRED=auto();BLOCKED=auto()
class GateType(Enum):RISK=auto();PORTFOLIO=auto();PROTECTION=auto();EXECUTION=auto()
class GateStatus(Enum):APPROVED=auto();CONDITIONAL=auto();REJECTED=auto();BLOCKED=auto();UNAVAILABLE=auto();UNKNOWN=auto()
class SignalLifecycleState(Enum):NOT_EVALUATED=auto();DETECTED=auto();QUALIFIED=auto();SCORED=auto();RESEARCH_SIGNAL=auto();NOT_DETECTED=auto();REJECTED=auto();BLOCKED=auto();DEFERRED=auto();EXPIRED=auto();INVALIDATED=auto();UNKNOWN=auto();NO_ACTION=auto()
class StrategyHealth(Enum):HEALTHY=auto();DEGRADED=auto();RESTRICTED=auto();UNAVAILABLE=auto();INVALID=auto();UNKNOWN=auto()
class StrategyReadiness(Enum):READY=auto();READY_WITH_RESTRICTIONS=auto();NOT_READY=auto();UNKNOWN=auto()
class EvaluationReason(Enum):NEW_BAR=auto();STRUCTURE_CHANGED=auto();FEATURES_CHANGED=auto();REGIME_CHANGED=auto();SESSION_CHANGED=auto();NEWS_RISK_CHANGED=auto();CONFIGURATION_CHANGED=auto();RECOVERY_REBUILD=auto();MANUAL_RESEARCH_EVALUATION=auto()
class EvaluationOutcome(Enum):COMPLETED=auto();NO_ACTION=auto();BLOCKED=auto();ERROR=auto();DEFERRED=auto()


@dataclass(frozen=True)
class StrategyIdentity:
    strategy_id:str;family:StrategyFamily;name:str;version:str
    schema_version:str=STRATEGY_SCHEMA_VERSION;configuration_namespace:str="strategies"
    required_capabilities:tuple[str,...]=()


@dataclass(frozen=True)
class StrategyRequirement:
    requirement_id:str;requirement_type:RequirementType;source:EvidenceSource
    capability:str;timeframe:str|None=None;description:str=""


@dataclass(frozen=True)
class StrategyMetadata:
    identity:StrategyIdentity;description:str;required_timeframes:tuple[str,...]
    required_features:tuple[str,...];required_structure_inputs:tuple[str,...]
    allowed_regimes:tuple[str,...];required_session_context:bool;required_news_context:bool
    minimum_intelligence_health:IntelligenceHealth;requirements:tuple[StrategyRequirement,...]


@dataclass(frozen=True)
class StrategyFrameworkConfiguration:
    enabled:bool=True;allowed_instruments:tuple[str,...]=("FICTIONAL_ALPHA",)
    cooldown_observations:int=0;candidate_ttl_minutes:int=60;maximum_cache_entries:int=256
    maximum_history:int=100;strict:bool=True
    def validate(self)->tuple[str,...]:
        errors=[]
        if self.enabled and not self.allowed_instruments:errors.append("ENABLED_WITHOUT_INSTRUMENTS")
        if self.cooldown_observations<0:errors.append("NEGATIVE_COOLDOWN")
        if self.candidate_ttl_minutes<=0:errors.append("INVALID_TTL")
        if min(self.maximum_cache_entries,self.maximum_history)<1:errors.append("INVALID_BOUND")
        if any(not item.startswith("FICTIONAL_") for item in self.allowed_instruments):errors.append("NON_FICTIONAL_INSTRUMENT")
        return tuple(errors)


@dataclass(frozen=True)
class StrategyApplicability:
    applicability_id:str;strategy_id:str;state:ApplicabilityState
    capability_status:CapabilityStatus;reasons:tuple[str,...];restrictions:tuple[str,...]


@dataclass(frozen=True)
class SignalEvidence:
    evidence_id:str;evidence_type:str;category:EvidenceCategory;source_module:EvidenceSource
    source_snapshot_id:str;instrument_id:str;timeframe:str|None;observed_value:object
    reference_value:object|None;direction:SignalDirection;strength:float|None
    availability:EvidenceAvailability;health:str;explanation_code:str
    upstream_evidence_ids:tuple[str,...]=()


@dataclass(frozen=True)
class DetectionResult:
    detection_id:str;strategy_id:str;instrument_id:str;as_of_timestamp_utc:datetime
    status:DetectionState;evidence:tuple[SignalEvidence,...];missing_evidence:tuple[SignalEvidence,...]
    conflicting_evidence:tuple[SignalEvidence,...];market_intelligence_snapshot_id:str
    configuration_snapshot_id:str


@dataclass(frozen=True)
class QualificationResult:
    qualification_id:str;strategy_id:str;status:QualificationState
    passed_rules:tuple[str,...];failed_rules:tuple[str,...];conditional_rules:tuple[str,...]
    missing_rules:tuple[str,...];blocking_rules:tuple[str,...]


@dataclass(frozen=True)
class SignalScore:
    signal_score_id:str;overall_score:float;component_scores:Mapping[str,float]
    confidence:float;quality:float;completeness:float;conflict_penalty:float
    missing_evidence_penalty:float;score_health:ScoreHealth;explanation:tuple[str,...]
    agreement:float=0.0;uncertainty:float=100.0;positive_contribution:float=0.0
    factor_scores:tuple[object,...]=();group_scores:Mapping[str,float]=field(default_factory=dict)
    conflicts:tuple[object,...]=();supporting_reasons:tuple[str,...]=();conflicting_reasons:tuple[str,...]=()
    missing_reasons:tuple[str,...]=();warnings:tuple[str,...]=()
    scoring_model_id:str="";scoring_model_version:str="";configuration_snapshot_id:str=""
    market_intelligence_snapshot_id:str="";logical_score_id:str="";score_version_id:str=""
    recovery_epoch:int=0
    def __post_init__(self):
        object.__setattr__(self,"component_scores",MappingProxyType(dict(self.component_scores)))
        object.__setattr__(self,"group_scores",MappingProxyType(dict(self.group_scores)))


@dataclass(frozen=True)
class SignalCandidate:
    signal_candidate_id:str;logical_signal_id:str;signal_version_id:str;strategy_id:str
    strategy_family:StrategyFamily;strategy_version:str;instrument_id:str;as_of_timestamp_utc:datetime
    direction:SignalDirection;detection_result_id:str;qualification_result_id:str;signal_score_id:str
    supporting_evidence:tuple[SignalEvidence,...];conflicting_evidence:tuple[SignalEvidence,...]
    missing_evidence:tuple[SignalEvidence,...];disqualifying_evidence:tuple[SignalEvidence,...]
    market_intelligence_snapshot_id:str;candidate_status:CandidateStatus;expires_at_utc:datetime
    reason_codes:tuple[str,...];configuration_snapshot_id:str;recovery_epoch:int


@dataclass(frozen=True)
class GateResult:
    gate_id:str;gate_type:GateType;status:GateStatus;restrictions:tuple[str,...]
    reasons:tuple[str,...];source_module:str;source_version:str


@dataclass(frozen=True)
class ResearchSignal:
    research_signal_id:str;logical_signal_id:str;signal_version_id:str;signal_candidate_id:str
    strategy_id:str;strategy_family:StrategyFamily;instrument_id:str;as_of_timestamp_utc:datetime
    direction:SignalDirection;score:float;confidence:float;quality:float
    strategy_decision:StrategyDecision;risk_gate_status:GateStatus;portfolio_gate_status:GateStatus
    execution_gate_status:GateStatus;final_research_action:FinalResearchAction
    restrictions:tuple[str,...];reason_codes:tuple[str,...]
    market_intelligence_snapshot_id:str;configuration_snapshot_id:str;recovery_epoch:int


@dataclass(frozen=True)
class StrategyState:
    strategy_id:str;instrument_id:str;last_evaluation_id:str|None=None
    last_market_intelligence_snapshot_id:str|None=None;last_logical_signal_id:str|None=None
    cooldown_remaining:int=0;recent_signal_references:tuple[str,...]=()


@dataclass(frozen=True)
class StrategyEvaluationContext:
    evaluation_id:str;strategy_id:str;instrument_id:str;as_of_timestamp_utc:datetime
    market_intelligence:MarketIntelligenceSnapshot;strategy_configuration_snapshot_id:str
    previous_strategy_state:StrategyState|None;evaluation_reason:EvaluationReason;recovery_epoch:int


@dataclass(frozen=True)
class StrategyEvaluation:
    evaluation_id:str;strategy_id:str;instrument_id:str;applicability:StrategyApplicability
    detection:DetectionResult|None;qualification:QualificationResult|None;score:SignalScore|None
    candidate:SignalCandidate|None;research_signal:ResearchSignal|None
    outcome:EvaluationOutcome;final_action:FinalResearchAction;strategy_health:StrategyHealth
    readiness:StrategyReadiness;reason_codes:tuple[str,...];decision_trace:DecisionTrace


class IStrategy(Protocol):
    @property
    def metadata(self)->StrategyMetadata:...
    def applicability(self,context:StrategyEvaluationContext)->StrategyApplicability:...
    def detect(self,context:StrategyEvaluationContext)->DetectionResult:...
    def qualify(self,context:StrategyEvaluationContext,detection:DetectionResult)->QualificationResult:...
    def direction(self,context:StrategyEvaluationContext,detection:DetectionResult)->SignalDirection:...


class ISignalScorer(Protocol):
    def score(self,context:StrategyEvaluationContext,detection:DetectionResult,qualification:QualificationResult)->SignalScore:...


class IStrategyGate(Protocol):
    @property
    def gate_type(self)->GateType:...
    def evaluate(self,candidate:SignalCandidate,context:StrategyEvaluationContext)->GateResult:...


class DeterministicPlaceholderScorer:
    """Contract test scorer only; Prompt 12 owns production scoring semantics."""
    def score(self,context,detection,qualification):
        supporting=sum(item.category is EvidenceCategory.SUPPORTING for item in detection.evidence)
        conflicts=len(detection.conflicting_evidence);missing=len(detection.missing_evidence)
        completeness=100*supporting/max(1,supporting+missing);conflict_penalty=min(100,conflicts*15);missing_penalty=min(100,missing*20)
        overall=max(0.0,min(100.0,50+supporting*10-conflict_penalty-missing_penalty))
        identity=deterministic_id("signal_score",context.evaluation_id,overall,conflict_penalty,missing_penalty)
        return SignalScore(identity,overall,{"placeholder_evidence":overall},overall,overall,completeness,conflict_penalty,missing_penalty,ScoreHealth.HEALTHY,("PROMPT12_PLACEHOLDER", "SCORE_NOT_PROFIT_PROBABILITY"))


class UnavailableStrategyGate:
    def __init__(self,gate_type:GateType):self._gate_type=gate_type
    @property
    def gate_type(self):return self._gate_type
    def evaluate(self,candidate,context):
        return GateResult(deterministic_id("gate",self.gate_type.name,candidate.signal_candidate_id),self.gate_type,GateStatus.UNAVAILABLE,
            ("DOWNSTREAM_GATE_UNAVAILABLE",),("UNAVAILABLE_IS_NOT_APPROVAL",),"StrategyFramework",STRATEGY_FRAMEWORK_VERSION)


class StrategyRegistry:
    def __init__(self):self._strategies:dict[str,IStrategy]={}
    def register(self,strategy:IStrategy)->None:
        identity=strategy.metadata.identity
        if not identity.strategy_id or not identity.version:raise ValueError("INVALID_STRATEGY_IDENTITY")
        if identity.strategy_id in self._strategies:raise ValueError("DUPLICATE_STRATEGY_ID")
        self._strategies[identity.strategy_id]=strategy
    def get(self,strategy_id:str)->IStrategy:return self._strategies[strategy_id]
    def all(self)->tuple[IStrategy,...]:return tuple(self._strategies[key] for key in sorted(self._strategies))
    def __len__(self):return len(self._strategies)


VALID_TRANSITIONS={
    SignalLifecycleState.NOT_EVALUATED:{SignalLifecycleState.DETECTED,SignalLifecycleState.NOT_DETECTED,SignalLifecycleState.BLOCKED,SignalLifecycleState.UNKNOWN},
    SignalLifecycleState.DETECTED:{SignalLifecycleState.QUALIFIED,SignalLifecycleState.REJECTED,SignalLifecycleState.BLOCKED,SignalLifecycleState.DEFERRED},
    SignalLifecycleState.QUALIFIED:{SignalLifecycleState.SCORED,SignalLifecycleState.REJECTED,SignalLifecycleState.BLOCKED,SignalLifecycleState.EXPIRED,SignalLifecycleState.INVALIDATED},
    SignalLifecycleState.SCORED:{SignalLifecycleState.RESEARCH_SIGNAL,SignalLifecycleState.NO_ACTION,SignalLifecycleState.BLOCKED,SignalLifecycleState.DEFERRED},
    SignalLifecycleState.RESEARCH_SIGNAL:{SignalLifecycleState.EXPIRED,SignalLifecycleState.INVALIDATED},
    SignalLifecycleState.DETECTED:{SignalLifecycleState.QUALIFIED,SignalLifecycleState.REJECTED,SignalLifecycleState.BLOCKED,SignalLifecycleState.DEFERRED,SignalLifecycleState.EXPIRED,SignalLifecycleState.INVALIDATED},
}


def validate_transition(current:SignalLifecycleState,target:SignalLifecycleState)->None:
    if target not in VALID_TRANSITIONS.get(current,set()):raise ValueError(f"ILLEGAL_SIGNAL_TRANSITION:{current.name}->{target.name}")


class StrategyOrchestrator:
    def __init__(self,clock:IClock,audit:IAuditSink,registry:StrategyRegistry,configuration:StrategyFrameworkConfiguration,
                 scorer:ISignalScorer|None=None,gates:tuple[IStrategyGate,...]|None=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.clock=clock;self.audit=audit;self.registry=registry;self.configuration=configuration
        self.scorer=scorer or DeterministicPlaceholderScorer()
        self.gates=gates or tuple(UnavailableStrategyGate(item) for item in (GateType.RISK,GateType.PORTFOLIO,GateType.EXECUTION))
        self._cache:OrderedDict[tuple,StrategyEvaluation]=OrderedDict();self._history:list[StrategyEvaluation]=[];self._states:dict[tuple[str,str],StrategyState]={}

    def _capability(self,strategy:IStrategy,intelligence:MarketIntelligenceSnapshot)->CapabilityStatus:
        metadata=strategy.metadata
        roles=set(intelligence.features.features)
        if any(timeframe not in {intelligence.structure.context_structure.timeframe,intelligence.structure.strategy_structure.timeframe,intelligence.structure.execution_structure.timeframe} for timeframe in metadata.required_timeframes):return CapabilityStatus.UNSUPPORTED
        available_features={key.split(":",1)[0] for values in intelligence.features.features.values() for key in values}
        if any(feature.upper() not in available_features for feature in metadata.required_features):return CapabilityStatus.UNAVAILABLE
        if not roles:return CapabilityStatus.UNAVAILABLE
        return CapabilityStatus.SUPPORTED

    def _phase2_applicability(self,strategy:IStrategy,context:StrategyEvaluationContext)->StrategyApplicability|None:
        intel=context.market_intelligence;identity=strategy.metadata.identity;reasons=[]
        capability=self._capability(strategy,intel)
        if not self.configuration.enabled:return StrategyApplicability(deterministic_id("applicability",context.evaluation_id,"disabled"),identity.strategy_id,ApplicabilityState.NOT_APPLICABLE,capability,("STRATEGY_DISABLED",),())
        if intel.instrument_id not in self.configuration.allowed_instruments:return StrategyApplicability(deterministic_id("applicability",context.evaluation_id,"instrument"),identity.strategy_id,ApplicabilityState.NOT_APPLICABLE,capability,("INSTRUMENT_NOT_ALLOWED",),())
        if intel.as_of_timestamp_utc>self.clock.now():return StrategyApplicability(deterministic_id("applicability",context.evaluation_id,"future"),identity.strategy_id,ApplicabilityState.BLOCKED,capability,("FUTURE_INTELLIGENCE_BLOCKED",),("NO_LOOK_AHEAD",))
        if intel.intelligence_availability in (IntelligenceAvailability.NOT_AVAILABLE,IntelligenceAvailability.UNKNOWN) or intel.overall_intelligence_health in (IntelligenceHealth.UNTRUSTED,IntelligenceHealth.UNAVAILABLE,IntelligenceHealth.UNKNOWN):
            return StrategyApplicability(deterministic_id("applicability",context.evaluation_id,"phase2"),identity.strategy_id,ApplicabilityState.BLOCKED,capability,("PHASE2_INTELLIGENCE_BLOCKED",),intel.restrictions)
        if capability in (CapabilityStatus.UNSUPPORTED,CapabilityStatus.UNAVAILABLE,CapabilityStatus.UNKNOWN):
            return StrategyApplicability(deterministic_id("applicability",context.evaluation_id,"capability"),identity.strategy_id,ApplicabilityState.BLOCKED,capability,("MANDATORY_CAPABILITY_UNAVAILABLE",),())
        if intel.intelligence_availability is IntelligenceAvailability.AVAILABLE_WITH_RESTRICTIONS or intel.restrictions:
            return StrategyApplicability(deterministic_id("applicability",context.evaluation_id,"restricted"),identity.strategy_id,ApplicabilityState.CONDITIONAL,capability,("PHASE2_RESTRICTIONS_PRESERVED",),intel.restrictions)
        return None

    def evaluate(self,strategy:IStrategy,intelligence:MarketIntelligenceSnapshot,reason:EvaluationReason=EvaluationReason.NEW_BAR)->StrategyEvaluation:
        identity=strategy.metadata.identity;key=(identity.strategy_id,intelligence.instrument_id)
        state=self._states.get(key)
        evaluation_id=deterministic_id("strategy_eval",identity.strategy_id,identity.version,intelligence.market_intelligence_snapshot_id,intelligence.configuration_snapshot_id,reason.name)
        cache_key=(identity.strategy_id,identity.version,intelligence.instrument_id,intelligence.market_intelligence_snapshot_id,intelligence.configuration_snapshot_id,reason.name)
        if cache_key in self._cache:self._cache.move_to_end(cache_key);return self._cache[cache_key]
        context=StrategyEvaluationContext(evaluation_id,identity.strategy_id,intelligence.instrument_id,intelligence.as_of_timestamp_utc,intelligence,intelligence.configuration_snapshot_id,state,reason,intelligence.recovery_epoch)
        self.audit.record("strategy_evaluation_started",{"strategy_id":identity.strategy_id,"evaluation_id":evaluation_id})
        trace=DecisionTraceBuilder(self.clock,deterministic_id("strategy_decision",evaluation_id),deterministic_id("correlation",evaluation_id))
        try:
            applicability=self._phase2_applicability(strategy,context) or strategy.applicability(context)
            app_ok=applicability.state in (ApplicabilityState.APPLICABLE,ApplicabilityState.CONDITIONAL)
            trace.evaluate("applicability",DecisionStatus.PASSED if app_ok else DecisionStatus.FAILED,applicability.state.name,"strategy applicability and Phase II gate")
            if not app_ok:return self._finish(context,applicability,None,None,None,None,None,EvaluationOutcome.BLOCKED,FinalResearchAction.BLOCKED,StrategyHealth.RESTRICTED,StrategyReadiness.NOT_READY,applicability.reasons,trace)
            detection=strategy.detect(context);detected=detection.status is DetectionState.DETECTED
            trace.evaluate("detection",DecisionStatus.PASSED if detected else DecisionStatus.FAILED,detection.status.name,"raw setup evidence")
            if not detected:
                outcome=EvaluationOutcome.NO_ACTION if detection.status is DetectionState.NOT_DETECTED else EvaluationOutcome.BLOCKED
                return self._finish(context,applicability,detection,None,None,None,None,outcome,FinalResearchAction.NO_ACTION if outcome is EvaluationOutcome.NO_ACTION else FinalResearchAction.BLOCKED,StrategyHealth.HEALTHY if outcome is EvaluationOutcome.NO_ACTION else StrategyHealth.RESTRICTED,StrategyReadiness.READY,detection.status.name,trace)
            qualification=strategy.qualify(context,detection);qualified=qualification.status in (QualificationState.QUALIFIED,QualificationState.CONDITIONALLY_QUALIFIED)
            trace.evaluate("qualification",DecisionStatus.PASSED if qualified else DecisionStatus.FAILED,qualification.status.name,"hard and soft rules")
            if not qualified:return self._finish(context,applicability,detection,qualification,None,None,None,EvaluationOutcome.NO_ACTION,FinalResearchAction.NO_ACTION,StrategyHealth.HEALTHY,StrategyReadiness.READY,qualification.failed_rules+qualification.blocking_rules,trace)
            score=self.scorer.score(context,detection,qualification)
            if not 0<=score.overall_score<=100:raise ValueError("SCORE_OUT_OF_RANGE")
            score_valid=score.score_health in (ScoreHealth.VALID,ScoreHealth.HEALTHY,ScoreHealth.DEGRADED)
            trace.evaluate("scoring",DecisionStatus.PASSED if score_valid else DecisionStatus.FAILED,score.score_health.name,"Prompt 12 health-constrained scoring")
            if not score_valid:
                return self._finish(context,applicability,detection,qualification,score,None,None,EvaluationOutcome.BLOCKED,FinalResearchAction.NO_ACTION,StrategyHealth.RESTRICTED,StrategyReadiness.NOT_READY,("SCORING_NOT_VALID",score.score_health.name),trace)
            candidate=self._candidate(context,strategy,detection,qualification,score)
            gate_results=tuple(gate.evaluate(candidate,context) for gate in self.gates)
            unavailable=any(item.status in (GateStatus.UNAVAILABLE,GateStatus.UNKNOWN) for item in gate_results)
            blocked=any(item.status in (GateStatus.REJECTED,GateStatus.BLOCKED) for item in gate_results)
            trace.evaluate("downstream_gates",DecisionStatus.FAILED if blocked else DecisionStatus.PASSED,"GATE_BLOCKED" if blocked else "GATES_UNAVAILABLE_RESEARCH_ONLY" if unavailable else "GATES_EVALUATED","unavailable never means approved")
            if blocked:return self._finish(context,applicability,detection,qualification,score,replace(candidate,candidate_status=CandidateStatus.BLOCKED),None,EvaluationOutcome.BLOCKED,FinalResearchAction.BLOCKED,StrategyHealth.RESTRICTED,StrategyReadiness.READY_WITH_RESTRICTIONS,("DOWNSTREAM_GATE_BLOCKED",),trace)
            signal=self._signal(context,candidate,score,gate_results)
            reasons=("DOWNSTREAM_GATES_UNAVAILABLE",) if unavailable else ("RESEARCH_SIGNAL_CREATED",)
            return self._finish(context,applicability,detection,qualification,score,candidate,signal,EvaluationOutcome.COMPLETED,FinalResearchAction.RESEARCH_SIGNAL,StrategyHealth.HEALTHY,StrategyReadiness.READY_WITH_RESTRICTIONS if unavailable else StrategyReadiness.READY,reasons,trace)
        except Exception as exc:
            self.audit.record("strategy_evaluation_failed",{"strategy_id":identity.strategy_id,"evaluation_id":evaluation_id,"error":type(exc).__name__})
            applicability=StrategyApplicability(deterministic_id("applicability",evaluation_id,"error"),identity.strategy_id,ApplicabilityState.UNKNOWN,CapabilityStatus.UNKNOWN,("STRATEGY_ERROR",),())
            return self._finish(context,applicability,None,None,None,None,None,EvaluationOutcome.ERROR,FinalResearchAction.NO_ACTION,StrategyHealth.INVALID,StrategyReadiness.NOT_READY,("STRATEGY_ERROR",type(exc).__name__),trace,failed=True)

    def evaluate_all(self,intelligence:MarketIntelligenceSnapshot,reason:EvaluationReason=EvaluationReason.NEW_BAR)->tuple[StrategyEvaluation,...]:
        return tuple(self.evaluate(strategy,intelligence,reason) for strategy in self.registry.all())

    def _candidate(self,context,strategy,detection,qualification,score):
        identity=strategy.metadata.identity;direction=strategy.direction(context,detection)
        logical=deterministic_id("logical_signal",identity.strategy_id,context.instrument_id,context.market_intelligence.market_intelligence_snapshot_id,direction.name)
        version=deterministic_id("signal_version",logical,identity.version,context.evaluation_id)
        status=CandidateStatus.QUALIFIED if qualification.status is QualificationState.QUALIFIED else CandidateStatus.CONDITIONALLY_QUALIFIED
        supporting=tuple(item for item in detection.evidence if item.category is EvidenceCategory.SUPPORTING)
        disqualifying=tuple(item for item in detection.evidence if item.category is EvidenceCategory.DISQUALIFYING)
        return SignalCandidate(deterministic_id("candidate",version),logical,version,identity.strategy_id,identity.family,identity.version,context.instrument_id,
            context.as_of_timestamp_utc,direction,detection.detection_id,qualification.qualification_id,score.signal_score_id,supporting,detection.conflicting_evidence,detection.missing_evidence,disqualifying,
            context.market_intelligence.market_intelligence_snapshot_id,status,context.as_of_timestamp_utc+timedelta(minutes=self.configuration.candidate_ttl_minutes),(status.name,),context.strategy_configuration_snapshot_id,context.recovery_epoch)

    def _signal(self,context,candidate,score,gates):
        by_type={item.gate_type:item for item in gates};restrictions=tuple(dict.fromkeys(value for item in gates for value in item.restrictions))
        version=deterministic_id("research_signal_version",candidate.signal_version_id,"|".join(item.status.name for item in gates))
        return ResearchSignal(deterministic_id("research_signal",version),candidate.logical_signal_id,version,candidate.signal_candidate_id,candidate.strategy_id,candidate.strategy_family,candidate.instrument_id,
            candidate.as_of_timestamp_utc,candidate.direction,score.overall_score,score.confidence,score.quality,StrategyDecision.QUALIFIED_CANDIDATE,
            by_type.get(GateType.RISK,UnavailableStrategyGate(GateType.RISK).evaluate(candidate,context)).status,
            by_type.get(GateType.PORTFOLIO,UnavailableStrategyGate(GateType.PORTFOLIO).evaluate(candidate,context)).status,
            by_type.get(GateType.EXECUTION,UnavailableStrategyGate(GateType.EXECUTION).evaluate(candidate,context)).status,
            FinalResearchAction.RESEARCH_SIGNAL,restrictions,("RESEARCH_ONLY_NOT_EXECUTABLE",),candidate.market_intelligence_snapshot_id,candidate.configuration_snapshot_id,candidate.recovery_epoch)

    def _finish(self,context,applicability,detection,qualification,score,candidate,signal,outcome,action,health,readiness,reasons,trace,failed=False):
        if trace.short_circuited_at is None:
            trace.evaluate("final_action",DecisionStatus.PASSED if action in (FinalResearchAction.RESEARCH_SIGNAL,FinalResearchAction.RESEARCH_CANDIDATE,FinalResearchAction.NO_ACTION) and not failed else DecisionStatus.FAILED,action.name,"research output only")
        decision_trace=trace.complete(DecisionOutcome.NO_ACTION,"strategy framework cannot execute")
        result=StrategyEvaluation(context.evaluation_id,context.strategy_id,context.instrument_id,applicability,detection,qualification,score,candidate,signal,outcome,action,health,readiness,tuple(reasons) if not isinstance(reasons,str) else (reasons,),decision_trace)
        cache_key=(self.registry.get(context.strategy_id).metadata.identity.strategy_id,self.registry.get(context.strategy_id).metadata.identity.version,context.instrument_id,context.market_intelligence.market_intelligence_snapshot_id,context.strategy_configuration_snapshot_id,context.evaluation_reason.name)
        self._cache[cache_key]=result;self._cache.move_to_end(cache_key)
        while len(self._cache)>self.configuration.maximum_cache_entries:self._cache.popitem(last=False)
        self._history.append(result);self._history=self._history[-self.configuration.maximum_history:]
        refs=(context.previous_strategy_state.recent_signal_references if context.previous_strategy_state else ())
        if signal:refs=(*refs,signal.research_signal_id)[-self.configuration.maximum_history:]
        self._states[(context.strategy_id,context.instrument_id)]=StrategyState(context.strategy_id,context.instrument_id,context.evaluation_id,context.market_intelligence.market_intelligence_snapshot_id,signal.logical_signal_id if signal else None,0,refs)
        self.audit.record("strategy_evaluation_completed",{"strategy_id":context.strategy_id,"evaluation_id":context.evaluation_id,"action":action.name,"outcome":outcome.name})
        return result

    def transition_candidate(self,candidate:SignalCandidate,target:CandidateStatus,as_of:datetime,reason:str)->SignalCandidate:
        source={CandidateStatus.DETECTED:SignalLifecycleState.DETECTED,CandidateStatus.QUALIFIED:SignalLifecycleState.QUALIFIED,CandidateStatus.CONDITIONALLY_QUALIFIED:SignalLifecycleState.QUALIFIED,CandidateStatus.EXPIRED:SignalLifecycleState.EXPIRED,CandidateStatus.INVALIDATED:SignalLifecycleState.INVALIDATED}.get(candidate.candidate_status,SignalLifecycleState.BLOCKED)
        destination={CandidateStatus.EXPIRED:SignalLifecycleState.EXPIRED,CandidateStatus.INVALIDATED:SignalLifecycleState.INVALIDATED}.get(target,SignalLifecycleState.UNKNOWN)
        validate_transition(source,destination)
        if target is CandidateStatus.EXPIRED and as_of<candidate.expires_at_utc:raise ValueError("CANDIDATE_NOT_EXPIRED")
        version=deterministic_id("signal_version",candidate.signal_version_id,target.name,as_of.isoformat(),reason)
        return replace(candidate,signal_candidate_id=deterministic_id("candidate",version),signal_version_id=version,candidate_status=target,reason_codes=(*candidate.reason_codes,reason))

    @property
    def history(self):return tuple(self._history)
    @property
    def cache_size(self):return len(self._cache)
    def state(self,strategy_id:str,instrument_id:str):return self._states.get((strategy_id,instrument_id))
    def recovery_state(self):
        return {"strategy_framework_version":STRATEGY_FRAMEWORK_VERSION,"states":tuple((key[0],key[1],value.last_evaluation_id,value.last_market_intelligence_snapshot_id,value.last_logical_signal_id) for key,value in sorted(self._states.items()))}
    def validate_recovery(self,state:Mapping[str,object])->bool:return state.get("strategy_framework_version")==STRATEGY_FRAMEWORK_VERSION
