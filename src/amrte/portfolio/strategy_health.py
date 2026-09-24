"""Offline strategy-health monitoring and fictional allocation restriction.

Consumes authoritative normalized research outcomes and Prompt 23 decisions.
It cannot increase exposure and contains no broker, account, or execution APIs.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime,timedelta
from decimal import Decimal,ROUND_FLOOR,localcontext
from enum import Enum,auto
from math import sqrt
from statistics import median

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation,DecisionOutcome,DecisionStatus,DecisionTrace
from amrte.risk.exit_management import ExitHealth,ResearchExitCompletion,ResearchExitPlan
from amrte.risk.sizing import _decimal
from .correlation import CorrelationDecisionOutcome,CorrelationRiskDecision

STRATEGY_HEALTH_ENGINE_VERSION="1.0";RECOVERY_SCHEMA_VERSION="1.0";ZERO=Decimal("0");ONE=Decimal("1")

class StrategyHealthState(Enum):HEALTHY=auto();CAUTION=auto();DEFENSIVE=auto();SUSPENDED=auto();INSUFFICIENT_HISTORY=auto();STALE=auto();INVALID=auto();UNKNOWN=auto()
class HealthComponent(Enum):EXPECTANCY=auto();DRAWDOWN=auto();LOSS_CLUSTER=auto();STABILITY=auto();REGIME=auto();SAMPLE=auto();DATA=auto();BEHAVIOR_DEVIATION=auto()
class HealthSeverity(Enum):NONE=auto();LOW=auto();MEDIUM=auto();HIGH=auto();CRITICAL=auto();UNKNOWN=auto()
class HealthAggregationPolicy(Enum):MOST_RESTRICTIVE=auto();WEIGHTED_WITH_HARD_FLOORS=auto()
class AllocationOutcome(Enum):ALLOW_UNCHANGED=auto();ALLOW_REDUCED=auto();BLOCK=auto();NO_ACTION=auto();INVALID=auto();UNKNOWN=auto()
class OutcomeHealth(Enum):HEALTHY=auto();DEGRADED=auto();INVALID=auto();UNKNOWN=auto()

@dataclass(frozen=True)
class HealthWindow:
    window_id:str;completed_observations:int;minimum_observations:int;required:bool=True;weight:Decimal=ONE

@dataclass(frozen=True)
class StrategyExpectedBehaviorProfile:
    profile_id:str;profile_version:str;strategy_id:str;strategy_version:str;strategy_family:str;strategy_variant:str|None
    applicable_regimes:tuple[str,...];expected_mean_r_min:Decimal;expected_mean_r_max:Decimal
    expected_win_rate_min:Decimal;expected_win_rate_max:Decimal;maximum_expected_drawdown:Decimal
    caution_expectancy:Decimal;defensive_expectancy:Decimal;suspend_expectancy:Decimal
    caution_drawdown:Decimal;defensive_drawdown:Decimal;suspend_drawdown:Decimal
    minimum_observations:int;minimum_regime_observations:int;provenance:str;valid_from_utc:datetime;known_at_utc:datetime
    configuration_snapshot_id:str

@dataclass(frozen=True)
class StrategyOutcomeObservation:
    observation_id:str;completion_id:str;strategy_id:str;strategy_version:str;strategy_family:str;strategy_variant:str|None
    research_hypothesis_id:str;research_signal_id:str;strategy_decision_id:str;instrument_id:str
    regime_at_admission:str|None;regime_at_termination:str|None;initial_normalized_risk:Decimal;realized_normalized_r:Decimal
    exit_reason:str;exit_policy:str;opened_at_utc:datetime;closed_at_utc:datetime;outcome_known_at_utc:datetime
    dataset_fingerprint:str;configuration_snapshot_id:str;recovery_epoch:int;health:OutcomeHealth

    @classmethod
    def from_completion(cls,completion:ResearchExitCompletion,plan:ResearchExitPlan,*,strategy_version, strategy_family,instrument_id,dataset_fingerprint,realized_normalized_r=None,regime_at_admission=None,regime_at_termination=None):
        value=completion.normalized_research_outcome if realized_normalized_r is None else realized_normalized_r
        if value is None:raise ValueError("STRATEGY_OUTCOME_NORMALIZED_R_UNAVAILABLE")
        value=_decimal(value)
        if not value.is_finite():raise ValueError("STRATEGY_OUTCOME_INVALID")
        oid=deterministic_id("strategy_outcome_observation",completion.completion_id,plan.strategy_id,strategy_version,plan.strategy_variant or "NONE",str(value),completion.completed_at_utc.isoformat(),dataset_fingerprint)
        return cls(oid,completion.completion_id,plan.strategy_id,strategy_version,strategy_family,plan.strategy_variant,plan.logical_plan_id,plan.research_signal_id,plan.strategy_decision_snapshot_id,instrument_id,regime_at_admission,regime_at_termination,ONE,value,completion.terminal_reason.name,plan.exit_policy_id,plan.created_at_utc,completion.completed_at_utc,completion.completed_at_utc,dataset_fingerprint,plan.configuration_snapshot_id,plan.recovery_epoch,OutcomeHealth.HEALTHY if completion.health is ExitHealth.HEALTHY else OutcomeHealth.DEGRADED)

@dataclass(frozen=True)
class StrategyPerformanceMetrics:
    observation_count:int;cumulative_r:Decimal;mean_r:Decimal;median_r:Decimal;win_rate:Decimal;loss_rate:Decimal;neutral_rate:Decimal
    average_positive_r:Decimal|None;average_negative_r:Decimal|None;expectancy_r:Decimal;rolling_peak:Decimal;maximum_drawdown:Decimal
    consecutive_negative_outcomes:int;outcome_dispersion:Decimal;downside_deviation:Decimal;average_holding_seconds:Decimal

@dataclass(frozen=True)
class StrategyHealthEvidence:
    evidence_id:str;strategy_id:str;strategy_variant:str|None;metric:HealthComponent;window_id:str;observed_value:Decimal|None
    expected_range:tuple[Decimal,Decimal]|None;deviation:Decimal|None;observation_count:int;health:StrategyHealthState;severity:HealthSeverity
    as_of_timestamp_utc:datetime;source_observation_ids:tuple[str,...];expected_behavior_profile_id:str;dataset_fingerprint:str;configuration_snapshot_id:str

@dataclass(frozen=True)
class StrategyHealthTransition:
    transition_id:str;strategy_key:str;previous_state:StrategyHealthState;raw_state:StrategyHealthState;published_state:StrategyHealthState
    deterioration_count:int;recovery_count:int;last_observation_set_id:str;cooldown_until_utc:datetime|None;transitioned_at_utc:datetime;reason_code:str

@dataclass(frozen=True)
class StrategyHealthSnapshot:
    snapshot_id:str;strategy_id:str;strategy_version:str;strategy_family:str;strategy_variant:str|None
    published_health_state:StrategyHealthState;raw_health_state:StrategyHealthState;health_score:Decimal
    evidence:tuple[StrategyHealthEvidence,...];window_results:tuple[tuple[str,StrategyPerformanceMetrics|None],...]
    regime_results:tuple[tuple[str,StrategyPerformanceMetrics],...];current_allocation_multiplier:Decimal;previous_health_state:StrategyHealthState
    transition:StrategyHealthTransition;expected_behavior_profile_id:str;outcome_observation_ids:tuple[str,...]
    as_of_timestamp_utc:datetime;dataset_fingerprint:str;configuration_snapshot_id:str;engine_version:str;recovery_epoch:int

@dataclass(frozen=True)
class StrategyHealthConfiguration:
    windows:tuple[HealthWindow,...]=(HealthWindow("SHORT",10,5),HealthWindow("LONG",30,10))
    aggregation_policy:HealthAggregationPolicy=HealthAggregationPolicy.MOST_RESTRICTIVE
    healthy_multiplier:Decimal=ONE;caution_multiplier:Decimal=Decimal("0.75");defensive_multiplier:Decimal=Decimal("0.35");suspended_multiplier:Decimal=ZERO;probation_multiplier:Decimal=Decimal("0.25")
    deterioration_confirmation_count:int=1;recovery_confirmation_count:int=3;recovery_cooldown_seconds:int=3600;stale_after_seconds:int=2592000
    exposure_step:Decimal=Decimal("0.01");maximum_outcomes:int=2048;maximum_snapshots:int=512;maximum_transitions:int=1024;maximum_decisions:int=1024;configuration_snapshot_id:str="STRATEGY_HEALTH_DEFAULT_RESEARCH"
    def validate(self):
        errors=[]
        try:
            multipliers=tuple(_decimal(x) for x in (self.suspended_multiplier,self.defensive_multiplier,self.caution_multiplier,self.healthy_multiplier,self.probation_multiplier,self.exposure_step))
            if any(not x.is_finite() for x in multipliers) or not (ZERO==multipliers[0]<=multipliers[1]<=multipliers[2]<=multipliers[3]<=ONE) or not ZERO<=multipliers[4]<=ONE or multipliers[5]<=0:errors.append("STRATEGY_HEALTH_MULTIPLIER_INVALID")
            if any(x.completed_observations<1 or x.minimum_observations<1 or x.minimum_observations>x.completed_observations or not _decimal(x.weight).is_finite() or x.weight<0 for x in self.windows):errors.append("STRATEGY_HEALTH_WINDOW_INVALID")
        except (ValueError,ArithmeticError):errors.append("STRATEGY_HEALTH_NUMERICAL_INVALID")
        if not self.windows or len({x.window_id for x in self.windows})!=len(self.windows):errors.append("STRATEGY_HEALTH_WINDOWS_INVALID")
        if self.deterioration_confirmation_count<1 or self.recovery_confirmation_count<1 or self.recovery_confirmation_count<self.deterioration_confirmation_count or self.recovery_cooldown_seconds<0 or self.stale_after_seconds<0:errors.append("STRATEGY_HEALTH_TRANSITION_INVALID")
        if min(self.maximum_outcomes,self.maximum_snapshots,self.maximum_transitions,self.maximum_decisions)<1:errors.append("STRATEGY_HEALTH_BOUND_INVALID")
        return tuple(dict.fromkeys(errors))

@dataclass(frozen=True)
class StrategyAllocationDecision:
    decision_id:str;strategy_id:str;strategy_family:str;strategy_variant:str|None;prompt23_decision_id:str;prompt23_approved_exposure:Decimal
    strategy_health_snapshot_id:str;health_state:StrategyHealthState;health_score:Decimal;allocation_multiplier:Decimal
    pre_quantized_exposure:Decimal;final_approved_exposure:Decimal;outcome:AllocationOutcome;binding_reason_codes:tuple[str,...]
    as_of_timestamp_utc:datetime;configuration_snapshot_id:str;engine_version:str;recovery_epoch:int;decision_trace:DecisionTrace

@dataclass(frozen=True)
class PortfolioIntelligenceSnapshot:
    snapshot_id:str;prompt22_portfolio_snapshot_id:str;prompt23_correlation_snapshot_id:str;strategy_health_snapshot_ids:tuple[str,...]
    strategy_allocation_decision_ids:tuple[str,...];final_research_admission:tuple[tuple[str,Decimal],...];portfolio_health:str
    restrictions:tuple[str,...];as_of_timestamp_utc:datetime;dataset_fingerprint:str;configuration_snapshot_id:str;engine_version:str;recovery_epoch:int

class StrategyHealthLedger:
    def __init__(self,maximum_outcomes=2048,maximum_transitions=1024):self.maximum_outcomes=maximum_outcomes;self.maximum_transitions=maximum_transitions;self.outcomes=OrderedDict();self.transitions=OrderedDict()
    def add_outcome(self,item):self.outcomes.setdefault(item.observation_id,item);self._bound()
    def add_transition(self,item):self.transitions.setdefault(item.transition_id,item);self._bound()
    def _bound(self):
        while len(self.outcomes)>self.maximum_outcomes:self.outcomes.popitem(last=False)
        while len(self.transitions)>self.maximum_transitions:self.transitions.popitem(last=False)

class StrategyHealthEngine:
    def __init__(self,configuration=StrategyHealthConfiguration(),audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit;self.ledger=StrategyHealthLedger(configuration.maximum_outcomes,configuration.maximum_transitions);self.snapshots=OrderedDict();self.decisions=OrderedDict();self._published={};self._cache=OrderedDict();self.recovery_restricted=False
    def ingest(self,outcomes):
        for item in sorted(outcomes,key=lambda x:(x.outcome_known_at_utc,x.observation_id)):
            if item.health is OutcomeHealth.INVALID or not item.realized_normalized_r.is_finite() or item.closed_at_utc>item.outcome_known_at_utc:raise ValueError("STRATEGY_OUTCOME_INVALID")
            self.ledger.add_outcome(item)
    def evaluate(self,profile:StrategyExpectedBehaviorProfile,as_of,recovery_epoch=0):
        if profile.known_at_utc>as_of or profile.valid_from_utc>as_of:raise ValueError("STRATEGY_PROFILE_FUTURE")
        observations=tuple(x for x in self.ledger.outcomes.values() if x.strategy_id==profile.strategy_id and x.strategy_version==profile.strategy_version and x.strategy_variant==profile.strategy_variant and x.outcome_known_at_utc<=as_of and x.configuration_snapshot_id==profile.configuration_snapshot_id)
        observations=tuple(sorted(observations,key=lambda x:(x.outcome_known_at_utc,x.observation_id)));windows=[];evidence=[];raw_states=[]
        for window in self.configuration.windows:
            selected=observations[-window.completed_observations:]
            if len(selected)<max(window.minimum_observations,profile.minimum_observations):metrics=None;state=StrategyHealthState.INSUFFICIENT_HISTORY
            else:metrics=self._metrics(selected);state=self._classify(metrics,profile)
            windows.append((window.window_id,metrics));raw_states.append(state);evidence.extend(self._evidence(profile,window,selected,metrics,state,as_of))
        raw=max(raw_states,key=self._rank) if raw_states else StrategyHealthState.UNKNOWN
        if observations and as_of-observations[-1].outcome_known_at_utc>timedelta(seconds=self.configuration.stale_after_seconds):raw=StrategyHealthState.STALE
        observation_set_id=deterministic_id("strategy_health_observation_set",*(x.observation_id for x in observations),profile.profile_id,as_of.isoformat());key=f"{profile.strategy_id}:{profile.strategy_version}:{profile.strategy_variant or 'NONE'}";transition=self._transition(key,raw,observation_set_id,as_of,recovery_epoch);published=transition.published_state
        score=self._score(windows,raw);multiplier=self._multiplier(published);regimes=[]
        for regime in sorted({x.regime_at_admission for x in observations if x.regime_at_admission}):
            items=tuple(x for x in observations if x.regime_at_admission==regime)
            if len(items)>=profile.minimum_regime_observations:regimes.append((regime,self._metrics(items)))
        fingerprint=observations[-1].dataset_fingerprint if observations else "UNKNOWN";sid=deterministic_id("strategy_health_snapshot",key,profile.profile_id,transition.transition_id,str(score),str(multiplier),*(x.observation_id for x in observations),as_of.isoformat(),self.configuration.configuration_snapshot_id,STRATEGY_HEALTH_ENGINE_VERSION,recovery_epoch)
        result=StrategyHealthSnapshot(sid,profile.strategy_id,profile.strategy_version,profile.strategy_family,profile.strategy_variant,published,raw,score,tuple(evidence),tuple(windows),tuple(regimes),multiplier,transition.previous_state,transition,profile.profile_id,tuple(x.observation_id for x in observations),as_of,fingerprint,self.configuration.configuration_snapshot_id,STRATEGY_HEALTH_ENGINE_VERSION,recovery_epoch);self.snapshots[sid]=result;self._bound();self._record("strategy_health_snapshot_created",{"snapshot_id":sid,"state":published.name});return result
    def allocate(self,prompt23:CorrelationRiskDecision,health:StrategyHealthSnapshot,family_health=None):
        as_of=prompt23.as_of_timestamp_utc;upstream=prompt23.approved_exposure;multiplier=min(health.current_allocation_multiplier,family_health.current_allocation_multiplier if family_health else ONE);reasons=[]
        if prompt23.outcome is CorrelationDecisionOutcome.NO_ACTION or upstream<=0:final=ZERO;outcome=AllocationOutcome.NO_ACTION;reasons.append("STRATEGY_ALLOCATION_NO_ACTION")
        elif self.recovery_restricted or health.published_health_state in (StrategyHealthState.INVALID,StrategyHealthState.UNKNOWN,StrategyHealthState.STALE):final=ZERO;outcome=AllocationOutcome.BLOCK;reasons.append("STRATEGY_HEALTH_UNAVAILABLE")
        else:
            pre=upstream*multiplier;final=self._floor(pre)
            if final<=0:outcome=AllocationOutcome.BLOCK;reasons.append("STRATEGY_HEALTH_SUSPENDED")
            elif final<upstream:outcome=AllocationOutcome.ALLOW_REDUCED;reasons.append("STRATEGY_ALLOCATION_REDUCED")
            else:outcome=AllocationOutcome.ALLOW_UNCHANGED;reasons.append("STRATEGY_ALLOCATION_UNCHANGED")
        pre=upstream*multiplier;final=min(upstream,final);did=deterministic_id("strategy_allocation_decision",prompt23.decision_id,health.snapshot_id,family_health.snapshot_id if family_health else "NONE",str(multiplier),str(final),outcome.name,self.configuration.configuration_snapshot_id)
        status=DecisionStatus.PASSED if outcome in (AllocationOutcome.ALLOW_UNCHANGED,AllocationOutcome.NO_ACTION) else DecisionStatus.FAILED;checks=(DecisionEvaluation("PROMPT23_PRECEDENCE",status,"STRATEGY_ALLOCATION_MONOTONIC","Prompt 24 cannot restore or amplify upstream exposure",(prompt23.decision_id,)),DecisionEvaluation("STRATEGY_HEALTH",status,reasons[-1],"Published strategy health and multiplier applied",(health.snapshot_id,)))
        trace=DecisionTrace(did,prompt23.request_id,as_of,checks,DecisionOutcome.ACCEPTED if outcome is AllocationOutcome.ALLOW_UNCHANGED else DecisionOutcome.NO_ACTION,reasons[-1],as_of,"STRATEGY_HEALTH" if status is DecisionStatus.FAILED else None);result=StrategyAllocationDecision(did,health.strategy_id,health.strategy_family,health.strategy_variant,prompt23.decision_id,upstream,health.snapshot_id,health.published_health_state,health.health_score,multiplier,pre,final,outcome,tuple(reasons),as_of,self.configuration.configuration_snapshot_id,STRATEGY_HEALTH_ENGINE_VERSION,prompt23.recovery_epoch,trace);self.decisions[did]=result;self._bound();self._record("strategy_allocation_decided",{"decision_id":did,"outcome":outcome.name});return result
    def phase_v_snapshot(self,prompt22_snapshot_id,prompt23_snapshot_id,health_snapshots,decisions,as_of,dataset_fingerprint,recovery_epoch=0):
        admissions=tuple(sorted((x.strategy_id,x.final_approved_exposure) for x in decisions));restrictions=tuple(sorted({r for x in decisions for r in x.binding_reason_codes if x.outcome is not AllocationOutcome.ALLOW_UNCHANGED}));portfolio_health="HEALTHY" if not restrictions else "RESTRICTED";sid=deterministic_id("portfolio_intelligence_snapshot",prompt22_snapshot_id,prompt23_snapshot_id,*(x.snapshot_id for x in health_snapshots),*(x.decision_id for x in decisions),as_of.isoformat(),dataset_fingerprint,self.configuration.configuration_snapshot_id,recovery_epoch)
        return PortfolioIntelligenceSnapshot(sid,prompt22_snapshot_id,prompt23_snapshot_id,tuple(x.snapshot_id for x in health_snapshots),tuple(x.decision_id for x in decisions),admissions,portfolio_health,restrictions,as_of,dataset_fingerprint,self.configuration.configuration_snapshot_id,STRATEGY_HEALTH_ENGINE_VERSION,recovery_epoch)
    def _metrics(self,items):
        values=[x.realized_normalized_r for x in items];count=len(values);cumulative=sum(values,ZERO);mean=cumulative/Decimal(count);wins=[x for x in values if x>0];losses=[x for x in values if x<0];neutral=[x for x in values if x==0];equity=ZERO;peak=ZERO;maxdd=ZERO;streak=0;maxstreak=0
        for value in values:equity+=value;peak=max(peak,equity);maxdd=max(maxdd,peak-equity);streak=streak+1 if value<0 else 0;maxstreak=max(maxstreak,streak)
        variance=sum(((x-mean)*(x-mean) for x in values),ZERO)/Decimal(count);down=[min(ZERO,x) for x in values];downside=sum((x*x for x in down),ZERO)/Decimal(count);dur=sum((Decimal(str((x.closed_at_utc-x.opened_at_utc).total_seconds())) for x in items),ZERO)/Decimal(count)
        return StrategyPerformanceMetrics(count,cumulative,mean,Decimal(str(median(values))),Decimal(len(wins))/count,Decimal(len(losses))/count,Decimal(len(neutral))/count,sum(wins,ZERO)/len(wins) if wins else None,sum(losses,ZERO)/len(losses) if losses else None,mean,peak,maxdd,maxstreak,Decimal(str(sqrt(float(variance)))),Decimal(str(sqrt(float(downside)))),dur)
    def _classify(self,m,p):
        if m.expectancy_r<=p.suspend_expectancy or m.maximum_drawdown>=p.suspend_drawdown:return StrategyHealthState.SUSPENDED
        if m.expectancy_r<=p.defensive_expectancy or m.maximum_drawdown>=p.defensive_drawdown:return StrategyHealthState.DEFENSIVE
        if m.expectancy_r<=p.caution_expectancy or m.maximum_drawdown>=p.caution_drawdown:return StrategyHealthState.CAUTION
        return StrategyHealthState.HEALTHY
    def _evidence(self,p,w,items,m,state,as_of):
        values=((HealthComponent.SAMPLE,Decimal(len(items)),(Decimal(w.minimum_observations),Decimal(w.completed_observations))),) if m is None else ((HealthComponent.EXPECTANCY,m.expectancy_r,(p.expected_mean_r_min,p.expected_mean_r_max)),(HealthComponent.DRAWDOWN,m.maximum_drawdown,(ZERO,p.maximum_expected_drawdown)),(HealthComponent.LOSS_CLUSTER,Decimal(m.consecutive_negative_outcomes),None),(HealthComponent.STABILITY,m.outcome_dispersion,None))
        out=[]
        for metric,value,expected in values:
            deviation=None if expected is None else value-min(max(value,expected[0]),expected[1]);severity=HealthSeverity.NONE if state is StrategyHealthState.HEALTHY else HealthSeverity.LOW if state is StrategyHealthState.CAUTION else HealthSeverity.HIGH if state is StrategyHealthState.DEFENSIVE else HealthSeverity.CRITICAL
            eid=deterministic_id("strategy_health_evidence",p.profile_id,w.window_id,metric.name,str(value),*(x.observation_id for x in items),as_of.isoformat());out.append(StrategyHealthEvidence(eid,p.strategy_id,p.strategy_variant,metric,w.window_id,value,expected,deviation,len(items),state,severity,as_of,tuple(x.observation_id for x in items),p.profile_id,items[-1].dataset_fingerprint if items else "UNKNOWN",self.configuration.configuration_snapshot_id))
        return tuple(out)
    def _transition(self,key,raw,observation_set_id,as_of,recovery_epoch):
        previous=self._published.get(key);prev=previous.published_state if previous else StrategyHealthState.INSUFFICIENT_HISTORY;det=previous.deterioration_count if previous else 0;rec=previous.recovery_count if previous else 0;cool=previous.cooldown_until_utc if previous else None;published=raw if previous is None else prev;reason="STRATEGY_HEALTH_INITIALIZED" if previous is None else "STRATEGY_HEALTH_UNCHANGED"
        if previous and previous.last_observation_set_id==observation_set_id:return previous
        if previous is None:
            tid=deterministic_id("strategy_health_transition",key,prev.name,raw.name,published.name,0,0,observation_set_id,as_of.isoformat(),recovery_epoch);item=StrategyHealthTransition(tid,key,prev,raw,published,0,0,observation_set_id,cool,as_of,reason);self._published[key]=item;self.ledger.add_transition(item);return item
        if self._rank(raw)>self._rank(prev):det+=1;rec=0
        elif self._rank(raw)<self._rank(prev):rec+=1;det=0
        else:det=rec=0
        if raw in (StrategyHealthState.INVALID,StrategyHealthState.UNKNOWN,StrategyHealthState.STALE,StrategyHealthState.SUSPENDED):published=raw;reason="STRATEGY_HEALTH_HARD_RESTRICTION"
        elif self._rank(raw)>self._rank(prev) and det>=self.configuration.deterioration_confirmation_count:published=raw;cool=as_of+timedelta(seconds=self.configuration.recovery_cooldown_seconds);reason="STRATEGY_HEALTH_DETERIORATED"
        elif self._rank(raw)<self._rank(prev) and rec>=self.configuration.recovery_confirmation_count and (cool is None or as_of>=cool):published=raw;reason="STRATEGY_HEALTH_RECOVERED"
        tid=deterministic_id("strategy_health_transition",key,prev.name,raw.name,published.name,det,rec,observation_set_id,as_of.isoformat(),recovery_epoch);item=StrategyHealthTransition(tid,key,prev,raw,published,det,rec,observation_set_id,cool,as_of,reason);self._published[key]=item;self.ledger.add_transition(item);return item
    def _rank(self,state):return {StrategyHealthState.HEALTHY:0,StrategyHealthState.INSUFFICIENT_HISTORY:1,StrategyHealthState.CAUTION:2,StrategyHealthState.DEFENSIVE:3,StrategyHealthState.STALE:4,StrategyHealthState.UNKNOWN:5,StrategyHealthState.INVALID:6,StrategyHealthState.SUSPENDED:7}[state]
    def _multiplier(self,state):return {StrategyHealthState.HEALTHY:self.configuration.healthy_multiplier,StrategyHealthState.CAUTION:self.configuration.caution_multiplier,StrategyHealthState.DEFENSIVE:self.configuration.defensive_multiplier,StrategyHealthState.SUSPENDED:ZERO,StrategyHealthState.INSUFFICIENT_HISTORY:self.configuration.probation_multiplier,StrategyHealthState.STALE:ZERO,StrategyHealthState.INVALID:ZERO,StrategyHealthState.UNKNOWN:ZERO}[state]
    def _score(self,windows,raw):
        valid=[m.mean_r for _,m in windows if m];base=Decimal("0.5") if not valid else max(ZERO,min(ONE,Decimal("0.5")+sum(valid,ZERO)/Decimal(len(valid))*Decimal("0.1")));return ZERO if raw in (StrategyHealthState.INVALID,StrategyHealthState.UNKNOWN) else base
    def _floor(self,value):
        with localcontext() as ctx:ctx.prec=28;return (_decimal(value)/self.configuration.exposure_step).to_integral_value(rounding=ROUND_FLOOR)*self.configuration.exposure_step
    def recovery_state(self):return {"schema_version":RECOVERY_SCHEMA_VERSION,"engine_version":STRATEGY_HEALTH_ENGINE_VERSION,"configuration_snapshot_id":self.configuration.configuration_snapshot_id,"outcomes":tuple(self.ledger.outcomes.values()),"transitions":tuple(self.ledger.transitions.values()),"published":tuple(self._published.items())}
    def restore(self,state):
        if state.get("schema_version")!=RECOVERY_SCHEMA_VERSION or state.get("engine_version")!=STRATEGY_HEALTH_ENGINE_VERSION or state.get("configuration_snapshot_id")!=self.configuration.configuration_snapshot_id:self.recovery_restricted=True;return False
        try:self.ledger.outcomes=OrderedDict((x.observation_id,x) for x in state.get("outcomes",()));self.ledger.transitions=OrderedDict((x.transition_id,x) for x in state.get("transitions",()));self._published=dict(state.get("published",()));self.recovery_restricted=False;return True
        except Exception:self.recovery_restricted=True;return False
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
    def _bound(self):
        for store,limit in ((self.snapshots,self.configuration.maximum_snapshots),(self.decisions,self.configuration.maximum_decisions),(self._cache,self.configuration.maximum_snapshots)):
            while len(store)>limit:store.popitem(last=False)
