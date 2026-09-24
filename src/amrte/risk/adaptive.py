"""Offline adaptive restriction of Prompt 17 fictional research risk."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from enum import Enum, auto
from typing import Protocol

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation, DecisionOutcome, DecisionStatus, DecisionTrace
from amrte.risk.sizing import RiskSizingResult, SizingEligibility, _decimal, quantize_simulated_exposure

ADAPTIVE_RISK_ENGINE_VERSION="1.0"; ZERO=Decimal("0"); ONE=Decimal("1")

class ModifierType(Enum):DRAWDOWN=auto();VOLATILITY=auto();STRATEGY_HEALTH=auto();DATA_HEALTH=auto();PORTFOLIO=auto();PROTECTION=auto();CUSTOM=auto()
class ModifierAvailability(Enum):AVAILABLE=auto();DEGRADED=auto();UNAVAILABLE=auto();NOT_APPLICABLE=auto();UNKNOWN=auto();FUTURE_OWNED=auto()
class ModifierHealth(Enum):HEALTHY=auto();DEGRADED=auto();RESTRICTED=auto();BLOCKED=auto();INVALID=auto();UNKNOWN=auto()
class MissingModifierPolicy(Enum):NEUTRAL_IF_NOT_REQUIRED=auto();RESTRICT=auto();BLOCK=auto()
class CompositionMode(Enum):MULTIPLICATIVE_RESTRICTIVE=auto();MINIMUM_MODIFIER=auto()
class OverlapPolicy(Enum):MOST_RESTRICTIVE_ONLY=auto();PRIMARY_SOURCE_ONLY=auto();ALLOW_MULTIPLICATIVE_IF_INDEPENDENT=auto()
class AdaptiveRiskState(Enum):NORMAL=auto();CAUTION=auto();REDUCED=auto();DEFENSIVE=auto();PROTECT=auto();BLOCKED=auto();UNKNOWN=auto()
class AdaptiveHealth(Enum):HEALTHY=auto();DEGRADED=auto();RESTRICTED=auto();BLOCKED=auto();INVALID=auto();UNKNOWN=auto()
class AdaptiveEligibility(Enum):ELIGIBLE=auto();ELIGIBLE_WITH_RESTRICTIONS=auto();NOT_ELIGIBLE=auto();BLOCKED=auto();INCOMPLETE=auto();UNKNOWN=auto()
class DrawdownBand(Enum):NORMAL=auto();ELEVATED=auto();HIGH=auto();SEVERE=auto();CRITICAL=auto()
class VolatilityState(Enum):VERY_LOW=auto();LOW=auto();NORMAL=auto();ELEVATED=auto();HIGH=auto();EXTREME=auto();UNKNOWN=auto()

@dataclass(frozen=True)
class AdaptiveRiskConfiguration:
    enabled:bool=True;allow_risk_amplification:bool=False;maximum_modifier:Decimal=ONE
    composition_mode:CompositionMode=CompositionMode.MULTIPLICATIVE_RESTRICTIVE;overlap_policy:OverlapPolicy=OverlapPolicy.MOST_RESTRICTIVE_ONLY
    system_maximum_fraction:Decimal=Decimal("0.02");profile_maximum_fraction:Decimal=Decimal("0.02");strategy_family_maximum_fraction:Decimal=Decimal("0.02");strategy_maximum_fraction:Decimal=Decimal("0.02");instrument_maximum_fraction:Decimal=Decimal("0.02");per_hypothesis_maximum_fraction:Decimal=Decimal("0.02")
    drawdown_thresholds:tuple[Decimal,...]=(Decimal("0.02"),Decimal("0.05"),Decimal("0.10"),Decimal("0.20"))
    drawdown_modifiers:tuple[Decimal,...]=(ONE,Decimal("0.8"),Decimal("0.5"),Decimal("0.25"),ZERO)
    volatility_modifiers:tuple[tuple[VolatilityState,Decimal],...]=((VolatilityState.VERY_LOW,Decimal("0.8")),(VolatilityState.LOW,Decimal("0.9")),(VolatilityState.NORMAL,ONE),(VolatilityState.ELEVATED,Decimal("0.75")),(VolatilityState.HIGH,Decimal("0.5")),(VolatilityState.EXTREME,ZERO),(VolatilityState.UNKNOWN,ZERO))
    strategy_health_modifiers:tuple[tuple[str,Decimal],...]=(("HEALTHY",ONE),("DEGRADED",Decimal("0.75")),("RESTRICTED",Decimal("0.4")),("UNAVAILABLE",ZERO),("INVALID",ZERO),("UNKNOWN",ZERO))
    data_health_modifiers:tuple[tuple[str,Decimal],...]=(("HEALTHY",ONE),("DEGRADED",Decimal("0.7")),("INCOMPLETE",Decimal("0.4")),("RESTRICTED",Decimal("0.4")),("UNAVAILABLE",ZERO),("INVALID",ZERO),("UNKNOWN",ZERO))
    portfolio_missing_policy:MissingModifierPolicy=MissingModifierPolicy.NEUTRAL_IF_NOT_REQUIRED;protection_missing_policy:MissingModifierPolicy=MissingModifierPolicy.NEUTRAL_IF_NOT_REQUIRED
    missing_restriction_modifier:Decimal=Decimal("0.5");recovery_confirmation_observations:int=2;cooldown_seconds:int=300
    maximum_modifier_results:int=256;maximum_decisions:int=256;maximum_transitions:int=256;maximum_cache_entries:int=256
    precision:int=28;tolerance:Decimal=Decimal("0.00000001");configuration_snapshot_id:str="ADAPTIVE_RISK_DEFAULT_RESEARCH"
    def validate(self):
        errors=[]
        if self.allow_risk_amplification:errors.append("AR_RISK_AMPLIFICATION_FORBIDDEN")
        try:
            modifiers=(self.maximum_modifier,self.missing_restriction_modifier)+self.drawdown_modifiers+tuple(v for _,v in self.volatility_modifiers)+tuple(v for _,v in self.strategy_health_modifiers)+tuple(v for _,v in self.data_health_modifiers)
            if any(not ZERO<=_decimal(v)<=ONE for v in modifiers):errors.append("AR_MODIFIER_OUT_OF_RANGE")
            caps=(self.system_maximum_fraction,self.profile_maximum_fraction,self.strategy_family_maximum_fraction,self.strategy_maximum_fraction,self.instrument_maximum_fraction,self.per_hypothesis_maximum_fraction)
            if any(_decimal(v)<ZERO or _decimal(v)>ONE for v in caps):errors.append("AR_HARD_MAX_INVALID")
            thresholds=tuple(_decimal(v) for v in self.drawdown_thresholds)
            if len(thresholds)!=4 or thresholds!=tuple(sorted(thresholds)) or any(v<ZERO for v in thresholds):errors.append("AR_DRAWDOWN_BANDS_INVALID")
            dd=tuple(_decimal(v) for v in self.drawdown_modifiers)
            if len(dd)!=5 or any(dd[i+1]>dd[i] for i in range(4)):errors.append("AR_DRAWDOWN_NON_MONOTONIC")
        except ValueError:errors.append("AR_NUMERICAL_INVALID")
        if self.recovery_confirmation_observations<1 or self.cooldown_seconds<0:errors.append("AR_RECOVERY_POLICY_INVALID")
        if min(self.maximum_modifier_results,self.maximum_decisions,self.maximum_transitions,self.maximum_cache_entries)<1:errors.append("AR_HISTORY_BOUND_INVALID")
        return tuple(dict.fromkeys(errors))

@dataclass(frozen=True)
class ResearchEquityObservation:
    observation_id:str;equity:Decimal;observed_at_utc:datetime;available_at_utc:datetime;dataset_id:str
    @classmethod
    def create(cls,equity,at,dataset_id="FICTIONAL_RESEARCH"):
        value=_decimal(equity);return cls(deterministic_id("research_equity",str(value),at.isoformat(),dataset_id),value,at,at,dataset_id)

@dataclass(frozen=True)
class VolatilityEvidence:
    evidence_id:str;state:VolatilityState;available_at_utc:datetime;source_snapshot_id:str;strategy_family:str;health:str="HEALTHY";dependency_group:str="VOLATILITY"

@dataclass(frozen=True)
class HealthEvidence:
    evidence_id:str;state:str;available_at_utc:datetime;source_snapshot_id:str;dependency_group:str

@dataclass(frozen=True)
class RiskModifierResult:
    modifier_id:str;modifier_type:ModifierType;modifier_version:str;raw_input_references:tuple[str,...];raw_state:str;modifier_value:Decimal|None;health:ModifierHealth;availability:ModifierAvailability;restrictions:tuple[str,...];reason_codes:tuple[str,...];as_of_timestamp_utc:datetime;configuration_snapshot_id:str;dependency_group:str
    def __post_init__(self):
        if self.modifier_value is not None and not ZERO<=_decimal(self.modifier_value)<=ONE:raise ValueError("AR_MODIFIER_OUT_OF_RANGE")

class IPortfolioRiskModifierProvider(Protocol):
    def modifier_as_of(self,as_of:datetime)->RiskModifierResult:...
class IProtectionRiskModifierProvider(Protocol):
    def modifier_as_of(self,as_of:datetime)->RiskModifierResult:...

@dataclass(frozen=True)
class AdaptedSimulatedExposure:
    exposure_id:str;prompt17_exposure_decision_id:str;adaptive_risk_amount:Decimal;quantized_simulated_exposure:Decimal;recalculated_risk:Decimal;requantized:bool;reason_codes:tuple[str,...]

@dataclass(frozen=True)
class AdaptiveRiskDecision:
    decision_id:str;strategy_decision_snapshot_id:str;prompt17_risk_budget_id:str;prompt17_exposure_decision_id:str;base_risk_amount:Decimal;base_risk_fraction:Decimal;modifier_results:tuple[RiskModifierResult,...];composite_modifier:Decimal;adaptive_risk_amount:Decimal;adaptive_risk_fraction:Decimal;effective_hard_maximum:Decimal;adaptive_risk_state:AdaptiveRiskState;health:AdaptiveHealth;eligibility:AdaptiveEligibility;restrictions:tuple[str,...];reason_codes:tuple[str,...];previous_risk_state:AdaptiveRiskState|None;transition_reason:str;as_of_timestamp_utc:datetime;configuration_snapshot_id:str;adaptive_risk_engine_version:str;recovery_epoch:int;adapted_exposure:AdaptedSimulatedExposure

@dataclass(frozen=True)
class AdaptiveRiskResult:
    decision:AdaptiveRiskDecision;decision_trace:DecisionTrace

class AdaptiveRiskEngine:
    def __init__(self,configuration:AdaptiveRiskConfiguration=AdaptiveRiskConfiguration(),audit=None,portfolio_provider:IPortfolioRiskModifierProvider|None=None,protection_provider:IProtectionRiskModifierProvider|None=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit;self.portfolio_provider=portfolio_provider;self.protection_provider=protection_provider
        self._peak_by_dataset={};self._state_by_key={};self._recovery_counts={};self._cooldowns={};self._modifiers=OrderedDict();self._decisions=OrderedDict();self._transitions=OrderedDict();self._cache=OrderedDict()
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
    def evaluate(self,prompt17:RiskSizingResult,equity_history:tuple[ResearchEquityObservation,...],volatility:VolatilityEvidence,strategy_health:HealthEvidence,data_health:HealthEvidence):
        d17=prompt17.exposure_decision;b17=prompt17.risk_budget;as_of=d17.as_of_timestamp_utc;cfg=self.configuration
        self._record("adaptive_risk_started",{"prompt17_decision_id":d17.decision_id})
        key=(d17.decision_id,tuple((x.observation_id,str(x.equity)) for x in equity_history),volatility.evidence_id,strategy_health.evidence_id,data_health.evidence_id,cfg.configuration_snapshot_id,ADAPTIVE_RISK_ENGINE_VERSION,d17.recovery_epoch)
        if key in self._cache:self._cache.move_to_end(key);return self._cache[key]
        hard=[]
        if not cfg.enabled:hard.append("AR_DISABLED")
        if b17.risk_budget_id!=d17.risk_budget_id or b17.strategy_decision_snapshot_id!=d17.strategy_decision_snapshot_id:hard.append("AR_PROMPT17_LINEAGE_INVALID")
        if d17.eligibility not in (SizingEligibility.ELIGIBLE,SizingEligibility.ELIGIBLE_WITH_RESTRICTIONS):hard.append("AR_PROMPT17_BLOCK_RETAINED")
        if any(x.available_at_utc>as_of or x.observed_at_utc>as_of for x in equity_history):hard.append("AR_FUTURE_DRAWDOWN_EVIDENCE")
        if volatility.available_at_utc>as_of:hard.append("AR_FUTURE_VOLATILITY_EVIDENCE")
        if strategy_health.available_at_utc>as_of:hard.append("AR_FUTURE_STRATEGY_HEALTH")
        if data_health.available_at_utc>as_of:hard.append("AR_FUTURE_DATA_HEALTH")
        dd=self._drawdown_modifier(equity_history,as_of,b17.strategy_decision_snapshot_id)
        vol=self._mapped_modifier(ModifierType.VOLATILITY,volatility.state.name,{k.name:v for k,v in cfg.volatility_modifiers},volatility.evidence_id,volatility.dependency_group,as_of,"AR_VOL_")
        strategy=self._mapped_modifier(ModifierType.STRATEGY_HEALTH,strategy_health.state,dict(cfg.strategy_health_modifiers),strategy_health.evidence_id,strategy_health.dependency_group,as_of,"AR_STRATEGY_")
        data=self._mapped_modifier(ModifierType.DATA_HEALTH,data_health.state,dict(cfg.data_health_modifiers),data_health.evidence_id,data_health.dependency_group,as_of,"AR_DATA_")
        portfolio=self._future_modifier(ModifierType.PORTFOLIO,self.portfolio_provider,cfg.portfolio_missing_policy,as_of)
        protection=self._future_modifier(ModifierType.PROTECTION,self.protection_provider,cfg.protection_missing_policy,as_of)
        modifiers=(dd,vol,strategy,data,portfolio,protection)
        if any(x.health in (ModifierHealth.BLOCKED,ModifierHealth.INVALID) for x in modifiers):hard.append("AR_HARD_BLOCK")
        selected=self._deduplicate(modifiers)
        participating=[]
        for m in selected:
            if m.availability is ModifierAvailability.NOT_APPLICABLE:continue
            if m.modifier_value is None:
                hard.append("AR_REQUIRED_MODIFIER_UNAVAILABLE");continue
            participating.append(m.modifier_value)
        composite=ZERO if hard else (min(participating,default=ONE) if cfg.composition_mode is CompositionMode.MINIMUM_MODIFIER else _product(participating))
        composite=min(ONE,max(ZERO,composite))
        caps=tuple(_decimal(x) for x in (cfg.system_maximum_fraction,cfg.profile_maximum_fraction,cfg.strategy_family_maximum_fraction,cfg.strategy_maximum_fraction,cfg.instrument_maximum_fraction,cfg.per_hypothesis_maximum_fraction));effective_fraction_cap=min(caps)
        base_amount=_decimal(b17.effective_risk_amount);capital=base_amount/_decimal(b17.effective_risk_fraction) if b17.effective_risk_fraction>0 else ZERO;hard_max_amount=capital*effective_fraction_cap
        with localcontext() as ctx:ctx.prec=cfg.precision;adaptive=min(base_amount*composite,base_amount,hard_max_amount)
        state=self._classify(ZERO if base_amount==0 else adaptive/base_amount)
        state,transition=self._transition(d17.strategy_decision_snapshot_id,state,as_of)
        state_cap={AdaptiveRiskState.NORMAL:ONE,AdaptiveRiskState.CAUTION:Decimal("0.8"),AdaptiveRiskState.REDUCED:Decimal("0.6"),AdaptiveRiskState.DEFENSIVE:Decimal("0.3"),AdaptiveRiskState.PROTECT:Decimal("0.1"),AdaptiveRiskState.BLOCKED:ZERO,AdaptiveRiskState.UNKNOWN:ZERO}[state]
        adaptive=min(adaptive,base_amount*state_cap);composite=ZERO if base_amount==0 else min(composite,adaptive/base_amount)
        exposure=self._reconcile(d17,adaptive)
        if exposure.recalculated_risk>adaptive+_decimal(cfg.tolerance):adaptive=ZERO;composite=ZERO;hard.append("AR_EXPOSURE_INVARIANT_FAILED");exposure=self._reconcile(d17,ZERO);state=AdaptiveRiskState.BLOCKED
        if not ZERO<=adaptive<=base_amount or adaptive>hard_max_amount+_decimal(cfg.tolerance):raise ValueError("AR_RISK_INVARIANT_FAILED")
        reasons=tuple(dict.fromkeys(("AR_BASE_RISK_ACCEPTED",)+tuple(r for m in modifiers for r in m.reason_codes)+tuple(hard)+(transition,)+exposure.reason_codes))
        blocked=adaptive==0;health=AdaptiveHealth.BLOCKED if blocked else AdaptiveHealth.HEALTHY if composite==ONE and not d17.restrictions else AdaptiveHealth.RESTRICTED
        eligibility=AdaptiveEligibility.BLOCKED if blocked else AdaptiveEligibility.ELIGIBLE if composite==ONE and not d17.restrictions else AdaptiveEligibility.ELIGIBLE_WITH_RESTRICTIONS
        previous=self._state_by_key.get(d17.strategy_decision_snapshot_id,(None,None))[0]
        identity=deterministic_id("adaptive_risk",d17.decision_id,*(m.modifier_id for m in modifiers),str(composite),str(adaptive),str(hard_max_amount),state.name,cfg.configuration_snapshot_id,ADAPTIVE_RISK_ENGINE_VERSION,as_of.isoformat())
        decision=AdaptiveRiskDecision(identity,d17.strategy_decision_snapshot_id,b17.risk_budget_id,d17.decision_id,base_amount,b17.effective_risk_fraction,modifiers,composite,adaptive,(adaptive/capital if capital>0 else ZERO),hard_max_amount,state,health,eligibility,tuple(dict.fromkeys(d17.restrictions+tuple(hard))),reasons,previous,transition,as_of,cfg.configuration_snapshot_id,ADAPTIVE_RISK_ENGINE_VERSION,d17.recovery_epoch,exposure)
        status=DecisionStatus.FAILED if blocked else DecisionStatus.PASSED
        checks=(DecisionEvaluation("PROMPT17_AUTHORITY",status,"AR_PROMPT17_AUTHORITY","Prompt 17 budget and restrictions retained",(b17.risk_budget_id,d17.decision_id)),DecisionEvaluation("ADAPTIVE_MODIFIERS",status,reasons[-1],"Point-in-time modifiers, overlap, hard maximum and exposure invariant evaluated",tuple(m.modifier_id for m in modifiers)))
        trace=DecisionTrace(identity,d17.decision_id,as_of,checks,DecisionOutcome.NO_ACTION if blocked else DecisionOutcome.ACCEPTED,reasons[-1],as_of,"PROMPT17_AUTHORITY" if blocked else None)
        result=AdaptiveRiskResult(decision,trace);self._decisions[identity]=decision;self._cache[key]=result
        for m in modifiers:self._modifiers[m.modifier_id]=m
        self._bound();self._record("adaptive_risk_blocked" if blocked else "adaptive_risk_completed",{"decision_id":identity,"state":state.name});return result
    def _drawdown_modifier(self,history,as_of,key):
        valid=tuple(x for x in history if x.available_at_utc<=as_of and x.observed_at_utc<=as_of)
        if not valid or any(x.equity<=0 for x in valid):return self._modifier(ModifierType.DRAWDOWN,"INVALID",ZERO,ModifierHealth.BLOCKED,ModifierAvailability.UNAVAILABLE,tuple(x.observation_id for x in valid),"DRAWDOWN",as_of,"AR_DD_INVALID")
        datasets={x.dataset_id for x in valid}
        if len(datasets)!=1:return self._modifier(ModifierType.DRAWDOWN,"DATASET_MISMATCH",ZERO,ModifierHealth.BLOCKED,ModifierAvailability.UNAVAILABLE,tuple(x.observation_id for x in valid),"DRAWDOWN",as_of,"AR_DD_INVALID")
        dataset=next(iter(datasets));peak=max(x.equity for x in valid);persisted=self._peak_by_dataset.get(dataset,ZERO);peak=max(peak,persisted);self._peak_by_dataset[dataset]=peak;current=max(valid,key=lambda x:(x.observed_at_utc,x.observation_id)).equity;dd=(peak-current)/peak
        thresholds=self.configuration.drawdown_thresholds;index=sum(dd>=x for x in thresholds);band=tuple(DrawdownBand)[index];value=self.configuration.drawdown_modifiers[index]
        health=ModifierHealth.BLOCKED if value==0 else ModifierHealth.HEALTHY if value==1 else ModifierHealth.RESTRICTED
        return self._modifier(ModifierType.DRAWDOWN,f"{band.name}:{dd}",value,health,ModifierAvailability.AVAILABLE,tuple(x.observation_id for x in valid),"DRAWDOWN",as_of,f"AR_DD_{band.name}")
    def _mapped_modifier(self,kind,state,mapping,evidence,group,as_of,prefix):
        value=mapping.get(state,ZERO);health=ModifierHealth.BLOCKED if value==0 else ModifierHealth.HEALTHY if value==1 else ModifierHealth.RESTRICTED
        return self._modifier(kind,state,value,health,ModifierAvailability.UNKNOWN if state=="UNKNOWN" else ModifierAvailability.AVAILABLE,(evidence,),group,as_of,prefix+state)
    def _future_modifier(self,kind,provider,policy,as_of):
        if provider:
            result=provider.modifier_as_of(as_of)
            if result.as_of_timestamp_utc>as_of:return self._modifier(kind,"FUTURE",ZERO,ModifierHealth.BLOCKED,ModifierAvailability.UNAVAILABLE,(result.modifier_id,),kind.name,as_of,f"AR_{kind.name}_FUTURE")
            return result
        if policy is MissingModifierPolicy.NEUTRAL_IF_NOT_REQUIRED:value=ONE;health=ModifierHealth.DEGRADED;availability=ModifierAvailability.FUTURE_OWNED
        elif policy is MissingModifierPolicy.RESTRICT:value=self.configuration.missing_restriction_modifier;health=ModifierHealth.RESTRICTED;availability=ModifierAvailability.UNAVAILABLE
        else:value=ZERO;health=ModifierHealth.BLOCKED;availability=ModifierAvailability.UNAVAILABLE
        return self._modifier(kind,"FUTURE_OWNED",value,health,availability,(),kind.name,as_of,f"AR_{kind.name}_FUTURE_OWNED")
    def _modifier(self,kind,state,value,health,availability,refs,group,as_of,reason):
        identity=deterministic_id("adaptive_modifier",kind.name,state,str(value),health.name,availability.name,*refs,self.configuration.configuration_snapshot_id,ADAPTIVE_RISK_ENGINE_VERSION,as_of.isoformat())
        return RiskModifierResult(identity,kind,"1.0",tuple(refs),state,_decimal(value),health,availability,() if value==ONE else (reason,), (reason,),as_of,self.configuration.configuration_snapshot_id,group)
    def _deduplicate(self,modifiers):
        if self.configuration.overlap_policy is OverlapPolicy.ALLOW_MULTIPLICATIVE_IF_INDEPENDENT:return modifiers
        groups={}
        for m in modifiers:
            if m.availability is ModifierAvailability.NOT_APPLICABLE:continue
            old=groups.get(m.dependency_group)
            if old is None or (m.modifier_value if m.modifier_value is not None else ZERO)<(old.modifier_value if old.modifier_value is not None else ZERO):groups[m.dependency_group]=m
        return tuple(groups.values())
    def _classify(self,factor):
        if factor<=0:return AdaptiveRiskState.BLOCKED
        if factor<=Decimal("0.1"):return AdaptiveRiskState.PROTECT
        if factor<=Decimal("0.3"):return AdaptiveRiskState.DEFENSIVE
        if factor<=Decimal("0.6"):return AdaptiveRiskState.REDUCED
        if factor<ONE:return AdaptiveRiskState.CAUTION
        return AdaptiveRiskState.NORMAL
    def _transition(self,key,proposed,as_of):
        previous,changed_at=self._state_by_key.get(key,(None,None));severity={s:i for i,s in enumerate((AdaptiveRiskState.NORMAL,AdaptiveRiskState.CAUTION,AdaptiveRiskState.REDUCED,AdaptiveRiskState.DEFENSIVE,AdaptiveRiskState.PROTECT,AdaptiveRiskState.BLOCKED,AdaptiveRiskState.UNKNOWN))}
        if previous is None or severity[proposed]>=severity[previous]:accepted=proposed;self._recovery_counts[key]=0;reason="AR_RISK_DOWN_FAST" if previous else "AR_STATE_INITIAL"
        else:
            count=self._recovery_counts.get(key,0)+1;self._recovery_counts[key]=count;cooldown=self._cooldowns.get(key)
            if cooldown and as_of<cooldown:accepted=previous;reason="AR_COOLDOWN_ACTIVE"
            elif count<self.configuration.recovery_confirmation_observations:accepted=previous;reason="AR_RECOVERY_PENDING"
            else:
                accepted=tuple(AdaptiveRiskState)[max(0,severity[previous]-1)];reason="AR_RECOVERY_STEP";self._recovery_counts[key]=0
        if accepted in (AdaptiveRiskState.DEFENSIVE,AdaptiveRiskState.PROTECT,AdaptiveRiskState.BLOCKED):self._cooldowns[key]=max(self._cooldowns.get(key,as_of),as_of+timedelta(seconds=self.configuration.cooldown_seconds))
        if accepted!=previous:
            tid=deterministic_id("adaptive_transition",key,previous.name if previous else "NONE",accepted.name,as_of.isoformat());self._transitions[tid]=(previous,accepted,as_of,reason)
        self._state_by_key[key]=(accepted,as_of if accepted!=previous else changed_at);return accepted,reason
    def _reconcile(self,d17,adaptive):
        if adaptive<=0 or d17.invalidation_distance is None:return AdaptedSimulatedExposure(deterministic_id("adapted_exposure",d17.decision_id,"ZERO"),d17.decision_id,ZERO,ZERO,ZERO,d17.quantized_simulated_exposure>0,("AR_NO_ACTION",))
        q=quantize_simulated_exposure(adaptive,d17.invalidation_distance,d17.cost_buffer,d17.minimum_exposure,d17.maximum_exposure,d17.exposure_step,self.configuration.precision)
        quantized=min(q.quantized,d17.quantized_simulated_exposure);recalculated=quantized*d17.invalidation_distance+d17.cost_buffer if quantized>0 else ZERO
        reasons=("AR_EXPOSURE_BELOW_MINIMUM","AR_NO_ACTION") if quantized==0 else (("AR_EXPOSURE_REDUCED",) if quantized<d17.quantized_simulated_exposure else ("AR_EXPOSURE_PRESERVED",))
        return AdaptedSimulatedExposure(deterministic_id("adapted_exposure",d17.decision_id,str(adaptive),str(quantized),str(recalculated)),d17.decision_id,adaptive,quantized,recalculated,quantized!=d17.quantized_simulated_exposure,reasons)
    def _bound(self):
        for store,limit in ((self._modifiers,self.configuration.maximum_modifier_results),(self._decisions,self.configuration.maximum_decisions),(self._transitions,self.configuration.maximum_transitions),(self._cache,self.configuration.maximum_cache_entries)):
            while len(store)>limit:store.popitem(last=False)
    def recovery_state(self):
        return {"adaptive_risk_engine_version":ADAPTIVE_RISK_ENGINE_VERSION,"configuration_snapshot_id":self.configuration.configuration_snapshot_id,"peak_by_dataset":dict(self._peak_by_dataset),"state_by_key":dict(self._state_by_key),"recovery_counts":dict(self._recovery_counts),"cooldowns":dict(self._cooldowns),"last_adaptive_risk_decision_id":next(reversed(self._decisions),None)}
    def restore(self,state):
        if not self.validate_recovery(state):return False
        self._peak_by_dataset=dict(state.get("peak_by_dataset",{}));self._state_by_key=dict(state.get("state_by_key",{}));self._recovery_counts=dict(state.get("recovery_counts",{}));self._cooldowns=dict(state.get("cooldowns",{}));return True
    def validate_recovery(self,state):return state.get("adaptive_risk_engine_version")==ADAPTIVE_RISK_ENGINE_VERSION and state.get("configuration_snapshot_id")==self.configuration.configuration_snapshot_id

def _product(values):
    result=ONE
    for value in values:result*=_decimal(value)
    return result
