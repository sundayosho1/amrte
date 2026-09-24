from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import pytest
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.research.temporal_quality import *
NOW=datetime(2026,9,20,12,tzinfo=timezone.utc)
def started(config=None,scope="A",epoch=0,audit=None):
 e=TemporalQualityProtectionEngine(config or TemporalQualityConfiguration(),audit);s=e.initialize(scope,f"FP-{scope}","D1","W1",NOW,epoch);return e,s
def out(tag,kind=OutcomeClass.ADVERSE,units="1",at=None,scope="A",day="D1",week="W1",epoch=0,fp=None):
 at=at or NOW+timedelta(seconds=1);return TemporalQualityOutcome.create(scope,"CATEGORY","VARIANT","SUBJECT",kind,units,day,week,at,at,f"L-{tag}",fp or f"FP-{scope}",recovery_epoch=epoch)
def test_config_validation():
 with pytest.raises(ValueError):TemporalQualityProtectionEngine(TemporalQualityConfiguration(daily_watch=Decimal("10"),daily_block=Decimal("5")))
 with pytest.raises(ValueError):TemporalQualityProtectionEngine(TemporalQualityConfiguration(watch_multiplier=Decimal("2")))
def test_daily_weekly_accumulation_and_favorable_does_not_erase_budget():
 e,_=started();a=e.process(out("1",units="3"),NOW+timedelta(seconds=1)).state;b=e.process(out("2",OutcomeClass.FAVORABLE,"0",NOW+timedelta(seconds=2)),NOW+timedelta(seconds=2)).state
 assert a.daily_adverse==b.daily_adverse==3 and a.weekly_adverse==b.weekly_adverse==3
def test_window_rollover_daily_does_not_reset_weekly():
 e,_=started();e.process(out("1",units="4"),NOW+timedelta(seconds=1));s=e.process(out("2",units="2",at=NOW+timedelta(seconds=2),day="D2"),NOW+timedelta(seconds=2)).state
 assert s.daily_adverse==2 and s.weekly_adverse==6
def test_week_rollover_resets_both_new_window_accumulators():
 e,_=started();e.process(out("1",units="4"),NOW+timedelta(seconds=1));s=e.process(out("2",units="2",at=NOW+timedelta(seconds=2),day="D2",week="W2"),NOW+timedelta(seconds=2)).state
 assert s.daily_adverse==s.weekly_adverse==2
def test_streak_watch_and_cooldown():
 e,_=started(TemporalQualityConfiguration(streak_watch=2,streak_cooldown=3))
 stages=[]
 for i in range(3):stages.append(e.process(out(str(i),units="0",at=NOW+timedelta(seconds=i+1)),NOW+timedelta(seconds=i+1)).state.published_stage)
 assert stages==[TemporalStage.NORMAL,TemporalStage.WATCH,TemporalStage.COOLDOWN]
def test_category_streak_and_favorable_reset_do_not_release_cooldown():
 e,_=started(TemporalQualityConfiguration(streak_watch=1,streak_cooldown=2));e.process(out("1",units="0"),NOW+timedelta(seconds=1));s=e.process(out("2",units="0",at=NOW+timedelta(seconds=2)),NOW+timedelta(seconds=2)).state;s2=e.process(out("3",OutcomeClass.FAVORABLE,"0",NOW+timedelta(seconds=3)),NOW+timedelta(seconds=3)).state
 assert dict(s.category_streaks)["CATEGORY"]==2 and s2.global_streak==0 and s2.cooldown_state is CooldownState.ACTIVE
def test_daily_weekly_breach_suspends_and_composition_never_amplifies():
 e,_=started();s=e.process(out("1",units="10"),NOW+timedelta(seconds=1),Decimal(".6")).state
 assert s.published_stage is TemporalStage.SUSPENDED and s.final_permission_multiplier==0 and s.final_permission_multiplier<=s.upstream_multiplier
