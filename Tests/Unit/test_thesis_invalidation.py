from dataclasses import FrozenInstanceError,replace
from datetime import timedelta
from decimal import Decimal
import pytest

from amrte.infrastructure.local import InMemoryAuditSink
from amrte.risk.invalidation import *
from amrte.risk.sizing import ResearchCapitalContext,RiskSizingEngine
from amrte.risk.adaptive import AdaptiveRiskEngine,ResearchEquityObservation,VolatilityEvidence,VolatilityState,HealthEvidence
from Tests.Unit.test_risk_sizing import strategy_snapshot

def inputs(method=InvalidationMethod.STRUCTURE,direction=ResearchDirection.BULLISH):
    snap=strategy_snapshot();t=snap.as_of_timestamp_utc;signal=snap.preferred_research_signal_id
    profile=InvalidationProfile(f"PROFILE-{direction.name}","S1",None,method,direction,structural_required=method is not InvalidationMethod.ATR_NORMALIZED,atr_allowed=True)
    ref=ResearchReferencePoint.create("100",t,"RESEARCH_SIGNAL_REFERENCE","DATASET-A",snap.instrument_id,"H1")
    structural_value="98" if direction is ResearchDirection.BULLISH else "102"
    structure=StructuralInvalidationEvidence.create(snap,signal,direction,structural_value,"PROMPT6-REFERENCE","STRUCTURE-SNAPSHOT",t,"DATASET-A","H1")
    atr=ATRInvalidationEvidence.create("1",t,"FEATURE-SNAPSHOT","ATR-FEATURE","DATASET-A",snap.instrument_id,"H1")
    return snap,profile,ref,structure,atr

def test_structural_bullish_bearish_symmetry_authority_and_immutability():
    for direction in (ResearchDirection.BULLISH,ResearchDirection.BEARISH):
        result=ThesisInvalidationEngine().evaluate(*inputs(direction=direction));d=result.decision
        assert d.eligibility in (InvalidationEligibility.ELIGIBLE,InvalidationEligibility.ELIGIBLE_WITH_RESTRICTIONS) and d.normalized_distance.normalized_distance==Decimal("2") and d.direction is direction
        with pytest.raises(FrozenInstanceError):d.research_invalidation_boundary=0

def test_unconfirmed_future_structure_and_missing_authoritative_structure_fail_closed():
    snap,profile,ref,structure,atr=inputs();future=snap.as_of_timestamp_utc+timedelta(minutes=1)
    d=ThesisInvalidationEngine().evaluate(snap,profile,ref,replace(structure,confirmed_at_utc=future),atr).decision;assert d.eligibility is InvalidationEligibility.BLOCKED and "INV_STRUCTURE_UNCONFIRMED" in d.reason_codes
    d=ThesisInvalidationEngine().evaluate(snap,profile,ref,None,atr).decision;assert d.eligibility is InvalidationEligibility.BLOCKED and "INV_NO_AUTHORITATIVE_INVALIDATION" in d.reason_codes

def test_atr_method_uses_upstream_value_configurable_multiplier_and_rejects_invalid():
    snap,profile,ref,structure,atr=inputs(InvalidationMethod.ATR_NORMALIZED);cfg=InvalidationConfiguration(atr_multiplier=Decimal("2"));d=ThesisInvalidationEngine(cfg).evaluate(snap,profile,ref,None,atr).decision
    assert d.normalized_distance.normalized_distance==Decimal("2")
    for bad in ("0","-1"):
        d=ThesisInvalidationEngine().evaluate(snap,profile,ref,None,replace(atr,atr_value=Decimal(bad),evidence_id="BAD"+bad)).decision;assert d.eligibility is InvalidationEligibility.BLOCKED

def test_future_atr_and_stale_or_invalid_health_fail_closed():
    snap,profile,ref,_,atr=inputs(InvalidationMethod.ATR_NORMALIZED);future=snap.as_of_timestamp_utc+timedelta(minutes=1)
    assert ThesisInvalidationEngine().evaluate(snap,profile,ref,None,replace(atr,available_at_utc=future)).decision.eligibility is InvalidationEligibility.BLOCKED
    assert ThesisInvalidationEngine().evaluate(snap,profile,ref,None,replace(atr,health=InvalidationHealth.INVALID,evidence_id="INVALID")).decision.eligibility is InvalidationEligibility.BLOCKED

def test_hybrid_structure_plus_atr_and_deterministic_selection():
    snap,profile,ref,structure,atr=inputs(InvalidationMethod.HYBRID);d=ThesisInvalidationEngine().evaluate(snap,profile,ref,structure,atr).decision
    assert d.method is InvalidationMethod.HYBRID and d.normalized_distance.normalized_distance==Decimal("3.5") and "INV_HYBRID_CREATED" in d.reason_codes

