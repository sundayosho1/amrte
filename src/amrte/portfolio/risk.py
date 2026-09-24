"""Aggregate capacity accounting for fictional research exposure only."""
from __future__ import annotations
from collections import OrderedDict,defaultdict
from dataclasses import dataclass,replace
from datetime import datetime,timedelta
from decimal import Decimal,ROUND_FLOOR,localcontext
from enum import Enum,auto

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation,DecisionOutcome,DecisionStatus,DecisionTrace
from amrte.risk.sizing import _decimal
from amrte.risk.invalidation import ResearchDirection
from amrte.risk.exit_management import ExitManagementState
from amrte.risk.protection import ProtectiveManagementState

PORTFOLIO_ENGINE_VERSION="1.0";ZERO=Decimal("0")

class ExposureStatus(Enum):PROPOSED=auto();RESERVED=auto();ACTIVE=auto();PARTIALLY_REDUCED=auto();PROTECTED=auto();EXIT_PENDING=auto();CLOSED=auto();RELEASED=auto();BLOCKED=auto();INVALID=auto();UNKNOWN=auto()
class ReservationStatus(Enum):REQUESTED=auto();RESERVED=auto();COMMITTED=auto();RELEASED=auto();EXPIRED=auto();REJECTED=auto();INVALID=auto();UNKNOWN=auto()
class AdmissionOutcome(Enum):ALLOW_FULL=auto();ALLOW_REDUCED=auto();BLOCK=auto();NO_ACTION=auto();INVALID=auto();UNKNOWN=auto()
class ReductionPolicy(Enum):BLOCK_IF_INSUFFICIENT=auto();REDUCE_TO_CAPACITY=auto()
class PortfolioHealth(Enum):HEALTHY=auto();DEGRADED=auto();RESTRICTED=auto();AT_LIMIT=auto();OVER_LIMIT=auto();INCOMPLETE=auto();RECONCILING=auto();INVALID=auto();UNKNOWN=auto()
class BindingConstraint(Enum):GLOBAL_RISK=auto();GROSS_EXPOSURE=auto();DIRECTIONAL=auto();INSTRUMENT=auto();FACTOR=auto();STRATEGY=auto();STRATEGY_FAMILY=auto();STRATEGY_VARIANT=auto();CONCURRENT_HYPOTHESES=auto();HEALTH=auto();DATA=auto();UNKNOWN=auto();NONE=auto()
class LimitDimension(Enum):GLOBAL_RISK=auto();GROSS_EXPOSURE=auto();BULLISH_EXPOSURE=auto();BEARISH_EXPOSURE=auto();DIRECTIONAL_IMBALANCE=auto();INSTRUMENT_RISK=auto();INSTRUMENT_EXPOSURE=auto();FACTOR_RISK=auto();FACTOR_GROSS_EXPOSURE=auto();FACTOR_NET_EXPOSURE=auto();STRATEGY_RISK=auto();STRATEGY_EXPOSURE=auto();FAMILY_RISK=auto();FAMILY_EXPOSURE=auto();VARIANT_RISK=auto();VARIANT_EXPOSURE=auto();CONCURRENT_HYPOTHESES=auto()

@dataclass(frozen=True)
class FactorLeg:
    factor_id:str;sign:Decimal

@dataclass(frozen=True)
class InstrumentFactorMapping:
    instrument_id:str;legs:tuple[FactorLeg,...];mapping_version:str;available_at_utc:datetime;dataset_id:str

class DeterministicExposureDecomposer:
    def __init__(self,mappings=()):self._mappings={x.instrument_id:x for x in mappings}
    def decompose(self,instrument_id,direction,exposure,as_of,dataset_id):
        item=self._mappings.get(instrument_id)
        if not item or item.available_at_utc>as_of or item.dataset_id!=dataset_id:return None
        direction_sign=Decimal("1") if direction is ResearchDirection.BULLISH else Decimal("-1")
        return tuple((x.factor_id,_decimal(exposure)*x.sign*direction_sign) for x in item.legs)

@dataclass(frozen=True)
class PortfolioLimit:
    limit_id:str;dimension:LimitDimension;scope_key:str;maximum:Decimal;soft_threshold:Decimal|None;hard_limit:bool;configuration_snapshot_id:str

