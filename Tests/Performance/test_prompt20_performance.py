from dataclasses import replace
from decimal import Decimal
from amrte.risk.exit_management import *
from Tests.Unit.test_exit_management import upstream,policy

def test_prompt20_bounded_research_exit_load():
    snap,inv,rec,ref=upstream();cfg=ExitManagementConfiguration(maximum_plans=64,maximum_targets=64,maximum_events=64,maximum_ledger_entries=128,maximum_cache_entries=64);engine=ResearchExitManagementEngine(cfg)
    for i in range(200):engine.create_plan(snap,inv,rec,ref,replace(policy(),policy_id=f"P{i}"))
    assert len(engine._plans)<=64 and len(engine._targets)<=64 and len(engine._cache)<=64 and len(engine.ledger.plans)<=128