def test_explicit_fallback_required_no_silent_rescue():
    snap,profile,ref,structure,atr=inputs();invalid=replace(structure,health=InvalidationHealth.INVALID)
    assert ThesisInvalidationEngine().evaluate(snap,profile,ref,invalid,atr).decision.eligibility is InvalidationEligibility.BLOCKED
    fallback=replace(profile,fallback_allowed=True,fallback_methods=(InvalidationMethod.ATR_NORMALIZED,))
    assert ThesisInvalidationEngine().evaluate(snap,fallback,ref,invalid,atr).decision.eligibility in (InvalidationEligibility.ELIGIBLE,InvalidationEligibility.ELIGIBLE_WITH_RESTRICTIONS)

def test_reference_point_missing_future_invalid_and_lineage_mismatch():
    snap,profile,ref,structure,atr=inputs();engine=ThesisInvalidationEngine()
    assert engine.evaluate(snap,profile,None,structure,atr).decision.eligibility is InvalidationEligibility.BLOCKED
    assert engine.evaluate(snap,profile,replace(ref,available_at_utc=snap.as_of_timestamp_utc+timedelta(seconds=1),reference_point_id="FUTURE"),structure,atr).decision.eligibility is InvalidationEligibility.BLOCKED
    assert engine.evaluate(snap,profile,replace(ref,dataset_id="OTHER",reference_point_id="OTHER"),structure,atr).decision.eligibility is InvalidationEligibility.BLOCKED

def test_minimum_reject_or_widen_and_maximum_reject_without_boundary_distortion():
    snap,profile,ref,structure,atr=inputs();tiny=replace(structure,reference_value=Decimal("99.95"),evidence_id="TINY")
    assert ThesisInvalidationEngine().evaluate(snap,profile,ref,tiny,atr).decision.eligibility is InvalidationEligibility.BLOCKED
    cfg=InvalidationConfiguration(below_minimum_policy=BelowMinimumPolicy.WIDEN_TO_MINIMUM_IF_THESIS_VALID);d=ThesisInvalidationEngine(cfg).evaluate(snap,profile,ref,tiny,atr).decision;assert d.normalized_distance.normalized_distance==cfg.minimum_distance
    wide=replace(structure,reference_value=Decimal("80"),evidence_id="WIDE");d=ThesisInvalidationEngine().evaluate(snap,profile,ref,wide,atr).decision;assert d.eligibility is InvalidationEligibility.BLOCKED and "INV_DISTANCE_TOO_LARGE" in d.reason_codes

def test_numerical_validation_nan_infinity_zero_and_negative():
    with pytest.raises(ValueError):ResearchReferencePoint.create("NaN",strategy_snapshot().as_of_timestamp_utc,"X","D","I","H1")
    with pytest.raises(ValueError,match="INV_DISTANCE_CONFIGURATION_INVALID"):ThesisInvalidationEngine(InvalidationConfiguration(minimum_distance=Decimal("0")))
    with pytest.raises(ValueError,match="INV_ATR_MULTIPLIER_INVALID"):ThesisInvalidationEngine(InvalidationConfiguration(atr_multiplier=Decimal("-1")))

def test_research_friction_policies_and_buffer_never_increase_risk():
    snap,profile,ref,structure,atr=inputs();cfg=InvalidationConfiguration(friction_enabled=True,missing_friction_policy=MissingFrictionPolicy.BLOCK)
    assert ThesisInvalidationEngine(cfg).evaluate(snap,profile,ref,structure,atr).decision.eligibility is InvalidationEligibility.BLOCKED
    cfg=InvalidationConfiguration(friction_enabled=True,missing_friction_policy=MissingFrictionPolicy.USE_CONSERVATIVE_CONFIGURED_VALUE,conservative_friction_buffer=Decimal(".5"));d=ThesisInvalidationEngine(cfg).evaluate(snap,profile,ref,structure,atr).decision;assert d.normalized_distance.normalized_distance==Decimal("2.5")

def test_volatility_adjustment_bounded_future_and_extreme_rejected():
    snap,profile,ref,structure,atr=inputs();t=snap.as_of_timestamp_utc;cfg=InvalidationConfiguration(volatility_adjustment_enabled=True,maximum_volatility_allowance=Decimal("1"));v=VolatilityAdjustment("V",Decimal(".5"),"FEATURE",t,InvalidationHealth.HEALTHY,cfg.configuration_snapshot_id)
    assert ThesisInvalidationEngine(cfg).evaluate(snap,profile,ref,structure,atr,volatility=v).decision.normalized_distance.normalized_distance==Decimal("2.5")
    assert ThesisInvalidationEngine(cfg).evaluate(snap,profile,ref,structure,atr,volatility=replace(v,normalized_allowance=Decimal("2"),adjustment_id="EXTREME")).decision.eligibility is InvalidationEligibility.BLOCKED
    assert ThesisInvalidationEngine(cfg).evaluate(snap,profile,ref,structure,atr,volatility=replace(v,available_at_utc=t+timedelta(seconds=1),adjustment_id="FUTURE")).decision.eligibility is InvalidationEligibility.BLOCKED

