from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.validation.experiments import *

NOW=datetime(2026,9,21,12,tzinfo=timezone.utc)


def manifest(subjects=("A","B")):
    return OfflineDatasetManifest("DATASET","FP-DATA","1",subjects,NOW,NOW+timedelta(hours=1),20,NOW,"synthetic neutral fixture")


def observation(tag,value,second,subject="A",known=None,fingerprint="FP-DATA"):
    at=NOW+timedelta(seconds=second);return NeutralObservation.create(subject,"CAT","CONTEXT",at,known or at,Decimal(str(value)),fingerprint)


def definition(mode=ExperimentMode.EXPLORATORY,dimensions=None,holdout=(),preregistered=None,**changes):
    values=dict(name="NEUTRAL VALIDATION",mode=mode,dataset_manifest=manifest(),parameter_dimensions=dimensions if dimensions is not None else (ParameterDimension("gain",(Decimal(".5"),Decimal("1"),Decimal("1.5"))),),subject_ids=("A","B"),category_ids=("CAT",),context_ids=("CONTEXT",),start_time_utc=NOW,end_time_utc=NOW+timedelta(hours=1),as_of_time_utc=NOW+timedelta(hours=1),holdout_subject_ids=holdout,pre_registered_at_utc=preregistered)
    values.update(changes);return ExperimentDefinition.create(**values)


def ready_engine(d=None,items=None,config=None,audit=None):
    target=DeterministicExperimentEngine(config or ValidationConfiguration(minimum_sample=2,adequate_sample=4),audit)
    d=d or definition();items=items or tuple(observation(str(i),i-2,i,subject="A" if i%2==0 else "B") for i in range(6));assert target.register(d,items)[0];return target,d,items


def test_configuration_validation():
    with pytest.raises(ValueError):DeterministicExperimentEngine(ValidationConfiguration(minimum_sample=10,adequate_sample=2))
    with pytest.raises(ValueError):DeterministicExperimentEngine(ValidationConfiguration(precision=Decimal("0")))


def test_definition_identity_immutability_and_duplicate_registration():
    target,d,items=ready_engine();assert d.experiment_id==definition().experiment_id
    assert target.register(d,items)==(False,"EXPERIMENT_DUPLICATE")
    with pytest.raises(FrozenInstanceError):d.name="OTHER"


def test_invalid_temporal_lineage_and_numeric_observations_fail_closed():
    d=definition();future=observation("F",1,1,known=NOW+timedelta(hours=2));wrong=observation("W",1,2,fingerprint="OTHER");nan=observation("N","NaN",3)
    target=DeterministicExperimentEngine();ok,reasons=target.register(d,(future,wrong,nan))
    assert not ok and "EXPERIMENT_OBSERVATION_INVALID" in reasons and not target.definitions


def test_parameter_grid_identity_and_trial_count_are_deterministic():
    dims=(ParameterDimension("alpha",(Decimal("1"),Decimal("2"))),ParameterDimension("beta",(Decimal("3"),Decimal("4"),Decimal("5"))))
    target,d,_=ready_engine(definition(dimensions=dims));run=target.plan(d.experiment_id,NOW)
    assert len(run.trial_ids)==6 and run==target.plan(d.experiment_id,NOW)
    assert len(set(run.trial_ids))==6


def test_duplicate_parameter_and_bound_validation():
    bad=definition(dimensions=(ParameterDimension("x",(Decimal("1"),Decimal("1"))),))
    target=DeterministicExperimentEngine();assert not target.register(bad,(observation("1",1,1),))[0]
    target,d,_=ready_engine(definition(dimensions=(ParameterDimension("x",(Decimal("1"),Decimal("2"))),)),config=ValidationConfiguration(maximum_trials=1,minimum_sample=1,adequate_sample=2))
    with pytest.raises(ValueError):target.plan(d.experiment_id,NOW)


def test_full_execution_scorecard_sensitivity_and_manifest():
    target,d,_=ready_engine();run=target.plan(d.experiment_id,NOW);done=target.execute(run.run_id,NOW+timedelta(hours=2))
    card=target.scorecards[done.scorecard_id]
    assert done.state is ExperimentState.COMPLETED and len(done.completed_trial_ids)==3
    assert len(card.parameter_sensitivity)==1 and card.trial_count==3
    assert len(target.manifests)==1 and target.reconcile(done.run_id)==(ReconciliationState.CONSISTENT,())


def test_partial_execution_checkpoint_and_resume_without_duplicates():
    target,d,_=ready_engine();run=target.plan(d.experiment_id,NOW);partial=target.execute(run.run_id,NOW+timedelta(hours=1),maximum_trials=1)
    assert partial.state is ExperimentState.PARTIAL and len(partial.completed_trial_ids)==1
    completed=target.execute(run.run_id,NOW+timedelta(hours=2));assert completed.state is ExperimentState.COMPLETED and len(set(completed.completed_trial_ids))==3
    assert len([x for x in target.checkpoints.values() if x.run_id==run.run_id])==2


