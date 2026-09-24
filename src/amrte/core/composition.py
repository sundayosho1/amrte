from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .interfaces import IAuditSink
from .types import HealthReport, HealthStatus


class ComponentType(Enum):
    CORE = "CORE"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    RESEARCH = "RESEARCH"
    PERSISTENCE = "PERSISTENCE"
    OBSERVABILITY = "OBSERVABILITY"
    INTERFACE = "INTERFACE"
    OPTIONAL = "OPTIONAL"


class ComponentStatus(Enum):
    DECLARED = "DECLARED"
    REGISTERED = "REGISTERED"
    DEPENDENCIES_VALIDATED = "DEPENDENCIES_VALIDATED"
    INITIALIZING = "INITIALIZING"
    INITIALIZED = "INITIALIZED"
    READY = "READY"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    FAILED = "FAILED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    UNAVAILABLE = "UNAVAILABLE"


class CompositionError(RuntimeError):
    code = "COMPOSITION_ERROR"


class DuplicateComponentError(CompositionError):
    code = "DUPLICATE_COMPONENT"


class InvalidComponentError(CompositionError):
    code = "INVALID_COMPONENT"


class MissingDependencyError(CompositionError):
    code = "MISSING_DEPENDENCY"


class DependencyCycleError(CompositionError):
    code = "DEPENDENCY_CYCLE"


@dataclass(frozen=True)
class ComponentCapabilities:
    lifecycle: bool = True
    persistence: bool = False
    recovery: bool = False
    health: bool = True
    diagnostics: bool = True
    activation: bool = True


@dataclass(frozen=True)
class ComponentMetadata:
    component_id: str
    component_type: ComponentType
    component_version: str = "1.0"
    required: bool = True
    dependencies: tuple[str, ...] = ()
    capabilities: ComponentCapabilities = field(
        default_factory=ComponentCapabilities
    )
    available: bool = True

    def __post_init__(self) -> None:
        component_id = self.component_id.strip()
        if not component_id:
            raise InvalidComponentError("component identity is required")
        if component_id != self.component_id:
            object.__setattr__(self, "component_id", component_id)
        normalized_dependencies = tuple(
            dependency.strip()
            for dependency in self.dependencies
        )
        if any(not dependency for dependency in normalized_dependencies):
            raise InvalidComponentError("dependency identity is required")
        if len(set(normalized_dependencies)) != len(normalized_dependencies):
            raise InvalidComponentError("duplicate dependency declaration")
        object.__setattr__(
            self,
            "dependencies",
            tuple(sorted(normalized_dependencies)),
        )
        if self.required and not self.available:
            raise InvalidComponentError(
                "required component cannot be declared unavailable"
            )


@dataclass
class ComponentRecord:
    metadata: ComponentMetadata
    component: Any = None
    status: ComponentStatus = ComponentStatus.DECLARED
    ready: bool = False
    active: bool = False
    health: HealthStatus = HealthStatus.UNKNOWN
    reason: str = ""
    cleanup_error: str = ""

    def inventory(self) -> dict[str, Any]:
        return {
            "component_id": self.metadata.component_id,
            "component_type": self.metadata.component_type.name,
            "required": self.metadata.required,
            "dependencies": list(self.metadata.dependencies),
            "status": self.status.name,
            "ready": self.ready,
            "active": self.active,
            "health": self.health.name,
            "persistence_participant": self.metadata.capabilities.persistence,
            "recovery_participant": self.metadata.capabilities.recovery,
            "diagnostics_available": self.metadata.capabilities.diagnostics,
            "version": self.metadata.component_version,
            "reason": self.reason,
            "cleanup_error": self.cleanup_error,
        }


@dataclass(frozen=True)
class CompositionContext:
    services: Mapping[str, Any]
    runtime_state: str = "COMPOSITION"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "services",
            MappingProxyType(dict(self.services)),
        )


