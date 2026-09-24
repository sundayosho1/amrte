from __future__ import annotations

import pytest

from amrte.app import build_engine
from amrte.core.composition import (
    ComponentCapabilities,
    ComponentMetadata,
    ComponentStatus,
    ComponentType,
    CompositionContext,
    DependencyCycleError,
    DuplicateComponentError,
    InvalidComponentError,
    MissingDependencyError,
    RuntimeComposition,
)
from amrte.core.types import HealthStatus
from amrte.infrastructure.local import InMemoryAuditSink
from amrte.operations.runtime import PersistentResearchRuntime
from run_amrte import main as cli_main


class DummyComponent:
    def __init__(
        self,
        component_id,
        events,
        *,
        fail_initialize=False,
        fail_shutdown=False,
        ready=True,
        health=HealthStatus.HEALTHY,
    ):
        self.component_id = component_id
        self.events = events
        self.fail_initialize = fail_initialize
        self.fail_shutdown = fail_shutdown
        self.ready = ready
        self.health = health
        self.restored = False
        self.reconciled = False

    def initialize_component(self, context):
        self.events.append(f"init:{self.component_id}")
        if self.fail_initialize:
            raise RuntimeError(f"fail:{self.component_id}")

    def shutdown_component(self, context):
        self.events.append(f"stop:{self.component_id}")
        if self.fail_shutdown:
            raise RuntimeError(f"cleanup:{self.component_id}")

    def component_ready(self, context):
        return self.ready

    def component_health(self, context):
        return self.health

    def restore_component_state(self, payload, context):
        self.events.append(f"restore:{self.component_id}")
        self.restored = payload

    def reconcile_component(self, context):
        self.events.append(f"reconcile:{self.component_id}")
        self.reconciled = True


def metadata(component_id, *, required=True, dependencies=(), **kwargs):
    return ComponentMetadata(
        component_id=component_id,
        component_type=kwargs.pop("component_type", ComponentType.CORE),
        required=required,
        dependencies=tuple(dependencies),
        capabilities=kwargs.pop("capabilities", ComponentCapabilities()),
        **kwargs,
    )


def composition_with(*items):
    audit = InMemoryAuditSink()
    composition = RuntimeComposition(audit)
    events = []
    for item in items:
        component_id, dependencies = item[:2]
        required = item[2] if len(item) > 2 else True
        component = DummyComponent(component_id, events)
        composition.register(
            metadata(
                component_id,
                required=required,
                dependencies=dependencies,
            ),
            component,
        )
    return composition, events, audit


def test_register_component_and_deterministic_lookup():
    composition, _, _ = composition_with(("b", ()), ("a", ()))
    assert [record.metadata.component_id for record in composition.records()] == [
        "a",
        "b",
    ]
    assert composition.get("a").metadata.component_id == "a"


def test_duplicate_component_id_rejected():
    composition, _, _ = composition_with(("a", ()))
    with pytest.raises(DuplicateComponentError):
        composition.register(metadata("a"), object())


def test_invalid_metadata_rejected():
    with pytest.raises(InvalidComponentError):
        metadata("")
    with pytest.raises(InvalidComponentError):
        metadata("x", dependencies=("a", "a"))
    with pytest.raises(InvalidComponentError):
        metadata("x", required=True, available=False)


def test_registry_freezes_at_initialization():
    composition, _, _ = composition_with(("a", ()))
    composition.initialize()
    assert composition.frozen is True
    with pytest.raises(RuntimeError):
        composition.register(metadata("b"), object())


def test_valid_dependency_graph_and_order():
    composition, _, _ = composition_with(
        ("clock", ()),
        ("configuration", ("clock",)),
        ("market", ("configuration", "clock")),
    )
    assert composition.validate() == (
        "clock",
        "configuration",
        "market",
    )


def test_missing_required_dependency_detected():
    composition, _, _ = composition_with(("market", ("clock",)))
    with pytest.raises(MissingDependencyError):
        composition.validate()


def test_self_dependency_detected():
    composition, _, _ = composition_with(("a", ("a",)))
    with pytest.raises(MissingDependencyError):
        composition.validate()


def test_simple_cycle_detected():
    composition, _, _ = composition_with(("a", ("b",)), ("b", ("a",)))
    with pytest.raises(DependencyCycleError):
        composition.validate()


def test_multi_node_cycle_detected():
    composition, _, _ = composition_with(
        ("a", ("b",)),
        ("b", ("c",)),
        ("c", ("a",)),
    )
    with pytest.raises(DependencyCycleError):
        composition.validate()


