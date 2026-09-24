from dataclasses import replace
from decimal import Decimal
from amrte.risk.invalidation import *
from Tests.Unit.test_thesis_invalidation import inputs

def test_prompt19_bounded_research_load():
    snap,profile,ref,structure,atr=inputs();cfg=InvalidationConfiguration(maximum_candidates=64,maximum_decisions=64,maximum_events=64,maximum_ledger_entries=128,maximum_cache_entries=64);engine=ThesisInvalidationEngine(cfg)
    for i in range(200):engine.evaluate(snap,replace(profile,profile_id=f"P{i}"),ref,replace(structure,evidence_id=f"S{i}",reference_value=Decimal("98")-Decimal(i%5)/10),replace(atr,evidence_id=f"A{i}"))
    assert len(engine._cache)<=64 and len(engine._decisions)<=64 and len(engine._candidates)<=64 and len(engine.ledger.decisions)<=128
