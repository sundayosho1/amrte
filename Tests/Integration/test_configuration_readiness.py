from amrte.app import build_engine
from amrte.core.types import SystemState, ValidationStatus


def test_master_configuration_integrates_with_startup_readiness():
    engine = build_engine("RESEARCH")
    assert engine.state_machine.state is SystemState.READY
    assert engine.configuration.validation_status is ValidationStatus.VALID
    assert engine.configuration.configuration_hash
    assert engine.configuration.snapshot_id


def test_startup_configuration_keeps_execution_unavailable():
    engine = build_engine("RESEARCH")
    values = engine.configuration.values
    assert values["execution.available"] is False
    assert values["broker.live_execution"] is False
    assert values["broker.demo_execution"] is False