@dataclass(frozen=True)
class PortfolioConfiguration:
    portfolio_id:str="AMRTE_FICTIONAL_PORTFOLIO";enabled:bool=True;reduction_policy:ReductionPolicy=ReductionPolicy.BLOCK_IF_INSUFFICIENT
    require_complete_state:bool=True;require_reservation:bool=True;require_factor_decomposition:bool=True
    maximum_research_risk:Decimal=Decimal("1000");maximum_gross_exposure:Decimal=Decimal("1000");soft_risk_threshold:Decimal=Decimal("800");soft_gross_threshold:Decimal=Decimal("800")
    maximum_concurrent_hypotheses:int=8;maximum_bullish_exposure:Decimal=Decimal("1000");maximum_bearish_exposure:Decimal=Decimal("1000");maximum_directional_imbalance:Decimal=Decimal("1000")
    maximum_instrument_risk:Decimal=Decimal("1000");maximum_instrument_exposure:Decimal=Decimal("1000");maximum_concurrent_per_instrument:int=8
    maximum_factor_gross:Decimal=Decimal("1000");maximum_factor_net:Decimal=Decimal("1000")
    maximum_strategy_risk:Decimal=Decimal("1000");maximum_strategy_exposure:Decimal=Decimal("1000");maximum_family_risk:Decimal=Decimal("1000");maximum_family_exposure:Decimal=Decimal("1000");maximum_variant_risk:Decimal=Decimal("1000");maximum_variant_exposure:Decimal=Decimal("1000")
    minimum_exposure:Decimal=Decimal("0.01");exposure_step:Decimal=Decimal("0.01");reservation_ttl_seconds:int=300;tolerance:Decimal=Decimal("0.00000001");precision:int=28
    maximum_records:int=512;maximum_reservations:int=512;maximum_snapshots:int=512;maximum_ledger_events:int=1024;maximum_cache_entries:int=256;configuration_snapshot_id:str="PORTFOLIO_DEFAULT_RESEARCH"
    def validate(self):
        errors=[];values=(self.maximum_research_risk,self.maximum_gross_exposure,self.soft_risk_threshold,self.soft_gross_threshold,self.maximum_bullish_exposure,self.maximum_bearish_exposure,self.maximum_directional_imbalance,self.maximum_instrument_risk,self.maximum_instrument_exposure,self.maximum_factor_gross,self.maximum_factor_net,self.maximum_strategy_risk,self.maximum_strategy_exposure,self.maximum_family_risk,self.maximum_family_exposure,self.maximum_variant_risk,self.maximum_variant_exposure,self.minimum_exposure,self.exposure_step,self.tolerance)
        try:
            converted=tuple(_decimal(x) for x in values)
            if any(not x.is_finite() or x<0 for x in converted):errors.append("PORTFOLIO_LIMIT_INVALID")
            if self.exposure_step<=0 or self.soft_risk_threshold>self.maximum_research_risk or self.soft_gross_threshold>self.maximum_gross_exposure:errors.append("PORTFOLIO_THRESHOLD_INVALID")
        except (ValueError,ArithmeticError):errors.append("PORTFOLIO_NUMERICAL_INVALID")
        if self.maximum_concurrent_hypotheses<1 or self.maximum_concurrent_per_instrument<1 or self.reservation_ttl_seconds<1:errors.append("PORTFOLIO_CONFIGURATION_INVALID")
        if min(self.maximum_records,self.maximum_reservations,self.maximum_snapshots,self.maximum_ledger_events,self.maximum_cache_entries)<1:errors.append("PORTFOLIO_BOUND_INVALID")
        return tuple(dict.fromkeys(errors))

@dataclass(frozen=True)
class PortfolioAdmissionRequest:
    request_id:str;strategy_decision_snapshot_id:str;prompt17_sizing_decision_id:str;prompt18_adaptive_risk_decision_id:str;prompt19_invalidation_id:str;strategy_id:str;strategy_version:str;strategy_family:str;strategy_variant:str|None;instrument_id:str;direction:ResearchDirection;dataset_id:str;factors:tuple[str,...];proposed_exposure:Decimal;proposed_risk:Decimal;as_of_timestamp_utc:datetime;configuration_snapshot_id:str;recovery_epoch:int;regime:str|None=None
    @classmethod
    def create(cls,strategy_decision_snapshot_id,p17_id,p18_id,p19_id,strategy_id,strategy_version,strategy_family,strategy_variant,instrument_id,direction,dataset_id,factors,proposed_exposure,proposed_risk,as_of,configuration_snapshot_id="PORTFOLIO_DEFAULT_RESEARCH",recovery_epoch=0,regime=None):
        exposure=_decimal(proposed_exposure);risk=_decimal(proposed_risk);rid=deterministic_id("portfolio_admission_request",strategy_decision_snapshot_id,p17_id,p18_id,p19_id,strategy_id,strategy_version,strategy_family,strategy_variant or "NONE",instrument_id,direction.name,dataset_id,*sorted(factors),str(exposure),str(risk),as_of.isoformat(),configuration_snapshot_id,recovery_epoch)
        return cls(rid,strategy_decision_snapshot_id,p17_id,p18_id,p19_id,strategy_id,strategy_version,strategy_family,strategy_variant,instrument_id,direction,dataset_id,tuple(sorted(factors)),exposure,risk,as_of,configuration_snapshot_id,recovery_epoch,regime)