@pytest.mark.parametrize("strategy,variant",[("S1",None),("S2","IMMEDIATE"),("S2","RETEST"),("S3","RANGE")])
def test_strategy_profiles_preserve_upstream_thesis_ownership(strategy,variant):
    snap,profile,ref,structure,atr=inputs();profile=replace(profile,strategy_id=strategy,strategy_variant=variant,profile_id=f"{strategy}-{variant}")
    d=ThesisInvalidationEngine().evaluate(snap,profile,ref,structure,atr).decision;assert d.strategy_id==strategy and d.strategy_variant==variant and d.structural_evidence_id==structure.evidence_id

def test_invalidation_event_condition_timing_immutability_and_duplicate_prevention():
    snap,profile,ref,structure,atr=inputs();engine=ThesisInvalidationEngine();d=engine.evaluate(snap,profile,ref,structure,atr).decision;t=snap.as_of_timestamp_utc
    assert engine.observe(d,"99",t,t,("OBS0",)) is None
    event=engine.observe(d,"97",t,t+timedelta(minutes=1),("OBS1",));same=engine.observe(d,"97",t,t+timedelta(minutes=1),("OBS1",))
    assert event.event_id==same.event_id and len(engine.ledger.events)==1 and event.confirmed_at_utc>event.observed_at_utc
    with pytest.raises(FrozenInstanceError):event.lifecycle=InvalidationLifecycle.ACTIVE

def test_expired_is_distinct_from_invalidated_and_superseded():
    snap,profile,ref,structure,atr=inputs();engine=ThesisInvalidationEngine();d=engine.evaluate(snap,profile,ref,structure,atr).decision
    engine.ledger.expire(d.decision_id);assert engine.ledger.states[d.decision_id] is InvalidationLifecycle.EXPIRED
    engine.ledger.supersede(d.decision_id);assert engine.ledger.states[d.decision_id] is InvalidationLifecycle.SUPERSEDED

def test_prompt17_and_prompt18_reconciliation_and_distance_monotonicity():
    snap,profile,ref,structure,atr=inputs();engine=ThesisInvalidationEngine();inv=engine.evaluate(snap,profile,ref,structure,atr);t=snap.as_of_timestamp_utc;cap=ResearchCapitalContext.create("10000",t)
    equity=(ResearchEquityObservation.create("10000",t),);vol=VolatilityEvidence("VOL",VolatilityState.NORMAL,t,"FEATURES","TREND");sh=HealthEvidence("SH","HEALTHY",t,"SIGNAL","STRATEGY");dh=HealthEvidence("DH","HEALTHY",t,"INTEL","DATA")
    reconciled=engine.reconcile(inv,snap,cap,equity,vol,sh,dh,RiskSizingEngine(),AdaptiveRiskEngine());assert reconciled.final_simulated_exposure>0 and reconciled.final_simulated_risk<=reconciled.prompt18.decision.adaptive_risk_amount<=reconciled.prompt17.risk_budget.base_risk_amount
    wider=engine.evaluate(snap,replace(profile,profile_id="WIDER"),ref,replace(structure,reference_value=Decimal("96"),evidence_id="WIDER"),atr);wide_result=engine.reconcile(wider,snap,cap,equity,vol,sh,dh,RiskSizingEngine(),AdaptiveRiskEngine());assert wide_result.final_simulated_exposure<=reconciled.final_simulated_exposure

def test_missing_invalidation_always_zero_exposure():
    snap,profile,ref,structure,atr=inputs();inv=ThesisInvalidationEngine().evaluate(snap,profile,ref,None,atr);cap=ResearchCapitalContext.create("10000",snap.as_of_timestamp_utc)
    r=ThesisInvalidationEngine().reconcile(inv,snap,cap,(),None,None,None,RiskSizingEngine(),AdaptiveRiskEngine());assert r.final_simulated_exposure==0 and r.prompt17 is None

def test_deterministic_cache_trace_observability_recovery_and_bounded_ledger():
    snap,profile,ref,structure,atr=inputs();audit=InMemoryAuditSink();cfg=InvalidationConfiguration(maximum_cache_entries=1,maximum_decisions=1,maximum_candidates=2,maximum_ledger_entries=4);engine=ThesisInvalidationEngine(cfg,audit);a=engine.evaluate(snap,profile,ref,structure,atr);b=engine.evaluate(snap,profile,ref,structure,atr)
    assert a is b and a.decision.decision_id==b.decision.decision_id and a.decision_trace.outcome is DecisionOutcome.ACCEPTED
    state=engine.recovery_state();restored=ThesisInvalidationEngine(cfg);assert restored.restore(state) and not restored.restore({"engine_version":"OLD"})
    assert len(engine._cache)<=1 and len(engine._decisions)<=1 and len(engine._candidates)<=2 and {x for x,_ in audit.events}>={"invalidation_evaluation_started","invalidation_evaluation_completed"}

def test_safety_surface_has_no_executable_stop_or_broker_capabilities():
    forbidden={"connect_broker","broker_login","place_stop_order","modify_order","modify_position","close_position","calculate_margin","set_leverage","submit_order","set_take_profit","trail_stop"}
    assert forbidden.isdisjoint(set(dir(ThesisInvalidationEngine)))
