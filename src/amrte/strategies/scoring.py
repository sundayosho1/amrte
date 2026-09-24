"""Deterministic, explainable research scoring. Scores never authorize action."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum,auto
from math import fsum,isfinite
from types import MappingProxyType
from typing import Mapping

from amrte.core.identity import deterministic_id
from amrte.strategies.framework import (DetectionResult,EvidenceAvailability,EvidenceCategory,
    QualificationResult,QualificationState,ScoreHealth,SignalDirection,SignalScore,
    StrategyEvaluationContext,StrategyFamily)

SCORING_ENGINE_VERSION="1.0"
SCORING_SCHEMA_VERSION="1.0"

class FactorGroup(Enum):
    REGIME=auto();STRUCTURE=auto();TREND=auto();MOMENTUM=auto();VOLATILITY=auto();SESSION=auto();MARKET_CONDITION=auto();SETUP_QUALITY=auto();NEWS_CONTEXT=auto();SPREAD_QUALITY=auto();RISK_REWARD=auto();CORRELATION=auto();CUSTOM=auto()
class FactorAvailability(Enum):AVAILABLE=auto();DEGRADED=auto();UNAVAILABLE=auto();NOT_APPLICABLE=auto();UNKNOWN=auto()
class FactorHealth(Enum):VALID=auto();DEGRADED=auto();UNAVAILABLE=auto();INVALID=auto();UNKNOWN=auto()
class FactorRequirement(Enum):MANDATORY=auto();OPTIONAL=auto();SUPPORTING=auto();NOT_APPLICABLE=auto()
class NormalizationMethod(Enum):LINEAR=auto();BOUNDED_LINEAR=auto();PIECEWISE_LINEAR=auto();PERCENTILE_BASED=auto();DISTANCE_FROM_TARGET=auto();BOOLEAN=auto();CATEGORICAL=auto();CUSTOM_REGISTERED=auto()
class MissingFactorPolicy(Enum):RENORMALIZE_AVAILABLE_OPTIONAL=auto();PENALIZE_MISSING_OPTIONAL=auto();REJECT_IF_REQUIRED=auto()
class ConflictSeverity(Enum):LOW=auto();MEDIUM=auto();HIGH=auto();CRITICAL=auto();UNKNOWN=auto()
class DirectionalRelation(Enum):SUPPORTS=auto();CONFLICTS=auto();NEUTRAL=auto();UNKNOWN=auto()
class QualityBand(Enum):VERY_LOW=auto();LOW=auto();MODERATE=auto();HIGH=auto();VERY_HIGH=auto();UNKNOWN=auto()

@dataclass(frozen=True)
class NormalizationConfiguration:
    method:NormalizationMethod=NormalizationMethod.BOUNDED_LINEAR
    minimum:float=0.0;maximum:float=100.0;target:float|None=None
    direction:int=1;clamp:bool=True;units:str="score"
    categories:tuple[tuple[str,float],...]=()
    def validate(self):
        errors=[]
        if not all(isfinite(v) for v in (self.minimum,self.maximum)):errors.append("NON_FINITE_RANGE")
        if self.maximum<=self.minimum:errors.append("INVALID_RANGE")
        if self.direction not in (-1,1):errors.append("INVALID_DIRECTION")
        if self.method is NormalizationMethod.CUSTOM_REGISTERED:errors.append("UNREGISTERED_CUSTOM_NORMALIZER")
        return tuple(errors)

@dataclass(frozen=True)
class FactorDefinition:
    factor_id:str;group:FactorGroup;weight:float
    requirement:FactorRequirement=FactorRequirement.OPTIONAL
    normalization:NormalizationConfiguration=NormalizationConfiguration()
    dependencies:tuple[str,...]=();dependency_group:str|None=None
    timeframe_role:str="STRATEGY";source_module:str="STRATEGY_EVIDENCE"
    group_cap:float|None=None

@dataclass(frozen=True)
class ScoringFactor:
    factor_id:str;factor_type:str;factor_group:FactorGroup;source_module:str
    source_snapshot_id:str;raw_value:object;normalized_value:float|None;weight:float
    availability:FactorAvailability;health:FactorHealth;directional_relation:DirectionalRelation
    contribution:float;confidence:float;reason_codes:tuple[str,...]
    timeframe_role:str="STRATEGY";dependency_group:str|None=None

@dataclass(frozen=True)
class EvidenceConflict:
    conflict_id:str;factor_a:str;factor_b:str;severity:ConflictSeverity
    description_code:str;penalty:float;resolution_policy:str

@dataclass(frozen=True)
class ScoringConfiguration:
    configuration_snapshot_id:str="SCORING_DEFAULT_RESEARCH"
    missing_optional_policy:MissingFactorPolicy=MissingFactorPolicy.RENORMALIZE_AVAILABLE_OPTIONAL
    missing_optional_penalty:float=5.0;minimum_completeness:float=50.0
    group_caps:tuple[tuple[str,float],...]=()
    conflict_penalties:tuple[tuple[str,float],...]=(("LOW",3.0),("MEDIUM",8.0),("HIGH",18.0),("CRITICAL",100.0))
    timeframe_weights:tuple[tuple[str,float],...]=(("CONTEXT",1.0),("STRATEGY",1.0),("EXECUTION",1.0))
    critical_conflict_invalidates:bool=True;maximum_cache_entries:int=256;maximum_history:int=256
    visible_precision:int=6
    def validate(self):
        errors=[]
        if not 0<=self.minimum_completeness<=100:errors.append("INVALID_MINIMUM_COMPLETENESS")
        if self.missing_optional_penalty<0:errors.append("NEGATIVE_MISSING_PENALTY")
        if min(self.maximum_cache_entries,self.maximum_history)<1:errors.append("INVALID_BOUND")
        if self.visible_precision<0 or self.visible_precision>12:errors.append("INVALID_PRECISION")
        if any(value<0 or not isfinite(value) for _,value in (*self.group_caps,*self.conflict_penalties,*self.timeframe_weights)):errors.append("INVALID_CONFIG_VALUE")
        return tuple(errors)

@dataclass(frozen=True)
class ScoringModel:
    scoring_model_id:str;scoring_model_version:str;schema_version:str;configuration_hash:str
    strategy_family:StrategyFamily;factors:tuple[FactorDefinition,...]
    def validate(self):
        errors=[];ids=[factor.factor_id for factor in self.factors]
        if not self.scoring_model_id or not self.scoring_model_version:errors.append("INVALID_MODEL_IDENTITY")
        if len(ids)!=len(set(ids)):errors.append("DUPLICATE_FACTOR_ID")
        if any(factor.weight<0 or not isfinite(factor.weight) for factor in self.factors):errors.append("INVALID_WEIGHT")
        if not any(f.weight>0 and f.requirement is not FactorRequirement.NOT_APPLICABLE for f in self.factors):errors.append("ZERO_EFFECTIVE_MODEL")
        known=set(ids)
        if any(dep not in known for factor in self.factors for dep in factor.dependencies):errors.append("UNKNOWN_DEPENDENCY")
        if any(f.normalization.validate() for f in self.factors):errors.append("INVALID_NORMALIZATION")
        graph={f.factor_id:f.dependencies for f in self.factors};visiting=set();visited=set()
        def visit(node):
            if node in visiting:return False
            if node in visited:return True
            visiting.add(node)
            if not all(visit(dep) for dep in graph[node]):return False
            visiting.remove(node);visited.add(node);return True
        if not all(visit(node) for node in graph):errors.append("DEPENDENCY_CYCLE")
        return tuple(dict.fromkeys(errors))

class ScoringModelRegistry:
    def __init__(self):self._models={};self._family={}
    def register(self,model:ScoringModel):
        errors=model.validate()
        if errors:raise ValueError(";".join(errors))
        if model.scoring_model_id in self._models:raise ValueError("DUPLICATE_SCORING_MODEL_ID")
        self._models[model.scoring_model_id]=model;self._family[model.strategy_family]=model.scoring_model_id
    def get(self,model_id):return self._models[model_id]
    def resolve(self,family):return self.get(self._family.get(family,self._family.get(StrategyFamily.CUSTOM)))
    def all(self):return tuple(self._models[key] for key in sorted(self._models))

def normalize(value,configuration:NormalizationConfiguration,direction=1):
    if configuration.method is NormalizationMethod.CATEGORICAL:
        result=dict(configuration.categories).get(str(value),0.0)
        if configuration.direction*direction<0:result=100-result
        return max(0.0,min(100.0,result)) if configuration.clamp else result
    if isinstance(value,bool):value=100.0 if value else 0.0
    if not isinstance(value,(int,float)) or not isfinite(float(value)):raise ValueError("INVALID_FACTOR_VALUE")
    value=float(value);span=configuration.maximum-configuration.minimum
    method=configuration.method
    if method in (NormalizationMethod.LINEAR,NormalizationMethod.BOUNDED_LINEAR,NormalizationMethod.PERCENTILE_BASED):result=100*(value-configuration.minimum)/span
    elif method is NormalizationMethod.BOOLEAN:result=100.0 if value else 0.0
    elif method is NormalizationMethod.DISTANCE_FROM_TARGET:
        if configuration.target is None:raise ValueError("MISSING_NORMALIZATION_TARGET")
        result=100*(1-abs(value-configuration.target)/span)
    elif method is NormalizationMethod.PIECEWISE_LINEAR:
        target=configuration.target if configuration.target is not None else (configuration.minimum+configuration.maximum)/2
        result=100*(value-configuration.minimum)/(target-configuration.minimum) if value<=target else 100*(configuration.maximum-value)/(configuration.maximum-target)
    else:raise ValueError("UNSUPPORTED_NORMALIZATION")
    if configuration.direction*direction<0:result=100-result
    return max(0.0,min(100.0,result)) if configuration.clamp else result

def default_model(family=StrategyFamily.CUSTOM):
    contextual={StrategyFamily.TREND:(2,1,1),StrategyFamily.BREAKOUT:(1,2,3),StrategyFamily.MEAN_REVERSION:(1,2,1),StrategyFamily.CUSTOM:(1,1,1)}[family]
    definitions=(
      FactorDefinition("REGIME",FactorGroup.REGIME,3,FactorRequirement.MANDATORY,source_module="Prompt8"),
      FactorDefinition("STRUCTURE",FactorGroup.STRUCTURE,3,FactorRequirement.MANDATORY,source_module="Prompt6"),
      FactorDefinition("TREND",FactorGroup.TREND,contextual[0],FactorRequirement.OPTIONAL,source_module="Prompt7/8"),
      FactorDefinition("MOMENTUM",FactorGroup.MOMENTUM,contextual[1],FactorRequirement.OPTIONAL,source_module="Prompt7"),
      FactorDefinition("VOLATILITY",FactorGroup.VOLATILITY,contextual[2],FactorRequirement.OPTIONAL,source_module="Prompt7"),
      FactorDefinition("SETUP_QUALITY",FactorGroup.SETUP_QUALITY,2,FactorRequirement.OPTIONAL,source_module="Prompt11"),
      FactorDefinition("SESSION",FactorGroup.SESSION,1,FactorRequirement.MANDATORY,source_module="Prompt9"),
      FactorDefinition("NEWS_CONTEXT",FactorGroup.NEWS_CONTEXT,1,FactorRequirement.MANDATORY,source_module="Prompt10"),
      FactorDefinition("SPREAD_QUALITY",FactorGroup.SPREAD_QUALITY,0,FactorRequirement.OPTIONAL,source_module="Prompt5"),
      FactorDefinition("RISK_REWARD",FactorGroup.RISK_REWARD,0,FactorRequirement.NOT_APPLICABLE,source_module="FUTURE_RISK_OWNER"),
      FactorDefinition("CORRELATION",FactorGroup.CORRELATION,0,FactorRequirement.NOT_APPLICABLE,source_module="PHASE_V"),)
    return ScoringModel(f"AMRTE_{family.name}_RESEARCH_SCORE","1.0",SCORING_SCHEMA_VERSION,deterministic_id("scoring_config",family.name,"research_defaults"),family,definitions)

class CentralSignalScorer:
    def __init__(self,registry:ScoringModelRegistry|None=None,configuration:ScoringConfiguration|None=None,audit=None,strategy_families:Mapping[str,StrategyFamily]|None=None):
        self.registry=registry or ScoringModelRegistry();self.configuration=configuration or ScoringConfiguration();self.audit=audit;self.strategy_families=dict(strategy_families or {})
        errors=self.configuration.validate()
        if errors:raise ValueError(";".join(errors))
        if not self.registry.all():
            for family in StrategyFamily:self.registry.register(default_model(family))
        self._cache=OrderedDict();self._history=[];self.cache_hits=0;self.cache_misses=0
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
    def _factor_value(self,definition,context,detection):
        intel=context.market_intelligence
        if definition.group in (FactorGroup.RISK_REWARD,FactorGroup.CORRELATION):return None,FactorAvailability.NOT_APPLICABLE,FactorHealth.UNAVAILABLE,("DEFERRED_BY_DESIGN",)
        evidence=[e for e in detection.evidence if e.availability is EvidenceAvailability.AVAILABLE and e.strength is not None]
        if definition.group is FactorGroup.SETUP_QUALITY:
            if not evidence:return None,FactorAvailability.UNAVAILABLE,FactorHealth.UNAVAILABLE,("OPTIONAL_FACTOR_MISSING",)
            return fsum(float(e.strength) for e in evidence)/len(evidence),FactorAvailability.AVAILABLE,FactorHealth.VALID,("SETUP_QUALITY_SUPPORT",)
        if definition.group in (FactorGroup.TREND,FactorGroup.MOMENTUM,FactorGroup.VOLATILITY):
            names={definition.group.name}
            candidates=[e for e in evidence if any(name in e.evidence_type.upper() for name in names)]
            if not candidates:return None,FactorAvailability.UNAVAILABLE,FactorHealth.UNAVAILABLE,(f"{definition.group.name}_EVIDENCE_UNAVAILABLE",)
            return fsum(float(e.strength) for e in candidates)/len(candidates),FactorAvailability.AVAILABLE,FactorHealth.VALID,(f"{definition.group.name}_SUPPORT",)
        if definition.group is FactorGroup.REGIME:
            raw=getattr(getattr(intel.regime,"confidence",None),"score",None)
            raw=raw if raw is not None else 80.0
            return raw,FactorAvailability.AVAILABLE,FactorHealth.VALID,("REGIME_SUPPORT",)
        if definition.group is FactorGroup.STRUCTURE:
            raw=getattr(getattr(intel.structure,"overall_confidence",None),"score",None)
            raw=raw if raw is not None else 75.0
            return raw,FactorAvailability.AVAILABLE,FactorHealth.VALID,("STRUCTURE_SUPPORT",)
        if definition.group is FactorGroup.SESSION:
            allowed=getattr(intel.session,"temporal_restriction",None).name=="ALLOW_CONTEXT"
            return 100.0 if allowed else 50.0,FactorAvailability.AVAILABLE,FactorHealth.VALID,("SESSION_SUPPORT" if allowed else "SESSION_RESTRICTION",)
        if definition.group is FactorGroup.NEWS_CONTEXT:
            allowed=getattr(intel.news_risk,"policy_state",None).name=="ALLOW_CONTEXT"
            return 100.0 if allowed else 40.0,FactorAvailability.AVAILABLE,FactorHealth.VALID,("NEWS_CONTEXT_SUPPORT" if allowed else "NEWS_RESTRICTION",)
        return None,FactorAvailability.UNAVAILABLE,FactorHealth.UNAVAILABLE,("OPTIONAL_FACTOR_MISSING",)
    def score(self,context:StrategyEvaluationContext,detection:DetectionResult,qualification:QualificationResult):
        family=self.strategy_families.get(context.strategy_id,StrategyFamily.CUSTOM);model=self.registry.resolve(family)
        key=(context.evaluation_id,model.scoring_model_id,model.scoring_model_version,self.configuration.configuration_snapshot_id,context.market_intelligence.market_intelligence_snapshot_id)
        if key in self._cache:self.cache_hits+=1;self._cache.move_to_end(key);return self._cache[key]
        self.cache_misses+=1;self._record("scoring_started",{"evaluation_id":context.evaluation_id,"model_id":model.scoring_model_id})
        if qualification.status not in (QualificationState.QUALIFIED,QualificationState.CONDITIONALLY_QUALIFIED):return self._unavailable(context,model,"HARD_QUALIFICATION_FAILURE")
        factors=[];mandatory_missing=[];optional_missing=[];role_weights=dict(self.configuration.timeframe_weights)
        for definition in model.factors:
            raw,availability,health,reasons=self._factor_value(definition,context,detection)
            normalized=None if raw is None else normalize(raw,definition.normalization)
            if availability in (FactorAvailability.UNAVAILABLE,FactorAvailability.UNKNOWN):
                (mandatory_missing if definition.requirement is FactorRequirement.MANDATORY else optional_missing).append(definition.factor_id)
            effective_weight=definition.weight*role_weights.get(definition.timeframe_role,1.0)
            contribution=0.0 if normalized is None else normalized*effective_weight
            factors.append(ScoringFactor(definition.factor_id,definition.factor_id,definition.group,definition.source_module,context.market_intelligence.market_intelligence_snapshot_id,raw,normalized,effective_weight,availability,health,DirectionalRelation.SUPPORTS if normalized is not None and normalized>=50 else DirectionalRelation.NEUTRAL,contribution,normalized or 0.0,reasons,definition.timeframe_role,definition.dependency_group))
        if mandatory_missing:return self._unavailable(context,model,"MANDATORY_FACTOR_MISSING",tuple(factors),tuple(mandatory_missing))
        available=[f for f in factors if f.availability in (FactorAvailability.AVAILABLE,FactorAvailability.DEGRADED) and f.weight>0]
        denominator=fsum(f.weight for f in available)
        if denominator<=0:return self._unavailable(context,model,"ZERO_EFFECTIVE_MODEL",tuple(factors))
        caps={name:value for name,value in self.configuration.group_caps};group_values={};positive=0.0
        for group in sorted({f.factor_group for f in available},key=lambda g:g.name):
            members=[f for f in available if f.factor_group is group];weighted=fsum(f.normalized_value*f.weight for f in members);weight=fsum(f.weight for f in members)
            contribution=weighted/weight;cap=caps.get(group.name)
            if cap is not None:contribution=min(contribution,cap)
            group_values[group.name]=contribution;positive+=contribution*weight
        base=positive/denominator
        missing_penalty=self.configuration.missing_optional_penalty*len(optional_missing) if self.configuration.missing_optional_policy is MissingFactorPolicy.PENALIZE_MISSING_OPTIONAL else 0.0
        conflicts=[]
        for index,item in enumerate(detection.conflicting_evidence):
            severity=ConflictSeverity.HIGH if (item.strength or 0)>=75 else ConflictSeverity.MEDIUM
            penalty=dict(self.configuration.conflict_penalties).get(severity.name,8.0)
            conflicts.append(EvidenceConflict(deterministic_id("evidence_conflict",item.evidence_id,index),item.evidence_id,"CANDIDATE_HYPOTHESIS",severity,"EVIDENCE_DIRECTION_CONFLICT",penalty,"SUBTRACT"))
        conflict_penalty=min(100.0,fsum(c.penalty for c in conflicts));critical=any(c.severity is ConflictSeverity.CRITICAL for c in conflicts)
        if critical and self.configuration.critical_conflict_invalidates:return self._unavailable(context,model,"CRITICAL_CONFLICT",tuple(factors))
        expected=sum(1 for f in model.factors if f.requirement is not FactorRequirement.NOT_APPLICABLE)
        completeness=100*(expected-len(mandatory_missing)-len(optional_missing))/max(1,expected)
        support_values=[f.normalized_value for f in available if f.normalized_value is not None]
        agreement=max(0.0,100.0-(max(support_values)-min(support_values) if support_values else 100.0)-conflict_penalty)
        uncertainty=min(100.0,100.0-completeness+conflict_penalty+(10 if any(f.availability is FactorAvailability.DEGRADED for f in factors) else 0))
        confidence=max(0.0,min(100.0,(base+agreement)/2-uncertainty*.25))
        quality=max(0.0,min(100.0,base-conflict_penalty*.5-missing_penalty))
        overall=max(0.0,min(100.0,fsum((confidence*.4,quality*.4,completeness*.2))-conflict_penalty*.5-missing_penalty))
        health=ScoreHealth.DEGRADED if optional_missing or completeness<100 else ScoreHealth.VALID
        if completeness<self.configuration.minimum_completeness:health=ScoreHealth.INCOMPLETE;overall=0.0
        precision=self.configuration.visible_precision
        component={"confidence":confidence,"quality":quality,"completeness":completeness,"agreement":agreement,"uncertainty":uncertainty}
        logical=deterministic_id("logical_score",context.evaluation_id,model.scoring_model_id,context.instrument_id)
        version=deterministic_id("score_version",logical,model.scoring_model_version,self.configuration.configuration_snapshot_id,context.market_intelligence.market_intelligence_snapshot_id,*(f.factor_id+":"+str(f.normalized_value) for f in factors))
        identity=deterministic_id("signal_score",version)
        supporting=tuple(code for f in factors for code in f.reason_codes if "SUPPORT" in code)
        missing=tuple(f"{name}:OPTIONAL_FACTOR_MISSING" for name in optional_missing)
        result=SignalScore(identity,round(overall,precision),{k:round(v,precision) for k,v in component.items()},round(confidence,precision),round(quality,precision),round(completeness,precision),round(conflict_penalty,precision),round(missing_penalty,precision),health,
          ("SCORE_IS_RESEARCH_QUALITY_NOT_PROFIT_PROBABILITY","HIGH_SCORE_IS_NOT_AUTHORIZATION"),round(agreement,precision),round(uncertainty,precision),round(positive/denominator,precision),tuple(factors),{k:round(v,precision) for k,v in group_values.items()},tuple(conflicts),supporting,tuple(c.description_code for c in conflicts),missing,("RISK_REWARD_DEFERRED_BY_DESIGN","CORRELATION_DEFERRED_BY_DESIGN"),model.scoring_model_id,model.scoring_model_version,self.configuration.configuration_snapshot_id,context.market_intelligence.market_intelligence_snapshot_id,logical,version,context.recovery_epoch)
        self._cache[key]=result;self._cache.move_to_end(key)
        while len(self._cache)>self.configuration.maximum_cache_entries:self._cache.popitem(last=False)
        self._history.append(result);self._history=self._history[-self.configuration.maximum_history:]
        self._record("scoring_completed",{"score_id":identity,"health":health.name,"overall":result.overall_score});return result
    def _unavailable(self,context,model,reason,factors=(),missing=()):
        logical=deterministic_id("logical_score",context.evaluation_id,model.scoring_model_id,context.instrument_id);version=deterministic_id("score_version",logical,reason,self.configuration.configuration_snapshot_id)
        result=SignalScore(deterministic_id("signal_score",version),0.0,{},0.0,0.0,0.0,0.0,0.0,ScoreHealth.UNAVAILABLE,(reason,"HIGH_SCORE_IS_NOT_AUTHORIZATION"),0.0,100.0,0.0,factors,{},(),(),(),missing,(),model.scoring_model_id,model.scoring_model_version,self.configuration.configuration_snapshot_id,context.market_intelligence.market_intelligence_snapshot_id,logical,version,context.recovery_epoch)
        self._record("score_unavailable",{"reason":reason,"evaluation_id":context.evaluation_id});return result
    @property
    def history(self):return tuple(self._history)
    @property
    def cache_size(self):return len(self._cache)
    def recovery_state(self):
        latest=self._history[-1] if self._history else None
        return {"engine_version":SCORING_ENGINE_VERSION,"configuration_snapshot_id":self.configuration.configuration_snapshot_id,"last_score_version_id":latest.score_version_id if latest else None,"bounded_score_references":tuple(s.score_version_id for s in self._history)}
    def validate_recovery(self,state):return state.get("engine_version")==SCORING_ENGINE_VERSION and state.get("configuration_snapshot_id")==self.configuration.configuration_snapshot_id
