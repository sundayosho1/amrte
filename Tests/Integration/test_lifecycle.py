from datetime import datetime, timezone

from amrte.app import build_engine
from amrte.core.capabilities import CapabilityRegistry
from amrte.core.clock import FixedClock
from amrte.core.config import LayeredConfigurationProvider
from amrte.core.engine import AMRTEEngine
from amrte.core.health import HealthService
from amrte.core.services import ServiceRegistry
from amrte.core.state import StateMachine
from amrte.core.types import SystemState
from amrte.infrastructure.local import InMemoryAuditSink, InMemoryStateRepository, ProhibitedExecutionProvider, SeededRandomSource


def test_defensive_protection_suspension_flow():
    engine = build_engine()
    assert engine.start().success
    for target in (SystemState.DEFENSIVE, SystemState.PROTECT, SystemState.SUSPENDED):
        assert engine.state_machine.transition(target, "integration flow").success


def test_initialization_failure_rolls_to_error():
    engine = build_engine("unsupported")
    assert engine.state_machine.state is SystemState.ERROR
    assert any(name == "startup_failure" for name, _ in engine.audit.events)


def test_missing_service_fails_closed():
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    audit = InMemoryAuditSink()
    registry = ServiceRegistry()
    registry.register("clock", clock)
    registry.register("audit", audit)
    registry.register("configuration", LayeredConfigurationProvider(clock))
    registry.register("state", InMemoryStateRepository())
    registry.register("execution", ProhibitedExecutionProvider(audit))
    registry.register("health", HealthService())
    engine = AMRTEEngine(registry, StateMachine(clock, audit), CapabilityRegistry(), audit)
    result = engine.initialize("RESEARCH")
    assert not result.success and engine.state_machine.state is SystemState.ERROR


def test_persistence_failure_blocks_ready():
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    audit = InMemoryAuditSink()
    registry = ServiceRegistry()
    services = {
        "clock": clock, "audit": audit,
        "configuration": LayeredConfigurationProvider(clock),
        "state": InMemoryStateRepository(available=False),
        "execution": ProhibitedExecutionProvider(audit),
        "health": HealthService(), "random": SeededRandomSource(1),
    }
    for name, service in services.items(): registry.register(name, service)
    engine = AMRTEEngine(registry, StateMachine(clock, audit), CapabilityRegistry(), audit)
    assert not engine.initialize("RESEARCH").success
    assert engine.state_machine.state is SystemState.ERROR

