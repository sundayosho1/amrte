from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from amrte.analytics.performance import *
from amrte.dashboard.monitoring import *
from amrte.infrastructure.local import InMemoryAuditSink

NOW=datetime(2026,9,21,10,tzinfo=timezone.utc)


def analytics():
    config=AnalyticsConfiguration(limited_sample=1,adequate_sample=2,strong_sample=3,rolling_minimum=1)
    engine=ResearchPerformanceAnalyticsEngine(config)
    opened=NOW-timedelta(hours=1);closed=opened+timedelta(minutes=5);known=closed+timedelta(seconds=1)
    o=ResearchOutcomeObservation.create("H","S1","1","V1","F1","SUB","CAT","REG","SES","TF","1",opened,closed,known,"DATA-A")
    engine.ingest(o,NOW);q=ResearchAnalyticsQuery.create(AnalyticsScope.GLOBAL,NOW-timedelta(days=1),NOW,NOW,"DATA-A");snap=engine.calculate(q);return engine.phase_viii_snapshot(snap,phase_vii_safety_snapshot_id="P7")


def source(module,state="HEALTHY",at=NOW,**payload):
    return DashboardSourceSnapshot(module,f"{module}-SNAP",at,"DATA-A","NEUTRAL_ANALYTICS_DEFAULT",0,state,state,(),f"TRACE-{module}",tuple(payload.items()))


def sources(**overrides):
    base={name:source(name) for name in DashboardSnapshotAggregator.REQUIRED}
    base["DATA"]=source("DATA",freshness="FRESH",integrity="VALID",last_valid=NOW)
    base["REGIME"]=source("REGIME",current_regime="NEUTRAL_REGIME",confidence=Decimal(".8"),since=NOW-timedelta(hours=2))
    base["SESSION"]=source("SESSION",session="RESEARCH_SESSION",research_clock=NOW,calendar_context="UTC")
    base["PROFILE"]=source("PROFILE",name="DEFAULT",version="1",activated_at=NOW-timedelta(days=1))
    base["LIFECYCLE"]=source("LIFECYCLE",state_counts=(("ACTIVE",2),("COMPLETED",3)),hypothesis_references=("H1","H2"))
    for name in ("RELIABILITY","TEMPORAL","SYSTEM_SAFETY"):base[name]=source(name,permission_multiplier=Decimal("1"),cooldown_state="INACTIVE")
    base.update(overrides);return tuple(base.values())


def snapshot(aggregator=None,src=None,generated=NOW):
    a=aggregator or DashboardSnapshotAggregator();return a,a.aggregate(src or sources(),analytics(),NOW,generated)


def test_configuration_validation():
    with pytest.raises(ValueError):DashboardSnapshotAggregator(DashboardConfiguration(stale_after=timedelta(0)))
    with pytest.raises(ValueError):DashboardSnapshotAggregator(DashboardConfiguration(maximum_alerts=0))


def test_master_snapshot_is_immutable_deterministic_and_research_only():
    a,first=snapshot();second=a.aggregate(sources(),analytics(),NOW,NOW)
    assert first.snapshot_id==second.snapshot_id and first.system_status.research_mode=="RESEARCH-ONLY"
    with pytest.raises(FrozenInstanceError):first.dataset_fingerprint="OTHER"


def test_authoritative_cards_bind_without_recalculation():
    phase8=analytics();a=DashboardSnapshotAggregator();snap=a.aggregate(sources(),phase8,NOW,NOW)
    assert snap.research_performance_summary.summary is phase8.global_performance_summary
    assert snap.market_regime.current_regime=="NEUTRAL_REGIME"
    assert snap.session_context.calendar_context=="UTC"
    assert snap.active_research_profile.profile_name=="DEFAULT"


def test_severe_protection_dominates_healthy_modules_and_permission_is_minimum():
    restricted=source("SYSTEM_SAFETY","EMERGENCY_STOP",permission_multiplier=Decimal("0"))
    a,snap=snapshot(src=sources(SYSTEM_SAFETY=restricted))
    assert snap.system_status.state is DashboardStatus.SUSPENDED
    assert snap.protection_status.effective_research_permission==ZERO
    assert snap.alert_summary.critical_count>=1


