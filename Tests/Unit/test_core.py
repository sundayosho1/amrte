from datetime import datetime, timezone

import pytest

from amrte.app import build_engine
from amrte.core.capabilities import CapabilityRegistry
from amrte.core.clock import FixedClock
from amrte.core.config import LayeredConfigurationProvider
from amrte.core.environment import detect_environment
from amrte.core.health import HealthService
from amrte.core.identity import deterministic_id, normalize_instrument
from amrte.core.numeric import bounded_percentage, require_finite, safe_divide, safe_round
from amrte.core.services import ServiceRegistry
from amrte.core.state import StateMachine
from amrte.core.types import Capability, HealthStatus, RuntimeEnvironment, SystemState
from amrte.infrastructure.local import InMemoryAuditSink, ProhibitedExecutionProvider, SeededRandomSource


def fixtures():
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    audit = InMemoryAuditSink()
    return clock, audit


def test_environment_detection():
    assert detect_environment("research") is RuntimeEnvironment.RESEARCH
    assert detect_environment("live") is RuntimeEnvironment.UNKNOWN


def test_valid_and_illegal_state_transitions():
    clock, audit = fixtures()
    machine = StateMachine(clock, audit)
    assert machine.transition(SystemState.READY, "ok").success
    rejected = machine.transition(SystemState.PROTECT, "skip")
    assert not rejected.success and machine.state is SystemState.READY
    assert rejected.error.code == "ILLEGAL_STATE_TRANSITION"


def test_configuration_precedence_and_provenance():
    clock, _ = fixtures()
    provider = LayeredConfigurationProvider(clock, {
        "global": {"x": 1}, "profile": {"x": 2}, "runtime": {"x": 3}
    })
    result = provider.load()
    assert result.success and result.value.values["x"] == 3
    assert result.value.provenance["x"] == "runtime"
    assert result.value.values["broker.live_execution"] is False


def test_hard_safety_cannot_be_overridden():
    clock, _ = fixtures()
    result = LayeredConfigurationProvider(clock, {"runtime": {"broker.live_execution": True}}).load()
    assert not result.success and result.error.code == "HARD_SAFETY_OVERRIDE"


def test_fictional_instrument_normalization():
    identity = normalize_instrument("fictional alpha.v1", "fictional_alpha")
    assert identity.canonical == "FICTIONAL_ALPHA"
    assert identity.provider_symbol == "fictional alpha.v1"
    assert identity.metadata_status is HealthStatus.HEALTHY


def test_deterministic_ids_are_stable_and_separated():
    first = deterministic_id("decision", "instance-1", "fictional-alpha", 42)
    assert first == deterministic_id("decision", "instance-1", "fictional-alpha", 42)
    assert first != deterministic_id("signal", "instance-1", "fictional-alpha", 42)


def test_registry_rejects_missing_duplicate_and_mutation_after_seal():
    registry = ServiceRegistry()
    registry.register("clock", object())
    with pytest.raises(ValueError): registry.register("clock", object())
    with pytest.raises(KeyError): registry.require("missing")
    registry.seal()
    with pytest.raises(RuntimeError): registry.register("late", object())


def test_readiness_requires_every_mandatory_component():
    report = HealthService().assess({"clock": HealthStatus.HEALTHY}, ("clock", "state"))
    assert not report.ready and report.reasons == ("state:UNKNOWN",)


def test_capabilities_permanently_exclude_broker_execution():
    registry = CapabilityRegistry({Capability.LIVE_BROKER_EXECUTION_AVAILABLE,
                                   Capability.DEMO_BROKER_EXECUTION_AVAILABLE,
                                   Capability.PERSISTENCE_AVAILABLE})
    assert registry.has(Capability.PERSISTENCE_AVAILABLE)
    assert not registry.has(Capability.LIVE_BROKER_EXECUTION_AVAILABLE)
    assert not registry.has(Capability.DEMO_BROKER_EXECUTION_AVAILABLE)


def test_execution_provider_rejects_every_request_and_audits():
    _, audit = fixtures()
    result = ProhibitedExecutionProvider(audit).submit({"anything": "rejected"})
    assert not result.success and result.error.code == "CAPABILITY_NOT_AVAILABLE"
    assert audit.events[-1][0] == "prohibited_capability_requested"


def test_numerical_safety():
    assert bounded_percentage(50) == 50
    assert safe_divide(8, 2) == 4
    assert str(safe_round(2.345, 2)) == "2.34"
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError): require_finite(value)
    with pytest.raises(ZeroDivisionError): safe_divide(1, 0)
    with pytest.raises(ValueError): bounded_percentage(101)


def test_seeded_random_is_reproducible():
    a, b = SeededRandomSource(77), SeededRandomSource(77)
    assert a.seed == b.seed == 77
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]


def test_effective_configuration_is_immutable():
    clock, _ = fixtures()
    snapshot = LayeredConfigurationProvider(clock).load().value
    with pytest.raises(TypeError): snapshot.values["new"] = 1


def test_valid_initialization_and_shutdown():
    engine = build_engine("RESEARCH")
    assert engine.state_machine.state is SystemState.READY
    assert engine.start().success
    stopped = engine.shutdown("test complete")
    assert stopped.success and engine.state_machine.state is SystemState.STOPPED
    assert engine.audit.flushed


def test_invalid_environment_fails_closed():
    engine = build_engine("LIVE")
    assert engine.state_machine.state is SystemState.ERROR
    assert not engine.start().success


def test_timeframe_defaults_are_configuration_values():
    engine = build_engine()
    assert engine.configuration.values["timeframes.context"] == "H4"
    assert engine.configuration.values["timeframes.strategy"] == "H1"
    assert engine.configuration.values["timeframes.execution"] == "M15"

