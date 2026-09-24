from dataclasses import replace
from time import perf_counter
from Tests.Unit.test_regime import upstream
from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.market.regime import RegimeConfiguration,RegimeEngine
from Tests.Unit.test_regime import NOW


def test_1000_snapshot_bounded_regime_performance():
    engine=RegimeEngine(FixedClock(NOW),InMemoryAuditSink(),RegimeConfiguration(confirmation_observations=1,minimum_classification_margin=0,maximum_history=50,cooldown_observations=0))
    began=perf_counter()
    for index in range(1000):
        identity=f"MD{index}"; m,s,f=upstream(identity=identity)
        engine.analyze(m,replace(s,source_market_data_snapshot_id=identity),replace(f,source_market_data_snapshot_id=identity))
    elapsed=perf_counter()-began
    assert len(engine.history)==50 and elapsed<5

