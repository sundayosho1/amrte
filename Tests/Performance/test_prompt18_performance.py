from datetime import timedelta
from dataclasses import replace
from amrte.risk.adaptive import *
from Tests.Unit.test_adaptive_risk import context

def test_bounded_prompt18_multi_instrument_style_load():
    base,equity,vol,sh,dh=context();cfg=AdaptiveRiskConfiguration(maximum_cache_entries=64,maximum_decisions=64,maximum_modifier_results=64,maximum_transitions=64);engine=AdaptiveRiskEngine(cfg)
    for i in range(200):
        t=base.exposure_decision.as_of_timestamp_utc;history=(ResearchEquityObservation.create("10000",t),ResearchEquityObservation.create(str(10000-(i%5)*300),t,dataset_id="FICTIONAL_RESEARCH"));engine.evaluate(base,history,replace(vol,evidence_id=f"V{i}",state=(VolatilityState.NORMAL,VolatilityState.ELEVATED,VolatilityState.HIGH)[i%3]),replace(sh,evidence_id=f"S{i}"),replace(dh,evidence_id=f"D{i}"))
    assert len(engine._cache)<=64 and len(engine._decisions)<=64 and len(engine._modifiers)<=64 and len(engine._transitions)<=64
