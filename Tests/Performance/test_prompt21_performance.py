from dataclasses import replace
from Tests.Unit.test_protection import context,evaluate

def test_prompt21_bounded_research_protection_load():
    engine,p,snap,inv,plan,state,ref,initial=context()
    for i in range(200):
        profile=replace(p,profile_id=f"P{i}")
        evaluate(engine,profile,snap,inv,plan,state,ref,initial,"103",oid=f"O{i}")
    assert len(engine._versions)<=engine.configuration.maximum_versions and len(engine.ledger.versions)<=engine.configuration.maximum_ledger_entries