def test_cooldown_expiry_requires_confirmation_and_releases_restricted():
 e,_=started(TemporalQualityConfiguration(streak_watch=1,streak_cooldown=1,cooldown_seconds=10));s=e.process(out("1",units="0"),NOW+timedelta(seconds=1)).state
 assert e.confirm_cooldown_release("A",NOW+timedelta(seconds=5),True).decision is TemporalDecision.NO_ACTION
 assert e.confirm_cooldown_release("A",NOW+timedelta(seconds=12),False).decision is TemporalDecision.BLOCKED
 r=e.confirm_cooldown_release("A",NOW+timedelta(seconds=12),True);assert r.state.cooldown_state is CooldownState.RELEASED and r.state.published_stage is TemporalStage.RESTRICTED
def test_duplicate_future_out_of_order_unknown_lineage_fail_closed():
 e,_=started();one=out("1");assert e.process(one,NOW+timedelta(seconds=1)).decision is TemporalDecision.ACCEPTED;assert e.process(one,NOW+timedelta(seconds=2)).decision is TemporalDecision.NO_ACTION
 assert e.process(out("F",at=NOW+timedelta(seconds=4)),NOW+timedelta(seconds=3)).decision is TemporalDecision.BLOCKED
 assert e.process(out("O",at=NOW),NOW+timedelta(seconds=3)).decision is TemporalDecision.BLOCKED
 assert e.process(out("U",OutcomeClass.UNKNOWN,"0",NOW+timedelta(seconds=3)),NOW+timedelta(seconds=3)).decision is TemporalDecision.BLOCKED
 assert e.process(out("L",at=NOW+timedelta(seconds=3),fp="BAD"),NOW+timedelta(seconds=3)).decision is TemporalDecision.BLOCKED
def test_point_in_time_snapshot():
 e,_=started();e.process(out("1",units="2"),NOW+timedelta(seconds=1));e.process(out("2",units="2",at=NOW+timedelta(seconds=2)),NOW+timedelta(seconds=2));s=e.snapshot("A",NOW+timedelta(seconds=1));assert s.daily_adverse==2 and len(s.event_ids)==1
def test_reconcile_detects_non_amplification_corruption_without_repair():
 e,_=started();s=e.process(out("1"),NOW+timedelta(seconds=1),Decimal(".5")).state;assert e.reconcile("A",NOW).outcome is TemporalReconciliationOutcome.CONSISTENT;e.states["A"]=replace(s,final_permission_multiplier=Decimal("1"));r=e.reconcile("A",NOW);assert r.outcome is TemporalReconciliationOutcome.FAILED_CLOSED and not r.repaired
def test_recovery_replay_and_corruption():
 e,_=started(epoch=2);e.process(out("1",epoch=2),NOW+timedelta(seconds=1));state=e.recovery_state(2);r=TemporalQualityProtectionEngine();assert r.restore(state,2) and r.replay_fingerprint("A")==e.replay_fingerprint("A")
 bad=replace(state.states[0],final_permission_multiplier=Decimal("2"));r2=TemporalQualityProtectionEngine();assert not r2.restore(replace(state,states=(bad,)),2) and r2.recovery_restricted
def test_scope_isolation_bound_audit_trace():
 audit=InMemoryAuditSink();e=TemporalQualityProtectionEngine(TemporalQualityConfiguration(maximum_events_per_scope=1),audit);e.initialize("A","FP-A","D1","W1",NOW);e.initialize("B","FP-B","D1","W1",NOW);r=e.process(out("1"),NOW+timedelta(seconds=1));blocked=e.process(out("2",at=NOW+timedelta(seconds=2)),NOW+timedelta(seconds=2));assert e.states["B"].accepted_count==0 and blocked.decision is TemporalDecision.BLOCKED and r.decision_trace.evaluations and audit.events
def test_worse_sequence_cannot_increase_permission():
 a,_=started();b,_=started();good=a.process(out("G",units="1"),NOW+timedelta(seconds=1)).state;bad=b.process(out("B",units="10"),NOW+timedelta(seconds=1)).state;assert bad.final_permission_multiplier<=good.final_permission_multiplier
def test_safety_surface():
 forbidden={"place_order","submit_trade","broker_login","open_position","close_position","calculate_margin","set_leverage"};assert forbidden.isdisjoint(set(dir(TemporalQualityProtectionEngine())))
