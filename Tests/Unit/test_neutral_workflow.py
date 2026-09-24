from dataclasses import FrozenInstanceError,replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.simulation.workflow import *

NOW=datetime(2026,7,1,12,tzinfo=timezone.utc)

def request(tag="A",authorized="1",requested="1",at=NOW,ttl=3600):
    return WorkflowRequest.create("AUTH-"+tag,"DOCUMENT_TRANSFORM","SUBJECT-"+tag,authorized,requested,at,"PAYLOAD-"+tag,ttl_seconds=ttl)

def started(engine=None,tag="A",amount="1"):
    engine=engine or DeterministicWorkflowEngine();result=engine.process(request(tag,amount,amount),NOW);return engine,result.submission

def test_configuration_validation_and_neutral_surface():
    with pytest.raises(ValueError):DeterministicWorkflowEngine(WorkflowConfiguration(work_step=Decimal("0")))
    with pytest.raises(ValueError):DeterministicWorkflowEngine(WorkflowConfiguration(maximum_retries=-1))
    forbidden={"place_order","broker_login","connect_broker","read_account","set_leverage","calculate_margin","open_position","close_position","market_fill"};assert forbidden.isdisjoint(set(dir(DeterministicWorkflowEngine())))

def test_request_validation_quantizes_down_and_cannot_exceed_authorization():
    e=DeterministicWorkflowEngine(WorkflowConfiguration(work_step=Decimal(".1")));q=request(authorized="1",requested=".96");v=e.validate(q,NOW);assert v.valid and v.accepted_work==Decimal(".9")
    blocked=e.process(request("B","1","1.1"),NOW);assert blocked.outcome is WorkflowOutcome.REJECTED and blocked.submission is None

def test_zero_work_is_no_action_and_future_expired_fail_closed():
    e=DeterministicWorkflowEngine();assert e.process(request(requested="0"),NOW).outcome is WorkflowOutcome.NO_ACTION
    future=request("F",at=NOW+timedelta(minutes=1));assert e.process(future,NOW).outcome is WorkflowOutcome.REJECTED
    expired=request("E",at=NOW-timedelta(hours=2),ttl=10);assert e.process(expired,NOW).outcome is WorkflowOutcome.REJECTED

def test_request_idempotency_and_duplicate_does_not_create_work():
    e=DeterministicWorkflowEngine();q=request();one=e.process(q,NOW);two=e.process(q,NOW+timedelta(seconds=1));assert one.submission.submission_id==two.submission.submission_id and len(e.submissions)==1 and two.submission.authorized_work==one.submission.authorized_work

def test_acknowledge_partial_complete_and_conservation():
    e,s=started();a=e.acknowledge(s.submission_id,NOW+timedelta(seconds=1));p=e.complete(s.submission_id,".4",NOW+timedelta(seconds=2),"PART-1");done=e.complete(s.submission_id,".8",NOW+timedelta(seconds=3),"PART-2")
    assert a.submission.state is WorkflowState.ACKNOWLEDGED and p.outcome is WorkflowOutcome.PARTIAL and p.submission.completed_work==Decimal(".4") and done.outcome is WorkflowOutcome.COMPLETED and done.submission.completed_work==done.submission.authorized_work and done.submission.remaining_work==0

def test_no_overcompletion_duplicate_completion_and_terminal_safety():
    e,s=started();e.acknowledge(s.submission_id,NOW+timedelta(seconds=1));done=e.complete(s.submission_id,"2",NOW+timedelta(seconds=2),"ONCE");again=e.complete(s.submission_id,"1",NOW+timedelta(seconds=3),"AGAIN");assert done.submission.completed_work==1 and again.outcome is WorkflowOutcome.NO_ACTION and again.submission.completed_work==1

def test_partial_then_cancel_preserves_completed_work():
    e,s=started();e.acknowledge(s.submission_id,NOW+timedelta(seconds=1));partial=e.complete(s.submission_id,".3",NOW+timedelta(seconds=2),"PART");cancel=e.cancel(s.submission_id,NOW+timedelta(seconds=3));assert cancel.submission.state is WorkflowState.CANCELLED and cancel.submission.completed_work==partial.submission.completed_work and cancel.submission.completed_work<=cancel.submission.authorized_work

def test_all_or_nothing_rejects_partial_without_mutation():
    e,s=started(DeterministicWorkflowEngine(WorkflowConfiguration(completion_policy=CompletionPolicy.ALL_OR_NOTHING)));e.acknowledge(s.submission_id,NOW+timedelta(seconds=1));result=e.complete(s.submission_id,".5",NOW+timedelta(seconds=2),"PART");assert result.outcome is WorkflowOutcome.REJECTED and result.submission.completed_work==0

def test_timeout_retry_bounded_and_retry_never_increases_work():
    e,s=started(DeterministicWorkflowEngine(WorkflowConfiguration(timeout_seconds=2,maximum_retries=1)));timed=e.timeout(s.submission_id,NOW+timedelta(seconds=3));retry=e.retry(s.submission_id,NOW+timedelta(seconds=4));blocked=e.retry(s.submission_id,NOW+timedelta(seconds=5));assert timed.outcome is WorkflowOutcome.TIMED_OUT and retry.submission.retry_count==1 and retry.submission.authorized_work==s.authorized_work and blocked.outcome is WorkflowOutcome.REJECTED