class RuntimeComposition:
    """Authoritative deterministic component registry and lifecycle coordinator."""

    def __init__(self, audit: IAuditSink | None = None) -> None:
        self.audit = audit
        self._records: dict[str, ComponentRecord] = {}
        self._frozen = False
        self._validated = False
        self._initialization_order: tuple[str, ...] = ()
        self._shutdown_order: tuple[str, ...] = ()
        self._failure_reasons: list[str] = []

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(
        self,
        metadata: ComponentMetadata,
        component: Any = None,
    ) -> None:
        if self._frozen:
            raise RuntimeError("component registry is frozen")
        component_id = metadata.component_id
        if component_id in self._records:
            raise DuplicateComponentError(component_id)
        status = (
            ComponentStatus.REGISTERED
            if metadata.available
            else ComponentStatus.UNAVAILABLE
        )
        health = (
            HealthStatus.UNKNOWN
            if metadata.available
            else HealthStatus.UNHEALTHY
        )
        self._records[component_id] = ComponentRecord(
            metadata=metadata,
            component=component,
            status=status,
            health=health,
            reason=(
                ""
                if metadata.available
                else "component intentionally unavailable"
            ),
        )
        self._audit(
            "component_registered",
            {
                "component_id": component_id,
                "component_type": metadata.component_type.name,
                "required": metadata.required,
            },
        )

    def get(self, component_id: str) -> ComponentRecord:
        return self._records[component_id]

    def records(self) -> tuple[ComponentRecord, ...]:
        return tuple(
            self._records[component_id]
            for component_id in sorted(self._records)
        )

    def freeze(self) -> None:
        self._frozen = True

    def validate(self) -> tuple[str, ...]:
        missing: list[str] = []
        for component_id, record in sorted(self._records.items()):
            metadata = record.metadata
            if not metadata.available:
                continue
            for dependency in metadata.dependencies:
                if dependency == component_id:
                    raise MissingDependencyError(
                        f"{component_id} depends on itself"
                    )
                if dependency not in self._records:
                    missing.append(f"{component_id}->{dependency}")
                elif not self._records[dependency].metadata.available:
                    missing.append(f"{component_id}->{dependency}:UNAVAILABLE")
        if missing:
            reason = ",".join(sorted(missing))
            self._audit(
                "dependency_validation_failed",
                {"missing": tuple(sorted(missing))},
            )
            raise MissingDependencyError(reason)

        order = self._topological_order()
        self._initialization_order = order
        self._shutdown_order = tuple(reversed(order))
        for component_id in order:
            record = self._records[component_id]
            if record.metadata.available:
                record.status = ComponentStatus.DEPENDENCIES_VALIDATED
        self._validated = True
        self._audit(
            "composition_validated",
            {"initialization_order": order},
        )
        return order

    @property
    def initialization_order(self) -> tuple[str, ...]:
        if not self._initialization_order:
            self.validate()
        return self._initialization_order

    @property
    def shutdown_order(self) -> tuple[str, ...]:
        if not self._shutdown_order:
            self.validate()
        return self._shutdown_order

    def initialize(self, context: CompositionContext | None = None) -> None:
        if not self._frozen:
            self.freeze()
        if not self._validated:
            self.validate()
        initialized: list[str] = []
        context = context or CompositionContext({})
        for component_id in self._initialization_order:
            record = self._records[component_id]
            if not record.metadata.available:
                continue
            try:
                record.status = ComponentStatus.INITIALIZING
                self._audit(
                    "component_initialization_started",
                    {"component_id": component_id},
                )
                self._call(record.component, "initialize_component", context)
                record.status = ComponentStatus.INITIALIZED
                ready = self._component_ready(record, context)
                record.ready = ready
                if ready:
                    record.status = ComponentStatus.READY
                    record.health = self._component_health(record, context)
                    self._audit(
                        "component_ready",
                        {
                            "component_id": component_id,
                            "health": record.health.name,
                        },
                    )
                else:
                    record.status = ComponentStatus.DEGRADED
                    record.health = HealthStatus.DEGRADED
                    record.reason = "readiness check returned false"
                initialized.append(component_id)
            except Exception as exc:
                self._handle_initialization_failure(
                    record,
                    exc,
                    initialized,
                    context,
                )
                if record.metadata.required:
                    raise
        self._audit(
            "composition_initialized",
            {"ready": self.readiness_report().ready},
        )

    def activate(self) -> None:
        for component_id in self._initialization_order:
            record = self._records[component_id]
            if (
                record.status is ComponentStatus.READY
                and record.metadata.capabilities.activation
            ):
                record.status = ComponentStatus.ACTIVE
                record.active = True
                self._audit(
                    "component_active",
                    {"component_id": component_id},
                )

    def shutdown(self, context: CompositionContext | None = None) -> None:
        context = context or CompositionContext({})
        for component_id in self.shutdown_order:
            record = self._records[component_id]
            if record.status in (
                ComponentStatus.STOPPED,
                ComponentStatus.UNAVAILABLE,
                ComponentStatus.DECLARED,
                ComponentStatus.REGISTERED,
            ):
                continue
            self._stop_record(record, context)

    def restore(
        self,
        payloads: Mapping[str, Any],
        context: CompositionContext | None = None,
    ) -> None:
        context = context or CompositionContext({})
        for component_id in self.initialization_order:
            record = self._records[component_id]
            if not record.metadata.capabilities.recovery:
                continue
            self._call(
                record.component,
                "restore_component_state",
                payloads.get(component_id),
                context,
            )
            self._call(record.component, "reconcile_component", context)
            record.active = False
            if record.status is ComponentStatus.ACTIVE:
                record.status = ComponentStatus.READY
            self._audit(
                "component_recovered",
                {"component_id": component_id, "active": record.active},
            )

    def readiness_report(self) -> HealthReport:
        reasons: list[str] = []
        components: dict[str, HealthStatus] = {}
        for component_id, record in sorted(self._records.items()):
            components[component_id] = record.health
            if record.metadata.required and not record.ready:
                reasons.append(
                    f"{component_id}:{record.status.name}"
                    + (f":{record.reason}" if record.reason else "")
                )
        return HealthReport(
            components=components,
            ready=not reasons,
            reasons=tuple(reasons),
        )

    def health_report(self) -> HealthReport:
        reasons: list[str] = []
        components: dict[str, HealthStatus] = {}
        for component_id, record in sorted(self._records.items()):
            status = record.health
            components[component_id] = status
            if status in (
                HealthStatus.UNHEALTHY,
                HealthStatus.UNKNOWN,
                HealthStatus.RESTRICTED,
            ):
                if record.metadata.required:
                    reasons.append(f"{component_id}:{status.name}")
        return HealthReport(
            components=components,
            ready=not reasons,
            reasons=tuple(reasons),
        )

    def inventory(self) -> tuple[dict[str, Any], ...]:
        return tuple(record.inventory() for record in self.records())

    def diagnostics(self) -> dict[str, Any]:
        readiness = self.readiness_report()
        health = self.health_report()
        return {
            "registry_frozen": self._frozen,
            "validated": self._validated,
            "initialization_order": list(self._initialization_order),
            "shutdown_order": list(self._shutdown_order),
            "readiness": {
                "ready": readiness.ready,
                "reasons": list(readiness.reasons),
            },
            "health": {
                "ready": health.ready,
                "reasons": list(health.reasons),
                "components": {
                    key: value.name
                    for key, value in sorted(health.components.items())
                },
            },
            "components": list(self.inventory()),
            "research_pipeline": self.research_pipeline_status(),
            "failure_reasons": list(self._failure_reasons),
        }

    def research_pipeline_status(self) -> dict[str, Any]:
        record = self._records.get("research_pipeline")
        if record is None:
            return {
                "registered": False,
                "active": False,
                "status": "NOT_REGISTERED",
            }
        return {
            "registered": True,
            "active": record.active,
            "status": record.status.name,
            "ready": record.ready,
            "health": record.health.name,
            "reason": record.reason,
        }

    def _handle_initialization_failure(
        self,
        record: ComponentRecord,
        exc: Exception,
        initialized: list[str],
        context: CompositionContext,
    ) -> None:
        record.status = ComponentStatus.FAILED
        record.ready = False
        record.active = False
        record.health = HealthStatus.UNHEALTHY
        record.reason = f"{type(exc).__name__}: {exc}"
        self._failure_reasons.append(
            f"{record.metadata.component_id}:{record.reason}"
        )
        self._audit(
            "component_failed",
            {
                "component_id": record.metadata.component_id,
                "reason": record.reason,
                "required": record.metadata.required,
            },
        )
        if record.metadata.required:
            for component_id in reversed(initialized):
                self._stop_record(self._records[component_id], context)

    def _stop_record(
        self,
        record: ComponentRecord,
        context: CompositionContext,
    ) -> None:
        record.status = ComponentStatus.STOPPING
        try:
            self._call(record.component, "shutdown_component", context)
        except Exception as exc:
            record.cleanup_error = f"{type(exc).__name__}: {exc}"
            self._failure_reasons.append(
                f"{record.metadata.component_id}:cleanup:{record.cleanup_error}"
            )
            self._audit(
                "component_cleanup_failed",
                {
                    "component_id": record.metadata.component_id,
                    "reason": record.cleanup_error,
                },
            )
        record.active = False
        record.ready = False
        record.status = ComponentStatus.STOPPED
        record.health = HealthStatus.UNKNOWN
        self._audit(
            "component_stopped",
            {"component_id": record.metadata.component_id},
        )

    def _topological_order(self) -> tuple[str, ...]:
        available = {
            component_id
            for component_id, record in self._records.items()
            if record.metadata.available
        }
        incoming = {
            component_id: set(self._records[component_id].metadata.dependencies)
            & available
            for component_id in available
        }
        outgoing = {component_id: set() for component_id in available}
        for component_id, dependencies in incoming.items():
            for dependency in dependencies:
                outgoing[dependency].add(component_id)
        ready = sorted(
            component_id
            for component_id, dependencies in incoming.items()
            if not dependencies
        )
        order: list[str] = []
        while ready:
            component_id = ready.pop(0)
            order.append(component_id)
            for dependent in sorted(outgoing[component_id]):
                incoming[dependent].remove(component_id)
                if not incoming[dependent]:
                    ready.append(dependent)
                    ready.sort()
        if len(order) != len(available):
            cycle_nodes = tuple(
                sorted(
                    component_id
                    for component_id, dependencies in incoming.items()
                    if dependencies
                )
            )
            self._audit(
                "composition_cycle_detected",
                {"cycle_nodes": cycle_nodes},
            )
            raise DependencyCycleError("->".join(cycle_nodes))
        return tuple(order)

    def _component_ready(
        self,
        record: ComponentRecord,
        context: CompositionContext,
    ) -> bool:
        ready = self._call(record.component, "component_ready", context)
        if ready is None:
            return True
        return bool(ready)

    def _component_health(
        self,
        record: ComponentRecord,
        context: CompositionContext,
    ) -> HealthStatus:
        health = self._call(record.component, "component_health", context)
        if health is None:
            health = getattr(record.component, "health", None)
        if isinstance(health, HealthStatus):
            return health
        name = getattr(health, "name", None)
        if name in HealthStatus.__members__:
            return HealthStatus[name]
        if name == "HEALTHY":
            return HealthStatus.HEALTHY
        if name in {"DEGRADED", "CORRUPTED"}:
            return HealthStatus.DEGRADED
        if name in {"UNAVAILABLE", "UNHEALTHY"}:
            return HealthStatus.UNHEALTHY
        return HealthStatus.HEALTHY

    @staticmethod
    def _call(component: Any, method: str, *args: Any) -> Any:
        target = getattr(component, method, None)
        if target is None:
            return None
        return target(*args)

    def _audit(self, event: str, context: Mapping[str, Any]) -> None:
        if self.audit is not None:
            self.audit.record(event, context)


