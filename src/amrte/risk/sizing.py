"""Per-hypothesis fictional risk budget and normalized simulated exposure sizing."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal,InvalidOperation,ROUND_FLOOR,localcontext
from enum import Enum,auto

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation,DecisionOutcome,DecisionStatus,DecisionTrace
from amrte.strategies.strategy_arbitration import ArbitrationOutcome,ResearchAvailability,StrategyDecisionSnapshot

RISK_ENGINE_VERSION="1.0";RISK_SCHEMA_VERSION="1.0";ZERO=Decimal("0");ONE=Decimal("1")

class CapitalSource(Enum):CONFIGURED_RESEARCH_CAPITAL=auto();BACKTEST_RESEARCH_LEDGER=auto();FICTIONAL_SIMULATION_LEDGER=auto();SYNTHETIC_TEST_FIXTURE=auto()
class InvalidationSource(Enum):STRATEGY_RESEARCH_METADATA=auto();STRUCTURE_RESEARCH_METADATA=auto();SYNTHETIC_TEST_FIXTURE=auto();CONFIGURED_RESEARCH_DISTANCE=auto()
class CostBufferSource(Enum):CONFIGURED_FIXED_NORMALIZED_COST=auto();HISTORICAL_RESEARCH_COST_SERIES=auto();SYNTHETIC_COST_FIXTURE=auto();NONE=auto()
class MissingCostPolicy(Enum):BLOCK=auto();USE_CONFIGURED_CONSERVATIVE_BUFFER=auto();NOT_REQUIRED=auto()
class MultipleCompatiblePolicy(Enum):BLOCK=auto();SHARED_BUDGET=auto()
class ModifierComposition(Enum):MIN=auto();MULTIPLICATIVE=auto()
class DistanceHealth(Enum):VALID=auto();TOO_SMALL=auto();TOO_LARGE=auto();MISSING=auto();INVALID=auto();UNKNOWN=auto()
class SizingHealth(Enum):HEALTHY=auto();DEGRADED=auto();RESTRICTED=auto();INSUFFICIENT_DATA=auto();BLOCKED=auto();INVALID=auto();UNKNOWN=auto()
class SizingEligibility(Enum):ELIGIBLE=auto();ELIGIBLE_WITH_RESTRICTIONS=auto();NOT_ELIGIBLE=auto();BLOCKED=auto();INCOMPLETE=auto();UNKNOWN=auto()

def _decimal(value):
    try:
        result=value if isinstance(value,Decimal) else Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):raise ValueError("RISK_NUMERICAL_INVALID")
    if not result.is_finite():raise ValueError("RISK_NUMERICAL_INVALID")
    return result

@dataclass(frozen=True)
class QuantizedExposure:
    raw:Decimal;quantized:Decimal;recalculated_risk:Decimal;capped:bool;rounded_down:bool

def quantize_simulated_exposure(risk_amount,distance,cost_buffer,minimum_exposure,maximum_exposure,exposure_step,precision=28):
    """Pure conservative Prompt 17 sizing primitive reusable by later risk layers."""
    risk=_decimal(risk_amount);dist=_decimal(distance);cost=_decimal(cost_buffer);minimum=_decimal(minimum_exposure);maximum=_decimal(maximum_exposure);step=_decimal(exposure_step)
    if risk<0 or dist<=0 or cost<0 or minimum<0 or maximum<minimum or step<=0:raise ValueError("RISK_QUANTIZATION_INVALID")
    usable=max(ZERO,risk-cost)
    with localcontext() as ctx:
        ctx.prec=precision;raw=usable/dist;capped=min(raw,maximum);quantized=(capped/step).to_integral_value(rounding=ROUND_FLOOR)*step;recalculated=quantized*dist+cost if quantized>0 else ZERO
    if quantized<minimum:quantized=ZERO;recalculated=ZERO
    return QuantizedExposure(raw,quantized,recalculated,raw>maximum,quantized<capped)

@dataclass(frozen=True)
class RiskSizingConfiguration:
    enabled:bool=True;default_research_capital:Decimal=Decimal("10000");base_risk_fraction:Decimal=Decimal("0.01")
    minimum_invalidation_distance:Decimal=Decimal("0.10");maximum_invalidation_distance:Decimal=Decimal("10")
    cost_buffer_enabled:bool=False;missing_cost_policy:MissingCostPolicy=MissingCostPolicy.NOT_REQUIRED
    conservative_cost_buffer:Decimal=ZERO;minimum_exposure:Decimal=Decimal("0.01");maximum_exposure:Decimal=Decimal("100")
    exposure_step:Decimal=Decimal("0.01");multiple_compatible_policy:MultipleCompatiblePolicy=MultipleCompatiblePolicy.BLOCK
    modifier_composition:ModifierComposition=ModifierComposition.MIN;precision:int=28;tolerance:Decimal=Decimal("0.00000001")
    maximum_decisions:int=256;maximum_budgets:int=256;maximum_cache_entries:int=256
    configuration_snapshot_id:str="RISK_SIZING_DEFAULT_RESEARCH"
    def validate(self):
        errors=[]
        values=(self.default_research_capital,self.base_risk_fraction,self.minimum_invalidation_distance,self.maximum_invalidation_distance,self.conservative_cost_buffer,self.minimum_exposure,self.maximum_exposure,self.exposure_step,self.tolerance)
        try:values=tuple(_decimal(x) for x in values)
        except ValueError:return ("RISK_NUMERICAL_INVALID",)
        capital,fraction,mind,maxd,cost,mine,maxe,step,tol=values
        if capital<0:errors.append("RISK_NEGATIVE_CAPITAL")
        if not ZERO<=fraction<=ONE:errors.append("RISK_INVALID_FRACTION")
        if mind<=0 or maxd<mind:errors.append("RISK_INVALID_DISTANCE_RANGE")
        if cost<0:errors.append("RISK_NEGATIVE_COST")
        if mine<0 or maxe<mine:errors.append("RISK_INVALID_EXPOSURE_RANGE")
        if step<=0:errors.append("RISK_INVALID_EXPOSURE_STEP")
        if tol<0 or self.precision<8 or self.precision>50:errors.append("RISK_INVALID_NUMERICAL_POLICY")
        if min(self.maximum_decisions,self.maximum_budgets,self.maximum_cache_entries)<1:errors.append("RISK_INVALID_BOUND")
        return tuple(errors)

@dataclass(frozen=True)
class ResearchCapitalContext:
    capital_context_id:str;starting_research_capital:Decimal;current_research_capital:Decimal
    available_research_capital:Decimal;currency_label:str;as_of_timestamp_utc:datetime
    source_type:CapitalSource;dataset_id:str;configuration_snapshot_id:str;available_at_utc:datetime
    @classmethod
    def create(cls,amount,as_of,source=CapitalSource.CONFIGURED_RESEARCH_CAPITAL,dataset_id="FICTIONAL_RESEARCH",configuration_snapshot_id="RISK_SIZING_DEFAULT_RESEARCH",currency_label="FRC"):
        value=_decimal(amount);identity=deterministic_id("research_capital",str(value),as_of.isoformat(),source.name,dataset_id,configuration_snapshot_id)
        return cls(identity,value,value,value,currency_label,as_of,source,dataset_id,configuration_snapshot_id,as_of)

@dataclass(frozen=True)
class InvalidationDistanceContext:
    context_id:str;normalized_distance:Decimal|None;source_type:InvalidationSource;source_evidence_id:str
    as_of_timestamp_utc:datetime;available_at_utc:datetime;health:DistanceHealth;configuration_snapshot_id:str
    @classmethod
    def create(cls,distance,as_of,source_evidence_id="SYNTHETIC_DISTANCE",source_type=InvalidationSource.SYNTHETIC_TEST_FIXTURE,configuration_snapshot_id="RISK_SIZING_DEFAULT_RESEARCH"):
        value=None if distance is None else _decimal(distance);identity=deterministic_id("invalidation_distance",str(value),as_of.isoformat(),source_type.name,source_evidence_id,configuration_snapshot_id)
        return cls(identity,value,source_type,source_evidence_id,as_of,as_of,DistanceHealth.MISSING if value is None else DistanceHealth.VALID,configuration_snapshot_id)

@dataclass(frozen=True)
class ResearchCostBuffer:
    buffer_id:str;normalized_amount:Decimal|None;source_type:CostBufferSource;source_evidence_id:str
    as_of_timestamp_utc:datetime;available_at_utc:datetime;health:str;configuration_snapshot_id:str
    @classmethod
    def create(cls,amount,as_of,source_type=CostBufferSource.SYNTHETIC_COST_FIXTURE,configuration_snapshot_id="RISK_SIZING_DEFAULT_RESEARCH"):
        value=None if amount is None else _decimal(amount);identity=deterministic_id("research_cost",str(value),as_of.isoformat(),source_type.name,configuration_snapshot_id)
        return cls(identity,value,source_type,"RESEARCH_COST_FIXTURE",as_of,as_of,"MISSING" if value is None else "VALID",configuration_snapshot_id)

@dataclass(frozen=True)
class RiskModifier:
    modifier_id:str;factor:Decimal;source_module:str;reason_code:str;available_at_utc:datetime
    def __post_init__(self):
        value=_decimal(self.factor)
        if not ZERO<=value<=ONE:raise ValueError("RISK_MODIFIER_MAY_NOT_AMPLIFY")

@dataclass(frozen=True)
class RiskBudget:
    risk_budget_id:str;strategy_decision_snapshot_id:str;capital_context_id:str;base_risk_fraction:Decimal
    base_risk_amount:Decimal;effective_risk_fraction:Decimal;effective_risk_amount:Decimal
    applied_restrictions:tuple[str,...];applied_buffers:tuple[str,...];health:SizingHealth
    as_of_timestamp_utc:datetime;configuration_snapshot_id:str;risk_engine_version:str;recovery_epoch:int

@dataclass(frozen=True)
class SimulatedExposureDecision:
    decision_id:str;strategy_decision_snapshot_id:str;preferred_research_signal_id:str|None
    capital_context_id:str;risk_budget_id:str;base_risk_fraction:Decimal;effective_risk_fraction:Decimal
    base_risk_amount:Decimal;effective_risk_amount:Decimal;usable_risk_amount:Decimal
    invalidation_distance:Decimal|None;cost_buffer:Decimal;raw_simulated_exposure:Decimal
    quantized_simulated_exposure:Decimal;minimum_exposure:Decimal;maximum_exposure:Decimal
    exposure_step:Decimal;recalculated_risk:Decimal;eligibility:SizingEligibility;health:SizingHealth
    restrictions:tuple[str,...];reason_codes:tuple[str,...];as_of_timestamp_utc:datetime
    configuration_snapshot_id:str;risk_engine_version:str;recovery_epoch:int

@dataclass(frozen=True)
class RiskSizingResult:
    risk_budget:RiskBudget;exposure_decision:SimulatedExposureDecision;decision_trace:DecisionTrace

class RiskSizingEngine:
    def __init__(self,configuration:RiskSizingConfiguration=RiskSizingConfiguration(),audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit;self._budgets=OrderedDict();self._decisions=OrderedDict();self._cache=OrderedDict()
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
    def size(self,snapshot:StrategyDecisionSnapshot,capital:ResearchCapitalContext,invalidation:InvalidationDistanceContext|None,cost:ResearchCostBuffer|None=None,modifiers:tuple[RiskModifier,...]=()):
        cfg=self.configuration;self._record("risk_sizing_started",{"snapshot_id":snapshot.snapshot_id});as_of=snapshot.as_of_timestamp_utc
        key=(snapshot.snapshot_id,capital.capital_context_id,invalidation.context_id if invalidation else "MISSING",cost.buffer_id if cost else "NONE",tuple(sorted((x.modifier_id,str(x.factor)) for x in modifiers)),cfg.configuration_snapshot_id,RISK_ENGINE_VERSION)
        if key in self._cache:self._cache.move_to_end(key);return self._cache[key]
        reasons=[];restrictions=list(snapshot.restrictions);hard=None
        if not cfg.enabled:hard="RISK_SIZING_DISABLED"
        elif snapshot.outcome in (ArbitrationOutcome.NO_ACTION,ArbitrationOutcome.ALL_REJECTED):hard="RISK_UPSTREAM_NO_ACTION"
        elif snapshot.outcome in (ArbitrationOutcome.BLOCKED,ArbitrationOutcome.INCOMPLETE,ArbitrationOutcome.UNKNOWN):hard="RISK_UPSTREAM_BLOCKED"
        elif snapshot.research_availability not in (ResearchAvailability.AVAILABLE,ResearchAvailability.AVAILABLE_WITH_RESTRICTIONS):hard="RISK_UPSTREAM_UNAVAILABLE"
        elif snapshot.outcome is ArbitrationOutcome.MULTIPLE_COMPATIBLE and cfg.multiple_compatible_policy is MultipleCompatiblePolicy.BLOCK:hard="RISK_MULTIPLE_COMPATIBLE_RESTRICTED"
        try:available=_decimal(capital.available_research_capital)
        except ValueError:available=ZERO;hard="RISK_CAPITAL_INVALID"
        if capital.available_at_utc>as_of:hard="RISK_FUTURE_CAPITAL"
        if available<0:hard="RISK_CAPITAL_INVALID"
        if invalidation is None or invalidation.normalized_distance is None:distance=None;hard=hard or "RISK_INVALIDATION_MISSING"
        else:
            try:distance=_decimal(invalidation.normalized_distance)
            except ValueError:distance=None;hard=hard or "RISK_INVALIDATION_INVALID"
            if invalidation.available_at_utc>as_of:hard=hard or "RISK_FUTURE_INVALIDATION"
            elif distance is not None and distance<=0:hard=hard or "RISK_INVALIDATION_ZERO"
            elif distance is not None and distance<_decimal(cfg.minimum_invalidation_distance):hard=hard or "RISK_INVALIDATION_TOO_SMALL"
            elif distance is not None and distance>_decimal(cfg.maximum_invalidation_distance):hard=hard or "RISK_INVALIDATION_TOO_LARGE"
        factor=ONE
        if modifiers:
            if any(x.available_at_utc>as_of for x in modifiers):hard=hard or "RISK_FUTURE_MODIFIER"
            factors=tuple(_decimal(x.factor) for x in modifiers)
            factor=min(factors) if cfg.modifier_composition is ModifierComposition.MIN else _product(factors)
        base_fraction=_decimal(cfg.base_risk_fraction);effective_fraction=base_fraction*factor
        with localcontext() as ctx:
            ctx.prec=cfg.precision;base_amount=available*base_fraction;effective_amount=available*effective_fraction
        buffer=ZERO
        if cfg.cost_buffer_enabled:
            if cost is None or cost.normalized_amount is None:
                if cfg.missing_cost_policy is MissingCostPolicy.BLOCK:hard=hard or "RISK_COST_UNKNOWN"
                elif cfg.missing_cost_policy is MissingCostPolicy.USE_CONFIGURED_CONSERVATIVE_BUFFER:buffer=_decimal(cfg.conservative_cost_buffer);reasons.append("RISK_CONSERVATIVE_COST_BUFFER")
            else:
                if cost.available_at_utc>as_of:hard=hard or "RISK_FUTURE_COST"
                buffer=_decimal(cost.normalized_amount)
                if buffer<0:hard=hard or "RISK_COST_INVALID"
        usable=max(ZERO,effective_amount-buffer)
        if cfg.cost_buffer_enabled and usable<=0:hard=hard or "RISK_COST_EXHAUSTS_BUDGET"
        if hard:return self._zero(snapshot,capital,distance,buffer,base_fraction,base_amount,effective_fraction,effective_amount,hard,tuple(restrictions),key)
        maximum=_decimal(cfg.maximum_exposure);step=_decimal(cfg.exposure_step);q=quantize_simulated_exposure(effective_amount,distance,buffer,cfg.minimum_exposure,maximum,step,cfg.precision);raw=q.raw;quantized=q.quantized;recalculated=q.recalculated_risk
        if q.capped:reasons.append("RISK_EXPOSURE_CAPPED")
        if q.rounded_down:reasons.append("RISK_EXPOSURE_QUANTIZED_DOWN")
        if quantized==0:return self._zero(snapshot,capital,distance,buffer,base_fraction,base_amount,effective_fraction,effective_amount,"RISK_EXPOSURE_BELOW_MINIMUM",tuple(restrictions),key)
        if recalculated>effective_amount+_decimal(cfg.tolerance):return self._zero(snapshot,capital,distance,buffer,base_fraction,base_amount,effective_fraction,effective_amount,"RISK_OVERRUN_BLOCKED",tuple(restrictions),key)
        budget=self._budget(snapshot,capital,base_fraction,base_amount,effective_fraction,effective_amount,tuple(restrictions),tuple(x.modifier_id for x in modifiers),SizingHealth.HEALTHY)
        did=deterministic_id("simulated_exposure",snapshot.snapshot_id,capital.capital_context_id,invalidation.context_id,cost.buffer_id if cost else "NONE",str(quantized),str(recalculated),cfg.configuration_snapshot_id,RISK_ENGINE_VERSION)
        decision=SimulatedExposureDecision(did,snapshot.snapshot_id,snapshot.preferred_research_signal_id,capital.capital_context_id,budget.risk_budget_id,base_fraction,effective_fraction,base_amount,effective_amount,usable,distance,buffer,raw,quantized,_decimal(cfg.minimum_exposure),maximum,step,recalculated,SizingEligibility.ELIGIBLE_WITH_RESTRICTIONS if restrictions or factor<ONE else SizingEligibility.ELIGIBLE,SizingHealth.RESTRICTED if restrictions or factor<ONE else SizingHealth.HEALTHY,tuple(restrictions),tuple(reasons or ("RISK_SIMULATED_EXPOSURE_CREATED",)),as_of,cfg.configuration_snapshot_id,RISK_ENGINE_VERSION,snapshot.recovery_epoch)
        result=self._result(snapshot,budget,decision,key);self._record("risk_sizing_completed",{"decision_id":did,"eligibility":decision.eligibility.name});return result
    def _budget(self,snapshot,capital,bf,ba,ef,ea,restrictions,buffers,health):
        identity=deterministic_id("risk_budget",snapshot.snapshot_id,capital.capital_context_id,str(bf),str(ba),str(ef),str(ea),self.configuration.configuration_snapshot_id,RISK_ENGINE_VERSION)
        return RiskBudget(identity,snapshot.snapshot_id,capital.capital_context_id,bf,ba,ef,ea,restrictions,buffers,health,snapshot.as_of_timestamp_utc,self.configuration.configuration_snapshot_id,RISK_ENGINE_VERSION,snapshot.recovery_epoch)
    def _zero(self,snapshot,capital,distance,buffer,bf,ba,ef,ea,reason,restrictions,key):
        budget=self._budget(snapshot,capital,bf,ba,ZERO,ZERO,restrictions+(reason,),(),SizingHealth.BLOCKED)
        did=deterministic_id("simulated_exposure",snapshot.snapshot_id,capital.capital_context_id,reason,self.configuration.configuration_snapshot_id,RISK_ENGINE_VERSION)
        decision=SimulatedExposureDecision(did,snapshot.snapshot_id,snapshot.preferred_research_signal_id,capital.capital_context_id,budget.risk_budget_id,bf,ZERO,ba,ZERO,ZERO,distance,buffer,ZERO,ZERO,_decimal(self.configuration.minimum_exposure),_decimal(self.configuration.maximum_exposure),_decimal(self.configuration.exposure_step),ZERO,SizingEligibility.BLOCKED,SizingHealth.BLOCKED,restrictions+(reason,),(reason,"RISK_NO_ACTION"),snapshot.as_of_timestamp_utc,self.configuration.configuration_snapshot_id,RISK_ENGINE_VERSION,snapshot.recovery_epoch)
        result=self._result(snapshot,budget,decision,key);self._record("risk_no_action",{"decision_id":did,"reason":reason});return result
    def _result(self,snapshot,budget,decision,key):
        status=DecisionStatus.PASSED if decision.eligibility in (SizingEligibility.ELIGIBLE,SizingEligibility.ELIGIBLE_WITH_RESTRICTIONS) else DecisionStatus.FAILED
        checks=(DecisionEvaluation("PHASE_III_GATE",status,decision.reason_codes[0],"StrategyDecisionSnapshot authority and restrictions applied",(snapshot.snapshot_id,)),DecisionEvaluation("RISK_MATHEMATICS",status,decision.reason_codes[-1],"Decimal budget, distance, cost and conservative quantization validated",(budget.risk_budget_id,decision.decision_id)))
        outcome=DecisionOutcome.ACCEPTED if status is DecisionStatus.PASSED else DecisionOutcome.NO_ACTION;trace=DecisionTrace(decision.decision_id,snapshot.snapshot_id,snapshot.as_of_timestamp_utc,checks,outcome,decision.reason_codes[-1],snapshot.as_of_timestamp_utc,"PHASE_III_GATE" if status is DecisionStatus.FAILED else None)
        result=RiskSizingResult(budget,decision,trace);self._budgets[budget.risk_budget_id]=budget;self._decisions[decision.decision_id]=decision;self._cache[key]=result
        for store,limit in ((self._budgets,self.configuration.maximum_budgets),(self._decisions,self.configuration.maximum_decisions),(self._cache,self.configuration.maximum_cache_entries)):
            while len(store)>limit:store.popitem(last=False)
        return result
    def recovery_state(self):return {"risk_engine_version":RISK_ENGINE_VERSION,"configuration_snapshot_id":self.configuration.configuration_snapshot_id,"last_risk_budget_id":next(reversed(self._budgets),None),"last_exposure_decision_id":next(reversed(self._decisions),None)}
    def validate_recovery(self,state):return state.get("risk_engine_version")==RISK_ENGINE_VERSION and state.get("configuration_snapshot_id")==self.configuration.configuration_snapshot_id

def _product(values):
    result=ONE
    for value in values:result*=value
    return result
