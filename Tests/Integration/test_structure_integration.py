from datetime import datetime, timedelta, timezone

from amrte.core.clock import FixedClock
from amrte.infrastructure.local import InMemoryAuditSink, ProhibitedExecutionProvider
from amrte.market.models import BarState, DataValidity, MarketDataSnapshot, NormalizedBar, SpreadHealth, SpreadOrigin, SpreadState, DataHealth, SynchronizationStatus
from amrte.market.structure import MarketStructureEngine, StructureConfiguration


def test_structure_consumes_prompt5_snapshot_and_audits_without_execution():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc); audit = InMemoryAuditSink()
    series = tuple(NormalizedBar("FICTIONAL_ALPHA", frame, start+timedelta(minutes=15*i),
        start+timedelta(minutes=15*(i+1)), value, value+1, value-1, value+.2,
        bar_state=BarState.CLOSED_BAR, validity=DataValidity.VALID, bar_id=f"{frame}-{i}")
        for frame in ("H4","H1","M15") for i,value in enumerate((1,3,1,4,2,5,3,6,4)))
    grouped = {frame: tuple(item for item in series if item.timeframe == frame) for frame in ("H4","H1","M15")}
    spread = SpreadState(None,None,None,None,None,SpreadHealth.UNAVAILABLE,SpreadOrigin.UNAVAILABLE)
    source = MarketDataSnapshot("MD",start,grouped["M15"][-1].close_time,"EXP","DS","FP","FICTIONAL_ALPHA",
        spread,grouped["H4"],grouped["H1"],grouped["M15"],SynchronizationStatus.SYNCHRONIZED,
        DataHealth.HEALTHY,100,{},"CFG",0)
    engine = MarketStructureEngine(FixedClock(start+timedelta(days=1)),audit,
        StructureConfiguration(left_bars=1,right_bars=1,minimum_structural_evidence=1))
    result = engine.analyze(source)
    assert result is not None and result.source_market_data_snapshot_id == "MD"
    assert {name for name,_ in audit.events} >= {"structure_analysis_started","structure_snapshot_created"}
    assert not ProhibitedExecutionProvider(audit).submit({"structure_snapshot_id":result.structure_snapshot_id}).success