@dataclass(frozen=True)
class PortfolioCapacityReservation:
    reservation_id:str;request_id:str;portfolio_snapshot_id:str;reserved_exposure:Decimal;reserved_risk:Decimal;status:ReservationStatus;created_at_utc:datetime;expires_at_utc:datetime;updated_at_utc:datetime;configuration_snapshot_id:str;recovery_epoch:int

@dataclass(frozen=True)
class PortfolioExposureRecord:
    exposure_record_id:str;exposure_version_id:str;strategy_decision_snapshot_id:str;research_signal_id:str;strategy_id:str;strategy_version:str;strategy_family:str;strategy_variant:str|None;instrument_id:str;direction:ResearchDirection;regime:str|None;prompt19_invalidation_id:str;prompt17_sizing_decision_id:str;prompt18_adaptive_risk_decision_id:str;prompt20_exit_state_id:str|None;prompt21_protective_state_id:str|None;initial_approved_exposure:Decimal;remaining_exposure:Decimal;original_risk:Decimal;current_risk:Decimal;underlying_factors:tuple[str,...];dataset_id:str;opened_at_utc:datetime;updated_at_utc:datetime;status:ExposureStatus;configuration_snapshot_id:str;recovery_epoch:int

@dataclass(frozen=True)
class FactorExposure:
    factor_id:str;long_exposure:Decimal;short_exposure:Decimal;gross_exposure:Decimal;net_exposure:Decimal

@dataclass(frozen=True)
class PortfolioRiskSnapshot:
    snapshot_id:str;portfolio_id:str;active_exposure_record_ids:tuple[str,...];reservation_ids:tuple[str,...];total_open_research_risk:Decimal;reserved_research_risk:Decimal;gross_exposure:Decimal;net_directional_exposure:Decimal;bullish_exposure:Decimal;bearish_exposure:Decimal;instrument_exposure:tuple[tuple[str,Decimal],...];factor_exposure:tuple[FactorExposure,...];strategy_exposure:tuple[tuple[str,Decimal],...];strategy_family_exposure:tuple[tuple[str,Decimal],...];strategy_variant_exposure:tuple[tuple[str,Decimal],...];regime_exposure:tuple[tuple[str,Decimal],...];concurrent_hypothesis_count:int;available_risk_capacity:Decimal;available_gross_capacity:Decimal;health:PortfolioHealth;restrictions:tuple[str,...];as_of_timestamp_utc:datetime;configuration_snapshot_id:str;engine_version:str;recovery_epoch:int

@dataclass(frozen=True)
class PortfolioRiskDecision:
    decision_id:str;request_id:str;portfolio_snapshot_id:str;reservation_id:str|None;proposed_exposure:Decimal;proposed_risk:Decimal;approved_exposure:Decimal;approved_risk:Decimal;outcome:AdmissionOutcome;global_capacity:Decimal;direction_capacity:Decimal;instrument_capacity:Decimal;factor_capacities:tuple[tuple[str,Decimal],...];strategy_capacity:Decimal;family_capacity:Decimal;variant_capacity:Decimal;binding_constraint:BindingConstraint;reduction_applied:bool;restrictions:tuple[str,...];reason_codes:tuple[str,...];as_of_timestamp_utc:datetime;configuration_snapshot_id:str;engine_version:str;recovery_epoch:int;decision_trace:DecisionTrace

@dataclass(frozen=True)
class PortfolioLedgerEvent:
    event_id:str;event_type:str;source_id:str;effective_at_utc:datetime;reason_codes:tuple[str,...]

class PortfolioRiskLedger:
    def __init__(self,maximum_events=1024):self.maximum_events=maximum_events;self.events=OrderedDict()
    def add(self,event):self.events.setdefault(event.event_id,event);self._bound()
    def _bound(self):
        while len(self.events)>self.maximum_events:self.events.popitem(last=False)
    def snapshot(self):return {"maximum_events":self.maximum_events,"events":tuple(self.events.values())}
    def restore(self,data):
        if data.get("maximum_events")!=self.maximum_events:return False
        events=tuple(data.get("events",()));self.events=OrderedDict((x.event_id,x) for x in events);return len(self.events)==len(events)