def test_deterministic_topological_tie_breaking():
    first, _, _ = composition_with(("b", ()), ("a", ()), ("c", ()))
    second, _, _ = composition_with(("c", ()), ("b", ()), ("a", ()))
    assert first.validate() == second.validate() == ("a", "b", "c")


def test_dependency_first_initialization_and_dependent_first_shutdown():
    composition, events, _ = composition_with(
        ("a", ()),
        ("b", ("a",)),
        ("c", ("b",)),
    )
    composition.initialize()
    composition.shutdown()
    assert events == [
        "init:a",
        "init:b",
        "init:c",
        "stop:c",
        "stop:b",
        "stop:a",
    ]


def test_successful_initialization_status_and_readiness():
    composition, _, _ = composition_with(("a", ()))
    composition.initialize()
    record = composition.get("a")
    assert record.status is ComponentStatus.READY
    assert record.ready is True
    assert record.active is False
    assert composition.readiness_report().ready is True


def test_ready_distinct_from_active_until_activation():
    composition, _, _ = composition_with(("a", ()))
    composition.initialize()
    assert composition.get("a").status is ComponentStatus.READY
    composition.activate()
    assert composition.get("a").status is ComponentStatus.ACTIVE
    assert composition.get("a").active is True


def test_double_activation_is_idempotent():
    composition, _, _ = composition_with(("a", ()))
    composition.initialize()
    composition.activate()
    composition.activate()
    assert composition.get("a").status is ComponentStatus.ACTIVE


def test_clean_shutdown_and_repeated_shutdown():
    composition, events, _ = composition_with(("a", ()))
    composition.initialize()
    composition.activate()
    composition.shutdown()
    composition.shutdown()
    assert composition.get("a").status is ComponentStatus.STOPPED
    assert events == ["init:a", "stop:a"]


def test_required_initialization_failure_rolls_back_partial_init():
    audit = InMemoryAuditSink()
    composition = RuntimeComposition(audit)
    events = []
    composition.register(metadata("a"), DummyComponent("a", events))
    composition.register(
        metadata("b", dependencies=("a",)),
        DummyComponent("b", events, fail_initialize=True),
    )
    with pytest.raises(RuntimeError):
        composition.initialize()
    assert events == ["init:a", "init:b", "stop:a"]
    assert composition.get("b").status is ComponentStatus.FAILED
    assert composition.readiness_report().ready is False


def test_cleanup_failure_is_observable_without_hiding_original_failure():
    composition = RuntimeComposition(InMemoryAuditSink())
    events = []
    composition.register(
        metadata("a"),
        DummyComponent("a", events, fail_shutdown=True),
    )
    composition.register(
        metadata("b", dependencies=("a",)),
        DummyComponent("b", events, fail_initialize=True),
    )
    with pytest.raises(RuntimeError):
        composition.initialize()
    assert "cleanup:a" in composition.get("a").cleanup_error
    assert "b:RuntimeError: fail:b" in composition.diagnostics()["failure_reasons"]


def test_optional_component_failure_is_degraded_not_global_failure():
    composition = RuntimeComposition(InMemoryAuditSink())
    events = []
    composition.register(metadata("required"), DummyComponent("required", events))
    composition.register(
        metadata("optional", required=False),
        DummyComponent("optional", events, fail_initialize=True),
    )
    composition.initialize()
    assert composition.get("optional").status is ComponentStatus.FAILED
    assert composition.readiness_report().ready is True
    assert composition.get("optional").health is HealthStatus.UNHEALTHY


def test_required_dependency_failure_blocks_readiness():
    composition = RuntimeComposition(InMemoryAuditSink())
    events = []
    composition.register(
        metadata("a"),
        DummyComponent("a", events, ready=False),
    )
    composition.initialize()
    assert composition.get("a").status is ComponentStatus.DEGRADED
    assert composition.readiness_report().ready is False


def test_health_aggregation_and_unavailable_optional_component():
    composition = RuntimeComposition(InMemoryAuditSink())
    composition.register(metadata("required"), DummyComponent("required", []))
    composition.register(
        metadata(
            "optional_offline",
            required=False,
            available=False,
            component_type=ComponentType.RESEARCH,
        ),
        None,
    )
    composition.initialize()
    diagnostics = composition.diagnostics()
    assert diagnostics["readiness"]["ready"] is True
    assert composition.get("optional_offline").status is ComponentStatus.UNAVAILABLE
    assert composition.get("optional_offline").health is HealthStatus.UNHEALTHY