def test_custom_evaluator_failure_is_isolated_and_fail_closed():
    target,d,_=ready_engine();run=target.plan(d.experiment_id,NOW)
    failed=target.execute(run.run_id,NOW+timedelta(hours=1),lambda observation,parameters: Decimal("NaN"))
    assert failed.state is ExperimentState.COMPLETED and len(failed.failed_trial_ids)==3 and not failed.completed_trial_ids


def test_holdout_separation_excludes_reserved_subjects():
    d=definition(holdout=("B",));target,d,_=ready_engine(d);run=target.plan(d.experiment_id,NOW)
    assert all(target.observations[x].subject_id=="A" for x in target.trials[run.trial_ids[0]].eligible_observation_ids)


def test_preregistered_mode_requires_registration_before_period():
    invalid=definition(mode=ExperimentMode.PRE_REGISTERED,preregistered=NOW+timedelta(seconds=1));target=DeterministicExperimentEngine();assert not target.register(invalid,(observation("1",1,1),))[0]
    valid=definition(mode=ExperimentMode.PRE_REGISTERED,preregistered=NOW-timedelta(seconds=1));assert DeterministicExperimentEngine().register(valid,(observation("1",1,1),))[0]


def test_cancellation_is_terminal_and_does_not_complete_work():
    target,d,_=ready_engine();run=target.plan(d.experiment_id,NOW);cancelled=target.cancel(run.run_id,NOW+timedelta(minutes=1),"operator request")
    assert cancelled.state is ExperimentState.CANCELLED and len(cancelled.cancelled_trial_ids)==3
    assert target.execute(run.run_id,NOW+timedelta(hours=1))==cancelled


def test_reconciliation_detects_corruption_without_repair():
    target,d,_=ready_engine();run=target.plan(d.experiment_id,NOW);done=target.execute(run.run_id,NOW+timedelta(hours=1));assert target.reconcile(done.run_id)[0] is ReconciliationState.CONSISTENT
    target.runs[run.run_id]=replace(done,completed_trial_ids=done.completed_trial_ids+("MISSING",))
    assert target.reconcile(run.run_id)[0] is ReconciliationState.FAILED_CLOSED


def test_recovery_and_replay_are_deterministic():
    target,d,_=ready_engine();run=target.plan(d.experiment_id,NOW,recovery_epoch=3);target.execute(run.run_id,NOW+timedelta(hours=1));fingerprint=target.replay_fingerprint(run.run_id);state=target.recovery_state(3)
    restored=DeterministicExperimentEngine(ValidationConfiguration(minimum_sample=2,adequate_sample=4));assert restored.restore(state,3);assert restored.replay_fingerprint(run.run_id)==fingerprint
    incompatible=DeterministicExperimentEngine();assert not incompatible.restore(replace(state,recovery_epoch=4),3) and incompatible.recovery_restricted


def test_concurrent_execution_is_idempotent():
    target,d,_=ready_engine();run=target.plan(d.experiment_id,NOW)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:target.execute(run.run_id,NOW+timedelta(hours=1)),range(4)))
    assert all(x.state is ExperimentState.COMPLETED for x in results)
    assert len(target.runs)==1 and len(target.manifests)==1


def test_parameter_perturbation_changes_only_affected_trial_scores():
    base,d,_=ready_engine(definition(dimensions=(ParameterDimension("gain",(Decimal("1"),)),)));r1=base.execute(base.plan(d.experiment_id,NOW).run_id,NOW+timedelta(hours=1));m1=base.scorecards[r1.scorecard_id].mean_of_trial_means
    changed,d2,_=ready_engine(definition(dimensions=(ParameterDimension("gain",(Decimal("2"),)),)));r2=changed.execute(changed.plan(d2.experiment_id,NOW).run_id,NOW+timedelta(hours=1));m2=changed.scorecards[r2.scorecard_id].mean_of_trial_means
    assert m1!=m2


def test_observation_order_does_not_change_replay_result():
    items=tuple(observation(str(i),i-2,i) for i in range(6));a,d,_=ready_engine(items=items);ra=a.execute(a.plan(d.experiment_id,NOW).run_id,NOW+timedelta(hours=1))
    b,d2,_=ready_engine(d=definition(),items=tuple(reversed(items)));rb=b.execute(b.plan(d2.experiment_id,NOW).run_id,NOW+timedelta(hours=1))
    assert a.scorecards[ra.scorecard_id]==b.scorecards[rb.scorecard_id]


def test_bounds_audit_and_decision_trace():
    audit=InMemoryAuditSink();target,d,_=ready_engine(audit=audit);run=target.plan(d.experiment_id,NOW);done=target.execute(run.run_id,NOW+timedelta(hours=1));trace=target.trace(done.run_id,NOW+timedelta(hours=1))
    assert trace.evaluations and any(x[0]=="experiment_run_updated" for x in audit.events)


def test_engine_has_no_financial_trading_or_gambling_capabilities():
    forbidden={"backtest_trade","optimize_profit","place_order","submit_trade","broker_login","account_balance","open_position","close_position","set_leverage","calculate_margin","wager","bet"}
    assert forbidden.isdisjoint(set(dir(DeterministicExperimentEngine)))

