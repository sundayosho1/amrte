from dataclasses import replace
from Tests.Unit.test_portfolio_risk import registry,request,NOW

def test_prompt22_bounded_portfolio_load():
    r=registry(maximum_records=64,maximum_reservations=64,maximum_snapshots=64,maximum_ledger_events=128,maximum_cache_entries=64)
    for i in range(200):r.assess(request(str(i),".001"))
    assert len(r.reservations)<=64 and len(r.snapshots)<=64 and len(r.ledger.events)<=128