def test_missing_source_and_conflicting_lineage_are_degraded():
    incomplete=tuple(x for x in sources() if x.source_module!="QUALITY")
    a,snap=snapshot(src=incomplete);assert snap.system_status.state is DashboardStatus.DEGRADED
    conflict=list(sources());conflict[0]=replace(conflict[0],dataset_fingerprint="OTHER")
    _,bad=snapshot(src=tuple(conflict));assert bad.system_status.state is DashboardStatus.DEGRADED


def test_future_source_and_stale_snapshot_are_not_presented_as_current():
    future=list(sources());future[0]=replace(future[0],as_of_time_utc=NOW+timedelta(seconds=1))
    _,bad=snapshot(src=tuple(future));assert "DASHBOARD_TEMPORAL_OR_EPOCH_MISMATCH" in bad.system_status.reason_codes
    _,stale=snapshot(generated=NOW+timedelta(hours=1));assert stale.system_status.state is DashboardStatus.STALE and stale.system_status.stale


def test_lifecycle_workflow_quality_and_data_health_views():
    _,snap=snapshot()
    assert snap.lifecycle_summary.total==5
    assert snap.workflow_health=="HEALTHY" and snap.observation_quality=="HEALTHY"
    assert snap.data_health.freshness=="FRESH" and snap.data_health.integrity=="VALID"


def test_strategy_health_panel_uses_supplied_authoritative_items():
    item={"strategy_id":"METHOD-A","version":"1","variant":"V","health":"HEALTHY","published_health":"HEALTHY","permission_multiplier":".5","observation_count":4,"sample_adequacy":"ADEQUATE","reason_codes":("UPSTREAM",)}
    _,snap=snapshot(src=sources(STRATEGY_HEALTH=source("STRATEGY_HEALTH",items=(item,))))
    assert len(snap.strategy_health_summary)==1
    assert snap.strategy_health_summary[0].permission_multiplier==Decimal(".5")


def test_alert_deduplication_acknowledgement_does_not_resolve_source():
    degraded=source("QUALITY","DEGRADED")
    a,snap=snapshot(src=sources(QUALITY=degraded));first_id=snap.alert_summary.alert_ids[0]
    a.aggregate(sources(QUALITY=degraded),analytics(),NOW,NOW)
    assert a.alerts[first_id].occurrence_count==2
    assert a.acknowledge_alert(first_id,"operator",NOW)
    assert a.alerts[first_id].acknowledgement_state is AlertAcknowledgement.ACKNOWLEDGED
    assert a.alerts[first_id].resolution_state is AlertResolution.ACTIVE
    assert a.resolve_alert_from_source(first_id,NOW) and a.alerts[first_id].resolution_state is AlertResolution.RESOLVED_BY_SOURCE


def control(action,snap,version=0,confirmed=True,reason="verified",nonce=""):
    return DashboardControlRequest.create(action,NOW,"operator","GLOBAL",version,snap.configuration_snapshot_id,reason,confirmed,nonce)


def test_read_only_default_denies_sensitive_control():
    a,snap=snapshot();result=a.process_control(control(ControlAction.PAUSE_RESEARCH,snap),{DashboardPermission.VIEW_DASHBOARD},snap)
    assert result.outcome is ControlOutcome.REJECTED and not a.paused


def test_pause_requires_confirmation_reason_and_permission():
    a,snap=snapshot();permission={DashboardPermission.PAUSE_RESEARCH}
    denied=a.process_control(control(ControlAction.PAUSE_RESEARCH,snap,confirmed=False,reason="",nonce="A"),permission,snap)
    accepted=a.process_control(control(ControlAction.PAUSE_RESEARCH,snap,nonce="B"),permission,snap)
    assert denied.outcome is ControlOutcome.REJECTED
    assert accepted.outcome is ControlOutcome.ACCEPTED and a.paused and a.state_version==1


def test_resume_cannot_bypass_authoritative_restriction():
    a,snap=snapshot();a.paused=True
    result=a.process_control(control(ControlAction.RESUME_RESEARCH,snap),{DashboardPermission.RESUME_RESEARCH},snap,safety_permission=Decimal(".5"))
    assert result.outcome is ControlOutcome.REJECTED and a.paused


def test_resume_healthy_state_and_no_action_semantics():
    a,snap=snapshot();a.paused=True
    resumed=a.process_control(control(ControlAction.RESUME_RESEARCH,snap,nonce="A"),{DashboardPermission.RESUME_RESEARCH},snap)
    again=a.process_control(control(ControlAction.RESUME_RESEARCH,snap,version=1,nonce="B"),{DashboardPermission.RESUME_RESEARCH},snap)
    assert resumed.outcome is ControlOutcome.ACCEPTED and not a.paused
    assert again.outcome is ControlOutcome.NO_ACTION