def test_persistence_and_recovery_participants_identified():
    composition = RuntimeComposition(InMemoryAuditSink())
    composition.register(
        metadata(
            "stateful",
            capabilities=ComponentCapabilities(
                persistence=True,
                recovery=True,
            ),
        ),
        DummyComponent("stateful", []),
    )
    composition.initialize()
    item = composition.inventory()[0]
    assert item["persistence_participant"] is True
    assert item["recovery_participant"] is True


def test_restore_reconcile_order_and_recovery_does_not_activate():
    events = []
    component = DummyComponent("stateful", events)
    composition = RuntimeComposition(InMemoryAuditSink())
    composition.register(
        metadata(
            "stateful",
            capabilities=ComponentCapabilities(
                persistence=True,
                recovery=True,
            ),
        ),
        component,
    )
    composition.initialize()
    composition.activate()
    assert composition.get("stateful").active is True
    composition.restore({"stateful": {"permission": "restricted"}})
    assert events[-2:] == ["restore:stateful", "reconcile:stateful"]
    assert component.restored == {"permission": "restricted"}
    assert component.reconciled is True
    assert composition.get("stateful").active is False


def test_component_inventory_and_dependency_diagnostics_are_accurate():
    composition, _, _ = composition_with(("a", ()), ("b", ("a",)))
    composition.initialize()
    diagnostics = composition.diagnostics()
    assert diagnostics["initialization_order"] == ["a", "b"]
    assert diagnostics["shutdown_order"] == ["b", "a"]
    assert diagnostics["components"][1]["dependencies"] == ["a"]


def test_build_engine_exposes_composition_without_activating_pipeline():
    engine = build_engine()
    assert engine.composition is not None
    assert engine.composition.get("market_data_contract").ready is True
    assert engine.composition.get("market_dataset_authority").ready is True
    assert engine.composition.get("market_data_configured_dataset").status is ComponentStatus.UNAVAILABLE
    assert engine.composition.get("observation_quality").ready is True
    assert engine.composition.get("research_reliability").ready is True
    assert engine.composition.get("temporal_quality").ready is True
    assert engine.composition.get("data_trust").ready is True
    assert engine.composition.get("market_structure").ready is True
    assert engine.composition.get("market_features").ready is True
    assert engine.composition.get("market_session").ready is True
    assert engine.composition.get("market_event_context").ready is True
    assert engine.composition.get("market_regime").ready is True
    assert engine.composition.get("market_intelligence").ready is True
    pipeline = engine.composition.research_pipeline_status()
    assert pipeline["registered"] is True
    assert pipeline["active"] is False
    assert pipeline["status"] == "UNAVAILABLE"
    assert engine.state_machine.state.name == "READY"


def test_core_running_does_not_imply_research_pipeline_active():
    engine = build_engine()
    assert engine.start().success
    assert engine.state_machine.state.name == "RUNNING"
    assert engine.composition.research_pipeline_status()["active"] is False
    assert engine.composition.get("clock").active is True


def test_engine_double_start_fails_explicitly():
    engine = build_engine()
    assert engine.start().success
    second = engine.start()
    assert not second.success
    assert second.error.code == "NOT_READY"


def test_persistent_runtime_remains_authoritative(tmp_path):
    runtime = PersistentResearchRuntime(
        state_root=tmp_path / "state",
        log_path=tmp_path / "logs" / "amrte.jsonl",
    )
    runtime.start()
    try:
        assert runtime.composition is runtime.engine.composition
        assert runtime.state == "RUNNING"
    finally:
        runtime.shutdown()


def test_cli_uses_authoritative_runtime_factory():
    calls = []

    class Runtime:
        engine = object()
        recovery_report = None
        last_checkpoint = None
        state = "STOPPED"

        def start(self):
            calls.append("start")
            raise KeyboardInterrupt()

        def shutdown(self):
            calls.append("shutdown")

    assert cli_main(runtime_factory=Runtime) == 0
    assert calls == ["start", "shutdown"]


def test_execution_prohibition_remains_authoritative():
    engine = build_engine()
    execution = engine.registry.require("execution")
    assert type(execution).__name__ == "ProhibitedExecutionProvider"
    assert not execution.submit({"attempt": "blocked"}).success


def test_no_financial_capability_terms_in_composition_source():
    source = (
        __import__("pathlib")
        .Path("src/amrte/core/composition.py")
        .read_text(encoding="utf-8")
        .lower()
    )
    forbidden = (
        "broker_login",
        "order_send",
        "place_order",
        "open_position",
        "margin",
        "leverage",
    )
    assert not any(token in source for token in forbidden)