class PortfolioExposureRegistry:
    def __init__(self,configuration=PortfolioConfiguration(),decomposer=None,audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.decomposer=decomposer or DeterministicExposureDecomposer();self.audit=audit;self.records=OrderedDict();self.record_versions=OrderedDict();self.reservations=OrderedDict();self.snapshots=OrderedDict();self.decisions=OrderedDict();self.ledger=PortfolioRiskLedger(configuration.maximum_ledger_events);self._cache=OrderedDict();self.complete=True
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)
    def snapshot(self,as_of,recovery_epoch=0):
        cfg=self.configuration;historical={}
        for item in self.record_versions.values():
            if item.updated_at_utc<=as_of and (item.exposure_record_id not in historical or historical[item.exposure_record_id].updated_at_utc<=item.updated_at_utc):historical[item.exposure_record_id]=item
        active=tuple(sorted((x for x in historical.values() if x.status in (ExposureStatus.ACTIVE,ExposureStatus.PARTIALLY_REDUCED,ExposureStatus.PROTECTED) and x.remaining_exposure>0),key=lambda x:x.exposure_record_id));reserved=tuple(sorted((x for x in self.reservations.values() if x.status is ReservationStatus.RESERVED and x.created_at_utc<=as_of and x.expires_at_utc>as_of),key=lambda x:x.reservation_id))
        risk=sum((x.current_risk for x in active),ZERO);reserved_risk=sum((x.reserved_risk for x in reserved),ZERO);bull=sum((x.remaining_exposure for x in active if x.direction is ResearchDirection.BULLISH),ZERO);bear=sum((x.remaining_exposure for x in active if x.direction is ResearchDirection.BEARISH),ZERO);gross=bull+bear;net=bull-bear
        instrument=self._group(active,"instrument_id");strategy=self._group(active,"strategy_id");family=self._group(active,"strategy_family");variant=self._group(active,"strategy_variant",empty="NONE");regime=self._group(active,"regime",empty="UNKNOWN");factor=self._factors(active,as_of)
        restrictions=[]
        if not self.complete or (cfg.require_factor_decomposition and factor is None):restrictions.append("PORTFOLIO_STATE_INCOMPLETE")
        health=PortfolioHealth.INCOMPLETE if restrictions else PortfolioHealth.HEALTHY
        if risk+reserved_risk>cfg.maximum_research_risk+cfg.tolerance or gross+sum((x.reserved_exposure for x in reserved),ZERO)>cfg.maximum_gross_exposure+cfg.tolerance:health=PortfolioHealth.OVER_LIMIT;restrictions.append("PORTFOLIO_OVER_LIMIT")
        available_risk=max(ZERO,cfg.maximum_research_risk-risk-reserved_risk);available_gross=max(ZERO,cfg.maximum_gross_exposure-gross-sum((x.reserved_exposure for x in reserved),ZERO))
        if health is PortfolioHealth.HEALTHY and (available_risk<=cfg.tolerance or available_gross<=cfg.tolerance):health=PortfolioHealth.AT_LIMIT
        fid=tuple(factor or ());sid=deterministic_id("portfolio_risk_snapshot",cfg.portfolio_id,*(x.exposure_version_id for x in active),*(x.reservation_id for x in reserved),str(risk),str(gross),str(net),str(available_risk),as_of.isoformat(),cfg.configuration_snapshot_id,PORTFOLIO_ENGINE_VERSION,recovery_epoch)
        result=PortfolioRiskSnapshot(sid,cfg.portfolio_id,tuple(x.exposure_record_id for x in active),tuple(x.reservation_id for x in reserved),risk,reserved_risk,gross,net,bull,bear,instrument,fid,strategy,family,variant,regime,len(active),available_risk,available_gross,health,tuple(dict.fromkeys(restrictions)),as_of,cfg.configuration_snapshot_id,PORTFOLIO_ENGINE_VERSION,recovery_epoch)
        self.snapshots[sid]=result;self._bound();return result
    def assess(self,request:PortfolioAdmissionRequest,as_of=None):
        cfg=self.configuration;as_of=as_of or request.as_of_timestamp_utc;snap=self.snapshot(as_of,request.recovery_epoch);hard=[]
        if not cfg.enabled:hard.append((BindingConstraint.HEALTH,"PORTFOLIO_DISABLED",ZERO))
        if request.configuration_snapshot_id!=cfg.configuration_snapshot_id or request.as_of_timestamp_utc>as_of:hard.append((BindingConstraint.DATA,"PORTFOLIO_LINEAGE_MISMATCH",ZERO))
        try:
            proposed_e=_decimal(request.proposed_exposure);proposed_r=_decimal(request.proposed_risk)
            if not proposed_e.is_finite() or not proposed_r.is_finite() or proposed_e<=0 or proposed_r<0:hard.append((BindingConstraint.DATA,"PORTFOLIO_REQUEST_INVALID",ZERO))
        except ValueError:proposed_e=proposed_r=ZERO;hard.append((BindingConstraint.DATA,"PORTFOLIO_REQUEST_INVALID",ZERO))
        if snap.health in (PortfolioHealth.INCOMPLETE,PortfolioHealth.INVALID,PortfolioHealth.UNKNOWN,PortfolioHealth.OVER_LIMIT):hard.append((BindingConstraint.HEALTH,"PORTFOLIO_STATE_UNAVAILABLE",ZERO))
        if cfg.require_factor_decomposition and self.decomposer.decompose(request.instrument_id,request.direction,proposed_e,as_of,request.dataset_id) is None:hard.append((BindingConstraint.DATA,"PORTFOLIO_FACTOR_MAPPING_MISSING",ZERO))
        capacities=self._capacities(snap,request,as_of);allowed=min((x[2] for x in capacities),default=ZERO);binding=min(capacities,key=lambda x:(x[2],x[0].value)) if capacities else (BindingConstraint.UNKNOWN,"PORTFOLIO_UNKNOWN",ZERO)
        if snap.concurrent_hypothesis_count+len(snap.reservation_ids)>=cfg.maximum_concurrent_hypotheses:hard.append((BindingConstraint.CONCURRENT_HYPOTHESES,"PORTFOLIO_CONCURRENCY_LIMIT",ZERO))
        duplicate=next((x for x in self.records.values() if x.strategy_decision_snapshot_id==request.strategy_decision_snapshot_id and x.status not in (ExposureStatus.CLOSED,ExposureStatus.RELEASED)),None)
        if duplicate:hard.append((BindingConstraint.DATA,"PORTFOLIO_DUPLICATE_ADMISSION",ZERO))
        approved_e=proposed_e;approved_r=proposed_r;outcome=AdmissionOutcome.ALLOW_FULL;reduction=False
        risk_per_exposure=(proposed_r/proposed_e) if proposed_e>0 else ZERO
        if hard:approved_e=approved_r=ZERO;outcome=AdmissionOutcome.BLOCK;binding=hard[0]
        elif allowed+cfg.tolerance<proposed_e:
            if cfg.reduction_policy is ReductionPolicy.REDUCE_TO_CAPACITY:
                approved_e=self._floor(allowed);approved_r=min(proposed_r,approved_e*risk_per_exposure)
                if approved_e<cfg.minimum_exposure:approved_e=approved_r=ZERO;outcome=AdmissionOutcome.BLOCK
                else:outcome=AdmissionOutcome.ALLOW_REDUCED;reduction=True
            else:approved_e=approved_r=ZERO;outcome=AdmissionOutcome.BLOCK
        reservation=None
        if outcome in (AdmissionOutcome.ALLOW_FULL,AdmissionOutcome.ALLOW_REDUCED) and cfg.require_reservation:
            reservation=self._reserve(request,snap,approved_e,approved_r,as_of)
            if reservation is None:approved_e=approved_r=ZERO;outcome=AdmissionOutcome.BLOCK;binding=(BindingConstraint.GLOBAL_RISK,"PORTFOLIO_RESERVATION_CONFLICT",ZERO)
        reasons=("PORTFOLIO_ALLOW_FULL",) if outcome is AdmissionOutcome.ALLOW_FULL else ("PORTFOLIO_ALLOW_REDUCED",) if outcome is AdmissionOutcome.ALLOW_REDUCED else (hard[0][1] if hard else binding[1],"PORTFOLIO_BLOCK")
        did=deterministic_id("portfolio_risk_decision",request.request_id,snap.snapshot_id,reservation.reservation_id if reservation else "NONE",outcome.name,str(approved_e),str(approved_r),binding[0].name,cfg.configuration_snapshot_id)
        status=DecisionStatus.PASSED if outcome in (AdmissionOutcome.ALLOW_FULL,AdmissionOutcome.ALLOW_REDUCED) else DecisionStatus.FAILED;checks=(DecisionEvaluation("PORTFOLIO_STATE",status,reasons[0],"Aggregate committed and reserved capacity reconstructed",(snap.snapshot_id,)),DecisionEvaluation("PORTFOLIO_LIMITS",status,reasons[-1],"Every applicable hard limit and reservation evaluated",tuple(x[0].name for x in capacities)))
        trace=DecisionTrace(did,request.strategy_decision_snapshot_id,as_of,checks,DecisionOutcome.ACCEPTED if status is DecisionStatus.PASSED else DecisionOutcome.NO_ACTION,reasons[-1],as_of,"PORTFOLIO_STATE" if status is DecisionStatus.FAILED else None)
        factor_caps=tuple((x[1].split(":",1)[-1],x[2]) for x in capacities if x[0] is BindingConstraint.FACTOR);decision=PortfolioRiskDecision(did,request.request_id,snap.snapshot_id,reservation.reservation_id if reservation else None,proposed_e,proposed_r,approved_e,approved_r,outcome,snap.available_risk_capacity,self._capacity_for(capacities,BindingConstraint.DIRECTIONAL),self._capacity_for(capacities,BindingConstraint.INSTRUMENT),factor_caps,self._capacity_for(capacities,BindingConstraint.STRATEGY),self._capacity_for(capacities,BindingConstraint.STRATEGY_FAMILY),self._capacity_for(capacities,BindingConstraint.STRATEGY_VARIANT),binding[0],reduction,tuple(snap.restrictions),tuple(reasons),as_of,cfg.configuration_snapshot_id,PORTFOLIO_ENGINE_VERSION,request.recovery_epoch,trace)
        self.decisions[did]=decision;self._event("CAPACITY_RESERVED" if reservation else "EXPOSURE_PROPOSED",reservation.reservation_id if reservation else request.request_id,as_of,reasons);self._record("portfolio_admission_assessed",{"decision_id":did,"outcome":outcome.name});self._bound();return decision
    def commit(self,decision:PortfolioRiskDecision,request:PortfolioAdmissionRequest,research_signal_id,as_of):
        if decision.outcome not in (AdmissionOutcome.ALLOW_FULL,AdmissionOutcome.ALLOW_REDUCED) or not decision.reservation_id:return None
        rid=deterministic_id("portfolio_exposure_record",self.configuration.portfolio_id,request.strategy_decision_snapshot_id,request.instrument_id,request.strategy_id,request.strategy_variant or "NONE")
        if rid in self.records:return self.records[rid]
        reservation=self.reservations.get(decision.reservation_id)
        if not reservation or reservation.status is not ReservationStatus.RESERVED or reservation.expires_at_utc<=as_of:return None
        vid=deterministic_id("portfolio_exposure_version",rid,decision.decision_id,str(decision.approved_exposure),str(decision.approved_risk),as_of.isoformat())
        record=PortfolioExposureRecord(rid,vid,request.strategy_decision_snapshot_id,research_signal_id,request.strategy_id,request.strategy_version,request.strategy_family,request.strategy_variant,request.instrument_id,request.direction,request.regime,request.prompt19_invalidation_id,request.prompt17_sizing_decision_id,request.prompt18_adaptive_risk_decision_id,None,None,decision.approved_exposure,decision.approved_exposure,decision.approved_risk,decision.approved_risk,request.factors,request.dataset_id,as_of,as_of,ExposureStatus.ACTIVE,self.configuration.configuration_snapshot_id,request.recovery_epoch)
        self.records[rid]=record;self.record_versions[vid]=record;self.reservations[reservation.reservation_id]=replace(reservation,status=ReservationStatus.COMMITTED,updated_at_utc=as_of);self._event("EXPOSURE_ADMITTED",rid,as_of,("PORTFOLIO_EXPOSURE_ADMITTED",));self._record("portfolio_exposure_admitted",{"exposure_record_id":rid});self._bound();return record
    def release(self,reservation_id,as_of,expired=False):
        item=self.reservations.get(reservation_id)
        if not item or item.status is not ReservationStatus.RESERVED:return False
        status=ReservationStatus.EXPIRED if expired else ReservationStatus.RELEASED;self.reservations[reservation_id]=replace(item,status=status,updated_at_utc=as_of);self._event("RESERVATION_EXPIRED" if expired else "RESERVATION_RELEASED",reservation_id,as_of,(f"PORTFOLIO_{status.name}",));return True
    def expire_reservations(self,as_of):
        return sum(1 for x in tuple(self.reservations.values()) if x.status is ReservationStatus.RESERVED and x.expires_at_utc<=as_of and self.release(x.reservation_id,as_of,True))
    def reconcile(self,record_id,exit_state:ExitManagementState,protective_state:ProtectiveManagementState|None,as_of,current_risk=None):
        item=self.records.get(record_id)
        if not item:return (False,("PORTFOLIO_MISSING_EXPOSURE",))
        if exit_state.as_of_timestamp_utc>as_of or (protective_state and protective_state.last_update_at_utc>as_of):return (False,("PORTFOLIO_FUTURE_STATE_REJECTED",))
        remaining=min(item.remaining_exposure,exit_state.remaining_exposure,protective_state.remaining_exposure if protective_state else exit_state.remaining_exposure);risk=item.current_risk if current_risk is None else min(item.current_risk,max(ZERO,_decimal(current_risk)))
        status=ExposureStatus.CLOSED if remaining==0 else ExposureStatus.PROTECTED if protective_state and protective_state.current_boundary_version_id else ExposureStatus.PARTIALLY_REDUCED if remaining<item.initial_approved_exposure else ExposureStatus.ACTIVE
        vid=deterministic_id("portfolio_exposure_version",item.exposure_record_id,item.exposure_version_id,exit_state.exit_plan_id,protective_state.current_boundary_version_id if protective_state else "NONE",str(remaining),str(risk),as_of.isoformat());new=replace(item,exposure_version_id=vid,prompt20_exit_state_id=exit_state.exit_plan_id,prompt21_protective_state_id=protective_state.current_boundary_version_id if protective_state else None,remaining_exposure=remaining,current_risk=risk,updated_at_utc=as_of,status=status)
        self.records[record_id]=new;self.record_versions[vid]=new;self._event("EXPOSURE_CLOSED" if status is ExposureStatus.CLOSED else "EXPOSURE_REDUCED",record_id,as_of,("PORTFOLIO_RECONCILED",));self._bound();return (True,("PORTFOLIO_RECONCILED",))
    def detect_inconsistencies(self,authoritative_active_ids):
        active={x.exposure_record_id for x in self.records.values() if x.status in (ExposureStatus.ACTIVE,ExposureStatus.PARTIALLY_REDUCED,ExposureStatus.PROTECTED)};authority=set(authoritative_active_ids);issues=[]
        if active-authority:issues.append("PORTFOLIO_GHOST_EXPOSURE")
        if authority-active:issues.append("PORTFOLIO_MISSING_EXPOSURE")
        if issues:self.complete=False
        return tuple(issues)
    def _capacities(self,snap,request,as_of):
        cfg=self.configuration;caps=[(BindingConstraint.GLOBAL_RISK,"GLOBAL_RISK",snap.available_risk_capacity),(BindingConstraint.GROSS_EXPOSURE,"GROSS_EXPOSURE",snap.available_gross_capacity)]
        direction_used=snap.bullish_exposure if request.direction is ResearchDirection.BULLISH else snap.bearish_exposure;direction_max=cfg.maximum_bullish_exposure if request.direction is ResearchDirection.BULLISH else cfg.maximum_bearish_exposure;caps.append((BindingConstraint.DIRECTIONAL,"DIRECTIONAL",max(ZERO,direction_max-direction_used)))
        inst=dict(snap.instrument_exposure).get(request.instrument_id,ZERO);caps.append((BindingConstraint.INSTRUMENT,f"INSTRUMENT:{request.instrument_id}",max(ZERO,cfg.maximum_instrument_exposure-inst)))
        strat=dict(snap.strategy_exposure).get(request.strategy_id,ZERO);fam=dict(snap.strategy_family_exposure).get(request.strategy_family,ZERO);variant=dict(snap.strategy_variant_exposure).get(request.strategy_variant or "NONE",ZERO);caps.extend(((BindingConstraint.STRATEGY,f"STRATEGY:{request.strategy_id}",max(ZERO,cfg.maximum_strategy_exposure-strat)),(BindingConstraint.STRATEGY_FAMILY,f"FAMILY:{request.strategy_family}",max(ZERO,cfg.maximum_family_exposure-fam)),(BindingConstraint.STRATEGY_VARIANT,f"VARIANT:{request.strategy_variant or 'NONE'}",max(ZERO,cfg.maximum_variant_exposure-variant))))
        factors={x.factor_id:x for x in snap.factor_exposure}
        for factor in request.factors:caps.append((BindingConstraint.FACTOR,f"FACTOR:{factor}",max(ZERO,cfg.maximum_factor_gross-(factors.get(factor).gross_exposure if factor in factors else ZERO))))
        return tuple(caps)
    def _reserve(self,request,snapshot,exposure,risk,as_of):
        existing=next((x for x in self.reservations.values() if x.request_id==request.request_id and x.status is ReservationStatus.RESERVED),None)
        if existing:return existing
        current=self.snapshot(as_of,request.recovery_epoch)
        if risk>current.available_risk_capacity+self.configuration.tolerance or exposure>current.available_gross_capacity+self.configuration.tolerance:return None
        rid=deterministic_id("portfolio_capacity_reservation",self.configuration.portfolio_id,request.request_id,snapshot.snapshot_id,str(exposure),str(risk),self.configuration.configuration_snapshot_id,request.recovery_epoch);item=PortfolioCapacityReservation(rid,request.request_id,snapshot.snapshot_id,exposure,risk,ReservationStatus.RESERVED,as_of,as_of+timedelta(seconds=self.configuration.reservation_ttl_seconds),as_of,self.configuration.configuration_snapshot_id,request.recovery_epoch);self.reservations[rid]=item;self._bound();return item
    def _factors(self,active,as_of):
        values=defaultdict(lambda:[ZERO,ZERO])
        for item in active:
            legs=self.decomposer.decompose(item.instrument_id,item.direction,item.remaining_exposure,as_of,item.dataset_id)
            if legs is None:return None
            for factor,value in legs:
                if value>=0:values[factor][0]+=value
                else:values[factor][1]+=abs(value)
        return tuple(FactorExposure(k,v[0],v[1],v[0]+v[1],v[0]-v[1]) for k,v in sorted(values.items()))
    def _group(self,records,attribute,empty=None):
        values=defaultdict(lambda:ZERO)
        for item in records:
            key=getattr(item,attribute) or empty
            if key is not None:values[key]+=item.remaining_exposure
        return tuple(sorted(values.items()))
    def _floor(self,value):
        step=self.configuration.exposure_step
        with localcontext() as ctx:ctx.prec=self.configuration.precision;return (_decimal(value)/step).to_integral_value(rounding=ROUND_FLOOR)*step
    def _capacity_for(self,capacities,dimension):return min((x[2] for x in capacities if x[0] is dimension),default=Decimal("Infinity"))
    def _event(self,event_type,source_id,at,reasons):
        eid=deterministic_id("portfolio_ledger_event",event_type,source_id,at.isoformat(),*reasons);self.ledger.add(PortfolioLedgerEvent(eid,event_type,source_id,at,tuple(reasons)))
    def _bound(self):
        for store,limit in ((self.records,self.configuration.maximum_records),(self.record_versions,self.configuration.maximum_records*4),(self.reservations,self.configuration.maximum_reservations),(self.snapshots,self.configuration.maximum_snapshots),(self.decisions,self.configuration.maximum_snapshots),(self._cache,self.configuration.maximum_cache_entries)):
            while len(store)>limit:store.popitem(last=False)
    def recovery_state(self):return {"engine_version":PORTFOLIO_ENGINE_VERSION,"configuration_snapshot_id":self.configuration.configuration_snapshot_id,"records":tuple(self.records.values()),"record_versions":tuple(self.record_versions.values()),"reservations":tuple(self.reservations.values()),"ledger":self.ledger.snapshot(),"complete":self.complete}
    def restore(self,state):
        if state.get("engine_version")!=PORTFOLIO_ENGINE_VERSION or state.get("configuration_snapshot_id")!=self.configuration.configuration_snapshot_id:return False
        records=tuple(state.get("records",()));versions=tuple(state.get("record_versions",records));reservations=tuple(state.get("reservations",()))
        if len({x.exposure_record_id for x in records})!=len(records) or len({x.reservation_id for x in reservations})!=len(reservations) or not self.ledger.restore(state.get("ledger",{})):return False
        if len({x.exposure_version_id for x in versions})!=len(versions):return False
        self.records=OrderedDict((x.exposure_record_id,x) for x in records);self.record_versions=OrderedDict((x.exposure_version_id,x) for x in versions);self.reservations=OrderedDict((x.reservation_id,x) for x in reservations);self.complete=bool(state.get("complete",False));return True

class ICorrelationRiskProvider:
    """Prompt 23 contract only; no correlation benefit is available in Prompt 22."""
    def available(self):return False