def test_expiration_and_invalid_out_of_order_transition():
    e=DeterministicWorkflowEngine();q=request(ttl=2);s=e.process(q,NOW).submission;early=e.expire(s.submission_id,NOW+timedelta(seconds=1));late=e.expire(s.submission_id,NOW+timedelta(seconds=3));assert early.outcome is WorkflowOutcome.NO_ACTION and late.outcome is WorkflowOutcome.EXPIRED
    e2,s2=started();assert e2.complete(s2.submission_id,"1",NOW+timedelta(seconds=1),"BAD").outcome is WorkflowOutcome.REJECTED

def test_event_sequence_snapshot_point_in_time_and_immutability():
    e,s=started();ack=e.acknowledge(s.submission_id,NOW+timedelta(seconds=1));e.complete(s.submission_id,".2",NOW+timedelta(seconds=2),"P");snap=e.snapshot(s.submission_id,NOW+timedelta(seconds=1));assert snap.state is WorkflowState.ACKNOWLEDGED and len(snap.event_ids)==1
    with pytest.raises(FrozenInstanceError):snap.completed_work=99

def test_reconciliation_consistent_and_detects_mismatch_without_creating_work():
    e,s=started();e.acknowledge(s.submission_id,NOW+timedelta(seconds=1));e.complete(s.submission_id,".2",NOW+timedelta(seconds=2),"P");good=e.reconcile(s.submission_id,NOW+timedelta(seconds=3));assert good.status is ReconciliationStatus.CONSISTENT and not good.repaired
    item=e.submissions[s.submission_id];e.submissions[s.submission_id]=replace(item,completed_work=Decimal(".9"));bad=e.reconcile(s.submission_id,NOW+timedelta(seconds=4));assert bad.status is ReconciliationStatus.COMPLETION_MISMATCH and not bad.repaired

def test_recovery_deterministic_replay_and_corruption_fail_closed():
    e,s=started();e.acknowledge(s.submission_id,NOW+timedelta(seconds=1));e.complete(s.submission_id,".4",NOW+timedelta(seconds=2),"P");state=e.recovery_state();r=DeterministicWorkflowEngine();assert r.restore(state) and r.submissions[s.submission_id].completed_work==Decimal(".4") and r.reconcile(s.submission_id,NOW+timedelta(seconds=3)).status is ReconciliationStatus.CONSISTENT
    bad={**state,"schema_version":"OLD"};assert not r.restore(bad) and r.recovery_restricted
    corrupt={**state,"submissions":(replace(state["submissions"][0],completed_work=Decimal(".9")),)};fresh=DeterministicWorkflowEngine();assert not fresh.restore(corrupt) and fresh.recovery_restricted

def test_duplicate_and_out_of_sequence_ledger_events_rejected():
    e,s=started();e.acknowledge(s.submission_id,NOW+timedelta(seconds=1));event=next(iter(e.ledger.events.values()));assert not e.ledger.append(event)
    bad=replace(event,event_id="OTHER",event_sequence=3);assert not e.ledger.append(bad)

def test_multi_subject_isolation_concurrency_and_order_independence():
    a=DeterministicWorkflowEngine();qa=request("A");qb=request("B");sa=a.process(qa,NOW).submission;sb=a.process(qb,NOW).submission;a.acknowledge(sa.submission_id,NOW+timedelta(seconds=1));a.complete(sa.submission_id,".5",NOW+timedelta(seconds=2),"A")
    assert a.submissions[sb.submission_id].completed_work==0
    b=DeterministicWorkflowEngine();rb=b.process(qb,NOW).submission;ra=b.process(qa,NOW).submission;assert {sa.submission_id,sb.submission_id}=={ra.submission_id,rb.submission_id}

def test_concurrent_duplicate_requests_are_serialized_and_idempotent():
    e=DeterministicWorkflowEngine();q=request("CONCURRENT")
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda _:e.process(q,NOW),range(32)))
    assert len(e.submissions)==1 and len({x.submission.submission_id for x in results})==1 and next(iter(e.submissions.values())).authorized_work==Decimal("1")

def test_bounds_audit_decision_trace_and_failure_injection():
    audit=InMemoryAuditSink();cfg=WorkflowConfiguration(maximum_requests=1,maximum_submissions=1,maximum_events=2,maximum_snapshots=1,maximum_cache_entries=1);e=DeterministicWorkflowEngine(cfg,audit);r=e.process(request(),NOW);assert r.decision_trace and any(x[0]=="workflow_submitted" for x in audit.events)
    invalid=e.complete(r.submission.submission_id,Decimal("NaN"),NOW+timedelta(seconds=1),"NAN");assert invalid.outcome is WorkflowOutcome.INVALID

def test_metamorphic_authorization_and_restart_invariants():
    low=DeterministicWorkflowEngine();a=low.process(request(authorized=".5",requested=".5"),NOW).submission;high=DeterministicWorkflowEngine();b=high.process(request(authorized="1",requested=".5"),NOW).submission;assert a.authorized_work==b.authorized_work==Decimal(".5")
    before=b.completed_work;state=high.recovery_state();restored=DeterministicWorkflowEngine();assert restored.restore(state) and restored.submissions[b.submission_id].completed_work==before