def register_core_components(
    composition: RuntimeComposition,
    services: Mapping[str, Any],
) -> None:
    definitions = (
        ("clock", ComponentType.CORE, True, ()),
        ("audit", ComponentType.OBSERVABILITY, True, ("clock",)),
        ("observability", ComponentType.OBSERVABILITY, True, ("clock",)),
        ("configuration", ComponentType.CORE, True, ("clock", "audit")),
        ("state", ComponentType.CORE, True, ()),
        ("execution", ComponentType.INFRASTRUCTURE, True, ("audit",)),
        ("health", ComponentType.CORE, True, ()),
        ("random", ComponentType.INFRASTRUCTURE, True, ()),
    )
    for component_id, component_type, required, dependencies in definitions:
        composition.register(
            ComponentMetadata(
                component_id=component_id,
                component_type=component_type,
                required=required,
                dependencies=dependencies,
                capabilities=ComponentCapabilities(
                    persistence=component_id == "state",
                    recovery=component_id == "state",
                    activation=True,
                ),
            ),
            services[component_id],
        )
    from amrte.market.boundary import market_data_component_registrations

    for metadata, component in market_data_component_registrations():
        composition.register(metadata, component)
    from amrte.research.data_quality_runtime import data_quality_component_registrations

    for metadata, component in data_quality_component_registrations():
        composition.register(metadata, component)
    from amrte.market.intelligence_runtime import market_intelligence_component_registrations

    for metadata, component in market_intelligence_component_registrations():
        composition.register(metadata, component)
    from amrte.strategies.evaluation_runtime import strategy_evaluation_component_registrations

    for metadata, component in strategy_evaluation_component_registrations():
        composition.register(metadata, component)
    from amrte.strategies.research_scoring_runtime import research_scoring_component_registrations

    for metadata, component in research_scoring_component_registrations():
        composition.register(metadata, component)
    from amrte.portfolio.research_portfolio_runtime import research_portfolio_component_registrations

    for metadata, component in research_portfolio_component_registrations():
        composition.register(metadata, component)
    from amrte.research.protection_runtime import research_protection_component_registrations

    for metadata, component in research_protection_component_registrations():
        composition.register(metadata, component)
    from amrte.research.decision_runtime import master_research_decision_component_registrations

    for metadata, component in master_research_decision_component_registrations():
        composition.register(metadata, component)
    composition.register(
        ComponentMetadata(
            component_id="composition",
            component_type=ComponentType.CORE,
            required=True,
            dependencies=tuple(item[0] for item in definitions),
            capabilities=ComponentCapabilities(activation=True),
        ),
        composition,
    )
    composition.register(
        ComponentMetadata(
            component_id="research_pipeline",
            component_type=ComponentType.RESEARCH,
            component_version="0.0",
            required=False,
            dependencies=("configuration", "clock", "observability"),
            capabilities=ComponentCapabilities(
                lifecycle=False,
                persistence=False,
                recovery=False,
                health=True,
                diagnostics=True,
                activation=False,
            ),
            available=False,
        ),
        None,
    )
