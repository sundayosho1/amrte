"""Deterministic experiments over neutral offline observations.

The engine validates software/research configurations.  It contains no market,
trading, financial, wagering, broker, account, or execution semantics.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass,replace
from datetime import datetime
from decimal import Decimal
from enum import Enum,auto
from itertools import product
from threading import RLock
from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation,DecisionOutcome,DecisionStatus,DecisionTrace

VERSION="1.0";SCHEMA="1.0";ZERO=Decimal("0");ONE=Decimal("1")
class ExperimentMode(Enum):EXPLORATORY=auto();CONFIRMATORY=auto();PRE_REGISTERED=auto()
class ExperimentState(Enum):PLANNED=auto();VALIDATED=auto();RUNNING=auto();PARTIAL=auto();COMPLETED=auto();CANCELLED=auto();FAILED=auto();QUARANTINED=auto()
class TrialState(Enum):PENDING=auto();RUNNING=auto();COMPLETED=auto();FAILED=auto();CANCELLED=auto()
class ValidationQuality(Enum):VALID=auto();LIMITED=auto();INSUFFICIENT=auto();INVALID=auto();UNKNOWN=auto()
class ReconciliationState(Enum):CONSISTENT=auto();REVIEW_REQUIRED=auto();FAILED_CLOSED=auto()

@dataclass(frozen=True)
class ValidationConfiguration:
    maximum_observations:int=100000;maximum_trials:int=4096;maximum_runs:int=512;maximum_checkpoints:int=2048;minimum_sample:int=5;adequate_sample:int=20;precision:Decimal=Decimal("0.00000001");configuration_snapshot_id:str="NEUTRAL_EXPERIMENT_DEFAULT"
    def validate(self):
        errors=[]
        if min(self.maximum_observations,self.maximum_trials,self.maximum_runs,self.maximum_checkpoints,self.minimum_sample,self.adequate_sample)<1 or self.minimum_sample>self.adequate_sample:errors.append("EXPERIMENT_BOUNDS_INVALID")
        p=Decimal(str(self.precision))
        if not p.is_finite() or p<=ZERO:errors.append("EXPERIMENT_PRECISION_INVALID")
        return tuple(errors)
@dataclass(frozen=True)
class OfflineDatasetManifest:
    dataset_id:str;dataset_fingerprint:str;schema_version:str;subject_ids:tuple[str,...];coverage_start_utc:datetime;coverage_end_utc:datetime;observation_count:int;created_at_utc:datetime;source_description:str
@dataclass(frozen=True)
class NeutralObservation:
    observation_id:str;subject_id:str;category_id:str;context_id:str;observed_at_utc:datetime;known_at_utc:datetime;input_value:Decimal;dataset_fingerprint:str
    @classmethod
    def create(cls,subject_id,category_id,context_id,observed_at_utc,known_at_utc,input_value,dataset_fingerprint):
        value=Decimal(str(input_value));oid=deterministic_id("neutral_observation",subject_id,category_id,context_id,observed_at_utc.isoformat(),known_at_utc.isoformat(),value,dataset_fingerprint);return cls(oid,subject_id,category_id,context_id,observed_at_utc,known_at_utc,value,dataset_fingerprint)
@dataclass(frozen=True)
class ParameterDimension:
    parameter_id:str;values:tuple[Decimal,...]
@dataclass(frozen=True)
class ExperimentDefinition:
    experiment_id:str;name:str;mode:ExperimentMode;dataset_manifest:OfflineDatasetManifest;parameter_dimensions:tuple[ParameterDimension,...];subject_ids:tuple[str,...];category_ids:tuple[str,...];context_ids:tuple[str,...];start_time_utc:datetime;end_time_utc:datetime;as_of_time_utc:datetime;holdout_subject_ids:tuple[str,...];pre_registered_at_utc:datetime|None;configuration_snapshot_id:str;definition_version:str
    @classmethod
    def create(cls,name,mode,dataset_manifest,parameter_dimensions,subject_ids,category_ids,context_ids,start_time_utc,end_time_utc,as_of_time_utc,holdout_subject_ids=(),pre_registered_at_utc=None,configuration_snapshot_id="NEUTRAL_EXPERIMENT_DEFAULT",definition_version="1.0"):
        dimensions=tuple(sorted(parameter_dimensions,key=lambda x:x.parameter_id));eid=deterministic_id("neutral_experiment",name,mode.name,dataset_manifest.dataset_fingerprint,*[x.parameter_id for x in dimensions],*[str(v) for x in dimensions for v in x.values],*sorted(subject_ids),*sorted(category_ids),*sorted(context_ids),start_time_utc.isoformat(),end_time_utc.isoformat(),as_of_time_utc.isoformat(),*sorted(holdout_subject_ids),pre_registered_at_utc.isoformat() if pre_registered_at_utc else "NONE",configuration_snapshot_id,definition_version);return cls(eid,name,mode,dataset_manifest,dimensions,tuple(sorted(subject_ids)),tuple(sorted(category_ids)),tuple(sorted(context_ids)),start_time_utc,end_time_utc,as_of_time_utc,tuple(sorted(holdout_subject_ids)),pre_registered_at_utc,configuration_snapshot_id,definition_version)
@dataclass(frozen=True)
class ExperimentTrial:
    trial_id:str;experiment_id:str;parameters:tuple[tuple[str,Decimal],...];state:TrialState;eligible_observation_ids:tuple[str,...];mean_score:Decimal|None;variance_score:Decimal|None;minimum_score:Decimal|None;maximum_score:Decimal|None;sample_count:int;quality:ValidationQuality;started_at_utc:datetime|None;completed_at_utc:datetime|None;reason_codes:tuple[str,...]
@dataclass(frozen=True)
class ParameterSensitivity:
    parameter_id:str;tested_values:tuple[Decimal,...];mean_scores:tuple[Decimal,...];score_range:Decimal;stable:bool
@dataclass(frozen=True)
class ValidationScorecard:
    scorecard_id:str;experiment_id:str;trial_count:int;completed_trial_count:int;sample_count:int;mean_of_trial_means:Decimal|None;trial_mean_variance:Decimal|None;parameter_sensitivity:tuple[ParameterSensitivity,...];concentration_share:Decimal|None;quality:ValidationQuality;warnings:tuple[str,...]
@dataclass(frozen=True)
class ExperimentRun:
    run_id:str;experiment_id:str;state:ExperimentState;trial_ids:tuple[str,...];completed_trial_ids:tuple[str,...];failed_trial_ids:tuple[str,...];cancelled_trial_ids:tuple[str,...];started_at_utc:datetime;updated_at_utc:datetime;completed_at_utc:datetime|None;dataset_fingerprint:str;configuration_snapshot_id:str;recovery_epoch:int;scorecard_id:str|None;reason_codes:tuple[str,...]
@dataclass(frozen=True)
class ExperimentCheckpoint:
    checkpoint_id:str;run_id:str;state:ExperimentState;completed_trial_ids:tuple[str,...];created_at_utc:datetime;sequence:int
@dataclass(frozen=True)
class ExperimentResultManifest:
    manifest_id:str;run_id:str;experiment_id:str;definition_fingerprint:str;dataset_fingerprint:str;configuration_snapshot_id:str;trial_ids:tuple[str,...];scorecard_id:str;replay_fingerprint:str;created_at_utc:datetime;engine_version:str
@dataclass(frozen=True)
class ExperimentRecovery:
    schema_version:str;engine_version:str;configuration_snapshot_id:str;recovery_epoch:int;definitions:tuple[ExperimentDefinition,...];observations:tuple[NeutralObservation,...];runs:tuple[ExperimentRun,...];trials:tuple[ExperimentTrial,...];scorecards:tuple[ValidationScorecard,...];checkpoints:tuple[ExperimentCheckpoint,...];manifests:tuple[ExperimentResultManifest,...]

class DeterministicExperimentEngine:
    def __init__(self,configuration=ValidationConfiguration(),audit=None):
        errors=configuration.validate()
        if errors:raise ValueError(";".join(errors))
        self.configuration=configuration;self.audit=audit;self._lock=RLock();self.definitions=OrderedDict();self.observations=OrderedDict();self.runs=OrderedDict();self.trials=OrderedDict();self.scorecards=OrderedDict();self.checkpoints=OrderedDict();self.manifests=OrderedDict();self.recovery_restricted=False
    def register(self,definition,observations):
        with self._lock:
            if definition.experiment_id in self.definitions:return False,"EXPERIMENT_DUPLICATE"
            errors=self._validate_definition(definition);valid=[]
            for x in observations:
                if self._valid_observation(x,definition):valid.append(x)
                else:errors.append("EXPERIMENT_OBSERVATION_INVALID")
            if errors:return False,tuple(sorted(set(errors)))
            if len(self.observations)+len(valid)>self.configuration.maximum_observations:return False,("EXPERIMENT_OBSERVATION_BOUND",)
            for x in valid:self.observations[x.observation_id]=x
            self.definitions[definition.experiment_id]=definition;self._record("experiment_registered",{"experiment_id":definition.experiment_id});return True,("EXPERIMENT_VALIDATED",)
    def plan(self,experiment_id,at,recovery_epoch=0):
        with self._lock:
            d=self.definitions.get(experiment_id)
            if not d:raise ValueError("EXPERIMENT_NOT_REGISTERED")
            combos=list(product(*[x.values for x in d.parameter_dimensions])) if d.parameter_dimensions else [()]
            if len(combos)>self.configuration.maximum_trials:raise ValueError("EXPERIMENT_TRIAL_BOUND")
            eligible=tuple(x.observation_id for x in self._eligible(d))
            tids=[]
            for values in combos:
                params=tuple((d.parameter_dimensions[i].parameter_id,Decimal(str(value))) for i,value in enumerate(values));tid=deterministic_id("neutral_trial",experiment_id,*[v for pair in params for v in pair]);trial=ExperimentTrial(tid,experiment_id,params,TrialState.PENDING,eligible,None,None,None,None,len(eligible),ValidationQuality.UNKNOWN,None,None,());self.trials[tid]=trial;tids.append(tid)
            rid=deterministic_id("experiment_run",experiment_id,*tids,d.dataset_manifest.dataset_fingerprint,d.configuration_snapshot_id,recovery_epoch);run=ExperimentRun(rid,experiment_id,ExperimentState.VALIDATED,tuple(tids),(),(),(),at,at,None,d.dataset_manifest.dataset_fingerprint,d.configuration_snapshot_id,recovery_epoch,None,());self.runs[rid]=run;return run
    def execute(self,run_id,at,evaluator=None,maximum_trials=None):
        with self._lock:
            run=self.runs.get(run_id)
            if not run:raise ValueError("EXPERIMENT_RUN_NOT_FOUND")
            if run.state in (ExperimentState.COMPLETED,ExperimentState.CANCELLED):return run
            d=self.definitions[run.experiment_id];limit=maximum_trials or len(run.trial_ids);completed=list(run.completed_trial_ids);failed=list(run.failed_trial_ids)
            for tid in run.trial_ids:
                if tid in completed or tid in failed or len(completed)+len(failed)>=limit:continue
                trial=self.trials[tid]
                try:
                    scores=[]
                    for oid in trial.eligible_observation_ids:
                        o=self.observations[oid];score=Decimal(str(evaluator(o,dict(trial.parameters)))) if evaluator else self._default_score(o,dict(trial.parameters))
                        if not score.is_finite():raise ValueError
                        scores.append(score)
                    updated=self._finish_trial(trial,scores,at);self.trials[tid]=updated;completed.append(tid)
                except Exception:self.trials[tid]=replace(trial,state=TrialState.FAILED,completed_at_utc=at,reason_codes=("EXPERIMENT_EVALUATION_FAILED",));failed.append(tid)
            terminal=len(completed)+len(failed)==len(run.trial_ids);state=ExperimentState.COMPLETED if terminal else ExperimentState.PARTIAL;updated=replace(run,state=state,completed_trial_ids=tuple(completed),failed_trial_ids=tuple(failed),updated_at_utc=at,completed_at_utc=at if terminal else None)
            scorecard=self._scorecard(d,updated);self.scorecards[scorecard.scorecard_id]=scorecard;updated=replace(updated,scorecard_id=scorecard.scorecard_id);self.runs[run_id]=updated;self._checkpoint(updated,at)
            if terminal:
                fingerprint=self.replay_fingerprint(run_id);mid=deterministic_id("experiment_result_manifest",run_id,scorecard.scorecard_id,fingerprint);self.manifests[mid]=ExperimentResultManifest(mid,run_id,d.experiment_id,deterministic_id("experiment_definition",d.experiment_id),d.dataset_manifest.dataset_fingerprint,d.configuration_snapshot_id,run.trial_ids,scorecard.scorecard_id,fingerprint,at,VERSION)
            self._record("experiment_run_updated",{"run_id":run_id,"state":state.name});return updated
    def cancel(self,run_id,at,reason):
        with self._lock:
            run=self.runs.get(run_id)
            if not run or run.state in (ExperimentState.COMPLETED,ExperimentState.CANCELLED):return run
            pending=[]
            for tid in run.trial_ids:
                if tid not in run.completed_trial_ids and tid not in run.failed_trial_ids:self.trials[tid]=replace(self.trials[tid],state=TrialState.CANCELLED,completed_at_utc=at,reason_codes=("EXPERIMENT_CANCELLED",reason));pending.append(tid)
            updated=replace(run,state=ExperimentState.CANCELLED,cancelled_trial_ids=tuple(pending),updated_at_utc=at,completed_at_utc=at,reason_codes=("EXPERIMENT_CANCELLED",));self.runs[run_id]=updated;self._checkpoint(updated,at);return updated
    def reconcile(self,run_id):
        run=self.runs.get(run_id)
        if not run:return ReconciliationState.FAILED_CLOSED,("EXPERIMENT_RUN_MISSING",)
        known=set(run.completed_trial_ids+run.failed_trial_ids+run.cancelled_trial_ids)
        if not known.issubset(run.trial_ids) or len(known)!=len(set(known)):return ReconciliationState.FAILED_CLOSED,("EXPERIMENT_TRIAL_STATE_INVALID",)
        for tid in run.completed_trial_ids:
            if self.trials.get(tid) is None or self.trials[tid].state is not TrialState.COMPLETED:return ReconciliationState.FAILED_CLOSED,("EXPERIMENT_TRIAL_MISMATCH",)
        return ReconciliationState.CONSISTENT,()
    def recovery_state(self,epoch):return ExperimentRecovery(SCHEMA,VERSION,self.configuration.configuration_snapshot_id,epoch,tuple(self.definitions.values()),tuple(self.observations.values()),tuple(self.runs.values()),tuple(self.trials.values()),tuple(self.scorecards.values()),tuple(self.checkpoints.values()),tuple(self.manifests.values()))
    def restore(self,state,epoch):
        with self._lock:
            if state.schema_version!=SCHEMA or state.engine_version!=VERSION or state.configuration_snapshot_id!=self.configuration.configuration_snapshot_id or state.recovery_epoch!=epoch:self.recovery_restricted=True;return False
            try:
                groups=((x.experiment_id for x in state.definitions),(x.observation_id for x in state.observations),(x.run_id for x in state.runs),(x.trial_id for x in state.trials),(x.scorecard_id for x in state.scorecards),(x.checkpoint_id for x in state.checkpoints),(x.manifest_id for x in state.manifests))
                if any(len(ids:=list(g))!=len(set(ids)) for g in groups):raise ValueError
                self.definitions=OrderedDict((x.experiment_id,x) for x in state.definitions);self.observations=OrderedDict((x.observation_id,x) for x in state.observations);self.runs=OrderedDict((x.run_id,x) for x in state.runs);self.trials=OrderedDict((x.trial_id,x) for x in state.trials);self.scorecards=OrderedDict((x.scorecard_id,x) for x in state.scorecards);self.checkpoints=OrderedDict((x.checkpoint_id,x) for x in state.checkpoints);self.manifests=OrderedDict((x.manifest_id,x) for x in state.manifests)
                if any(self.reconcile(x.run_id)[0] is ReconciliationState.FAILED_CLOSED for x in state.runs):raise ValueError
                self.recovery_restricted=False;return True
            except Exception:self.recovery_restricted=True;return False
    def replay_fingerprint(self,run_id):
        run=self.runs[run_id];return deterministic_id("experiment_replay",run.run_id,run.state.name,*run.trial_ids,*[self.trials[x].state.name for x in run.trial_ids],run.scorecard_id or "NONE")
    def _validate_definition(self,d):
        e=[]
        if not d.name or not d.dataset_manifest.dataset_fingerprint or d.start_time_utc>d.end_time_utc or d.end_time_utc>d.as_of_time_utc:e.append("EXPERIMENT_DEFINITION_INVALID")
        if d.configuration_snapshot_id!=self.configuration.configuration_snapshot_id:e.append("EXPERIMENT_CONFIGURATION_MISMATCH")
        ids=[x.parameter_id for x in d.parameter_dimensions]
        if len(ids)!=len(set(ids)) or any(not x.values or len(x.values)!=len(set(x.values)) or any(not v.is_finite() for v in x.values) for x in d.parameter_dimensions):e.append("EXPERIMENT_PARAMETER_GRID_INVALID")
        if d.mode is ExperimentMode.PRE_REGISTERED and (not d.pre_registered_at_utc or d.pre_registered_at_utc>d.start_time_utc):e.append("EXPERIMENT_PREREGISTRATION_INVALID")
        if set(d.holdout_subject_ids)-set(d.dataset_manifest.subject_ids):e.append("EXPERIMENT_HOLDOUT_INVALID")
        return e
    @staticmethod
    def _valid_observation(o,d):return o.input_value.is_finite() and o.observed_at_utc<=o.known_at_utc<=d.as_of_time_utc and d.start_time_utc<=o.observed_at_utc<=d.end_time_utc and o.dataset_fingerprint==d.dataset_manifest.dataset_fingerprint and o.subject_id in d.dataset_manifest.subject_ids
    def _eligible(self,d):return sorted((x for x in self.observations.values() if x.dataset_fingerprint==d.dataset_manifest.dataset_fingerprint and x.subject_id in d.subject_ids and x.subject_id not in d.holdout_subject_ids and (not d.category_ids or x.category_id in d.category_ids) and (not d.context_ids or x.context_id in d.context_ids) and x.known_at_utc<=d.as_of_time_utc),key=lambda x:(x.known_at_utc,x.observation_id))
    def _default_score(self,o,p):return self._q(o.input_value*sum(p.values(),ONE))
    def _finish_trial(self,t,scores,at):
        n=len(scores);quality=ValidationQuality.INSUFFICIENT if n<self.configuration.minimum_sample else ValidationQuality.LIMITED if n<self.configuration.adequate_sample else ValidationQuality.VALID
        if not scores:return replace(t,state=TrialState.COMPLETED,mean_score=None,variance_score=None,sample_count=0,quality=ValidationQuality.INSUFFICIENT,started_at_utc=at,completed_at_utc=at,reason_codes=("EXPERIMENT_INSUFFICIENT_SAMPLE",))
        mean=self._q(sum(scores,ZERO)/Decimal(n));variance=self._q(sum(((x-mean)*(x-mean) for x in scores),ZERO)/Decimal(n));return replace(t,state=TrialState.COMPLETED,mean_score=mean,variance_score=variance,minimum_score=min(scores),maximum_score=max(scores),sample_count=n,quality=quality,started_at_utc=at,completed_at_utc=at,reason_codes=("EXPERIMENT_TRIAL_COMPLETED",))
    def _scorecard(self,d,run):
        completed=[self.trials[x] for x in run.completed_trial_ids];means=[x.mean_score for x in completed if x.mean_score is not None];mean=self._q(sum(means,ZERO)/Decimal(len(means))) if means else None;variance=self._q(sum(((x-mean)*(x-mean) for x in means),ZERO)/Decimal(len(means))) if means else None;sensitivity=[]
        for dimension in d.parameter_dimensions:
            grouped=[]
            for value in dimension.values:
                xs=[x.mean_score for x in completed if dict(x.parameters).get(dimension.parameter_id)==value and x.mean_score is not None];grouped.append(self._q(sum(xs,ZERO)/Decimal(len(xs))) if xs else ZERO)
            span=self._q(max(grouped)-min(grouped)) if grouped else ZERO;sensitivity.append(ParameterSensitivity(dimension.parameter_id,dimension.values,tuple(grouped),span,span<=Decimal("0.25")))
        sample=sum(x.sample_count for x in completed);quality=ValidationQuality.INSUFFICIENT if sample<self.configuration.minimum_sample else ValidationQuality.LIMITED if sample<self.configuration.adequate_sample else ValidationQuality.VALID;all_scores=[abs(self.observations[oid].input_value) for x in completed for oid in x.eligible_observation_ids];concentration=self._q(max(all_scores)/sum(all_scores,ZERO)) if all_scores and sum(all_scores,ZERO)>ZERO else None;warnings=tuple(x for x,flag in (("EXPERIMENT_PARAMETER_SENSITIVE",any(not y.stable for y in sensitivity)),("EXPERIMENT_CONCENTRATED",concentration is not None and concentration>Decimal(".5")),("EXPERIMENT_SMALL_SAMPLE",quality is not ValidationQuality.VALID)) if flag);sid=deterministic_id("validation_scorecard",run.run_id,*run.completed_trial_ids,*warnings)
        return ValidationScorecard(sid,d.experiment_id,len(run.trial_ids),len(completed),sample,mean,variance,tuple(sensitivity),concentration,quality,warnings)
    def _checkpoint(self,run,at):
        seq=sum(1 for x in self.checkpoints.values() if x.run_id==run.run_id)+1;cid=deterministic_id("experiment_checkpoint",run.run_id,seq,run.state.name,*run.completed_trial_ids);self.checkpoints[cid]=ExperimentCheckpoint(cid,run.run_id,run.state,run.completed_trial_ids,at,seq)
        while len(self.checkpoints)>self.configuration.maximum_checkpoints:self.checkpoints.popitem(last=False)
    def _q(self,x):return Decimal(x).quantize(self.configuration.precision)
    def trace(self,run_id,at):
        run=self.runs[run_id];reason=run.reason_codes[-1] if run.reason_codes else f"EXPERIMENT_{run.state.name}";evaluation=DecisionEvaluation("NEUTRAL_EXPERIMENT",DecisionStatus.PASSED if run.state in (ExperimentState.COMPLETED,ExperimentState.PARTIAL) else DecisionStatus.FAILED,reason,"Neutral deterministic validation run",run.trial_ids);tid=deterministic_id("experiment_trace",run_id,run.state.name,*run.trial_ids);return DecisionTrace(tid,run_id,run.started_at_utc,(evaluation,),DecisionOutcome.ACCEPTED if run.state is ExperimentState.COMPLETED else DecisionOutcome.NO_ACTION,reason,at,None)
    def _record(self,event,payload):
        if self.audit:self.audit.record(event,payload)

