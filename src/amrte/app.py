from datetime import datetime, timezone

from .core.capabilities import CapabilityRegistry
from .core.clock import FixedClock
from .core.config_engine import MasterConfigurationEngine, MasterConfigurationProvider
from .core.constants import DEFAULT_SEED
from .core.engine import AMRTEEngine
from .core.health import HealthService
from .core.observability import (
    IEventSink,
    InMemoryEventSink,
    ObservabilityService,
)
from .core.services import ServiceRegistry
from .core.state import StateMachine
from .infrastructure.local import (
    InMemoryAuditSink, InMemoryStateRepository,
    ProhibitedExecutionProvider, SeededRandomSource,
)


def build_engine(
    environment: str = "RESEARCH",
    additional_sinks: tuple[IEventSink, ...] = (),
) -> AMRTEEngine:
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))

    event_sink = InMemoryEventSink()

    observability = ObservabilityService(
        clock,
        (event_sink, *additional_sinks),
        runtime_environment=environment,
    )
    audit = InMemoryAuditSink(observer=observability)
    registry = ServiceRegistry()
    registry.register("clock", clock)
    registry.register("audit", audit)
    registry.register("observability", observability)
    configuration_engine = MasterConfigurationEngine(clock, audit)
    registry.register("configuration", MasterConfigurationProvider(configuration_engine))
    registry.register("state", InMemoryStateRepository())
    registry.register("execution", ProhibitedExecutionProvider(audit))
    registry.register("health", HealthService())
    registry.register("random", SeededRandomSource(DEFAULT_SEED))
    engine = AMRTEEngine(registry, StateMachine(clock, audit), CapabilityRegistry(), audit)
    engine.observability = observability
    engine.initialize(environment)
    return engine


def main() -> int:
    engine = build_engine()
    ready = engine.state_machine.state.name == "READY"
    engine.shutdown("entry-point validation complete")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