def test_control_idempotency_optimistic_concurrency_and_config_conflict():
    a,snap=snapshot();request=control(ControlAction.PAUSE_RESEARCH,snap)
    first=a.process_control(request,{DashboardPermission.PAUSE_RESEARCH},snap);second=a.process_control(request,{DashboardPermission.PAUSE_RESEARCH},snap)
    assert first==second and a.state_version==1
    stale=a.process_control(control(ControlAction.PAUSE_RESEARCH,snap,version=0,nonce="S"),{DashboardPermission.PAUSE_RESEARCH},snap);assert stale.outcome is ControlOutcome.STALE_REQUEST
    bad_snap=replace(snap,configuration_snapshot_id="OTHER");conflict=a.process_control(control(ControlAction.REFRESH,bad_snap,version=1,nonce="C"),{DashboardPermission.VIEW_DASHBOARD},snap);assert conflict.outcome is ControlOutcome.CONFLICT


def test_preferences_are_non_authoritative_and_bounded():
    a=DashboardSnapshotAggregator(DashboardConfiguration(maximum_preferences=1));a.set_preference(DashboardPreference("A","GRID",("STATUS",),"LIGHT",30,NOW));a.set_preference(DashboardPreference("B","LIST",("ALERTS",),"DARK",60,NOW))
    assert tuple(a.preferences)==("B",)
    with pytest.raises(ValueError):a.set_preference(DashboardPreference("","GRID",(),"LIGHT",-1,NOW))


def test_export_contains_provenance_not_financial_fields():
    _,snap=snapshot();export=DashboardSnapshotAggregator().export_view(snap)
    assert export["snapshot_id"]==snap.snapshot_id and export["research_mode"]=="RESEARCH-ONLY"
    assert {"balance","equity","monetary_pnl","positions"}.isdisjoint(export)


def test_recovery_restart_and_replay_preserve_pause_alerts_and_controls():
    a,snap=snapshot(src=sources(QUALITY=source("QUALITY","DEGRADED")));a.process_control(control(ControlAction.PAUSE_RESEARCH,snap),{DashboardPermission.PAUSE_RESEARCH},snap);state=a.recovery_state(3);fingerprint=a.replay_fingerprint()
    restored=DashboardSnapshotAggregator();assert restored.restore(state,3)
    assert restored.paused and restored.replay_fingerprint()==fingerprint
    invalid=DashboardSnapshotAggregator();assert not invalid.restore(replace(state,recovery_epoch=4),3) and invalid.recovery_restricted


def test_decision_trace_inspector_is_read_only_and_audit_records_controls():
    audit=InMemoryAuditSink();a=DashboardSnapshotAggregator(audit=audit);snap=a.aggregate(sources(),analytics(),NOW,NOW);result=a.process_control(control(ControlAction.PAUSE_RESEARCH,snap),{DashboardPermission.PAUSE_RESEARCH},snap)
    assert result.trace_id and any(x[0]=="dashboard_control_processed" for x in audit.events)
    trace=DecisionTrace(result.trace_id,result.request_id,NOW,(),DecisionOutcome.ACCEPTED,"OK",NOW,None)
    assert a.inspect_trace(trace) is trace


def test_refresh_is_side_effect_safe_and_history_is_bounded():
    a=DashboardSnapshotAggregator(DashboardConfiguration(maximum_snapshots=1));first=a.aggregate(sources(),analytics(),NOW,NOW);second=a.aggregate(sources(),analytics(),NOW+timedelta(seconds=1),NOW+timedelta(seconds=1))
    assert len(a.snapshots)==1 and first.snapshot_id!=second.snapshot_id


def test_unknown_states_never_become_healthy():
    unknown=source("REGIME","UNKNOWN")
    _,snap=snapshot(src=sources(REGIME=unknown));assert snap.system_status.state is DashboardStatus.UNKNOWN
    assert snap.market_regime.current_regime=="UNKNOWN"


def test_dashboard_surface_has_no_trading_or_financial_controls():
    forbidden={"place_order","submit_trade","buy","sell","open_position","close_position","set_leverage","calculate_margin","account_balance","force_resume","override_safety","clear_circuit","bypass_cooldown"}
    assert forbidden.isdisjoint(set(dir(DashboardSnapshotAggregator)))

