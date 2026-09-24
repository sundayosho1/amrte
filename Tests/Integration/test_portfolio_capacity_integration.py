from datetime import timedelta
from decimal import Decimal
from Tests.Unit.test_portfolio_risk import registry,request,admit,NOW,states
from amrte.portfolio.risk import *

def test_multi_instrument_multi_strategy_capacity_pipeline():
    r=registry(reduction_policy=ReductionPolicy.REDUCE_TO_CAPACITY);admit(r,request("S1",".4",strategy="S1",family="TREND"));admit(r,request("S2I",".3",instrument="FICTIONAL_AC",strategy="S2",family="BREAKOUT",variant="IMMEDIATE"));decision=r.assess(request("S3",".5",strategy="S3",family="MEAN_REVERSION"));assert decision.outcome is AdmissionOutcome.ALLOW_REDUCED and decision.approved_exposure==Decimal(".30")
    s=r.snapshot(NOW);assert s.gross_exposure==Decimal(".7") and s.reserved_research_risk==Decimal(".3") and s.available_risk_capacity==0

def test_partial_exit_releases_only_effective_capacity_and_restart_preserves_reservation():
    r=registry();_,record=admit(r,request("A",".7"));reserved=r.assess(request("B",".3"));saved=r.recovery_state();restarted=registry();assert restarted.restore(saved) and restarted.assess(request("C",".1")).outcome is AdmissionOutcome.BLOCK
    exit_state,protective=states(record,".4",NOW+timedelta(minutes=1));assert restarted.reconcile(record.exposure_record_id,exit_state,protective,NOW+timedelta(minutes=1),current_risk=Decimal(".4"))[0]
    assert restarted.snapshot(NOW).total_open_research_risk==Decimal(".7")
    assert restarted.snapshot(NOW+timedelta(minutes=1)).total_open_research_risk==Decimal(".4") and reserved.reservation_id in restarted.reservations
