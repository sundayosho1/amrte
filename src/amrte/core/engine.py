from __future__ import annotations

from .capabilities import CapabilityRegistry
from .environment import detect_environment
from .errors import AMRTEError, Result
from .health import HealthService
from .interfaces import IAuditSink, IConfigurationProvider, IStateRepository
from .services import ServiceRegistry
from .state import StateMachine
from .types import HealthStatus, RuntimeEnvironment, Severity, SystemState


MANDATORY_SERVICES = ("configuration", "state", "clock", "audit", "observability",
                      "execution", "health", "random")


class AMRTEEngine:
    def __init__(self, registry: ServiceRegistry, state_machine: StateMachine,
                 capabilities: CapabilityRegistry, audit: IAuditSink):
        self.registry = registry
        self.state_machine = state_machine
        self.capabilities = capabilities
        self.audit = audit
        self.environment = RuntimeEnvironment.UNKNOWN
        self.configuration = None
        self.composition = None
        self._initialized = False

    def initialize(self, environment_name: str) -> Result[SystemState]:
        try:
            self.audit.record("initialization_started", {"environment_requested": environment_name})
            self.environment = detect_environment(environment_name)
            if self.environment is RuntimeEnvironment.UNKNOWN:
                return self._startup_failure("UNSUPPORTED_ENVIRONMENT", "runtime environment is unknown")
            self.audit.record("runtime_environment_detected", {"environment": self.environment.name})
            for name in MANDATORY_SERVICES:
                self.registry.require(name)
            self.audit.record("services_validated", {"services": MANDATORY_SERVICES})
            if "composition" in self.registry.names():
                self.composition = self.registry.require("composition")
            config_provider: IConfigurationProvider = self.registry.require("configuration")
            loaded = config_provider.load()
            if not loaded.success:
                return self._startup_failure("CONFIGURATION_INVALID", loaded.error.message if loaded.error else "invalid")
            self.audit.record("configuration_loaded", {
                "snapshot_id": getattr(loaded.value, "snapshot_id", None),
                "configuration_hash": getattr(loaded.value, "configuration_hash", None),
            })
            state_repo: IStateRepository = self.registry.require("state")
            persisted = state_repo.load()
            if not persisted.success:
                return self._startup_failure("PERSISTENCE_UNAVAILABLE", "state could not be loaded")
            self.audit.record("persistence_loaded", {"state_keys": tuple(sorted(persisted.value))})
            health: HealthService = self.registry.require("health")
            components = {name: HealthStatus.HEALTHY for name in MANDATORY_SERVICES}
            observability = self.registry.require("observability")
            if getattr(getattr(observability, "health", None), "name", "UNKNOWN") != "HEALTHY":
                components["observability"] = HealthStatus.UNHEALTHY
            report = health.assess(components, MANDATORY_SERVICES)
            if not report.ready:
                return self._startup_failure("NOT_READY", ",".join(report.reasons))
            self.audit.record("health_checked", {"ready": report.ready,
                                                   "components": {k: v.name for k, v in components.items()}})
            self.configuration = loaded.value
            self.registry.seal()
            transitioned = self.state_machine.transition(SystemState.READY, "startup checks passed")
            self._initialized = transitioned.success
            return transitioned
        except Exception as exc:
            return self._startup_failure("INITIALIZATION_FAILURE", str(exc))

    def start(self) -> Result[SystemState]:
        if not self._initialized or self.state_machine.state is not SystemState.READY:
            return Result.fail(self._error("NOT_READY", "engine is not ready"))
        if self.composition is not None:
            self.composition.activate()
        return self.state_machine.transition(SystemState.RUNNING, "controlled research start")

    def shutdown(self, reason: str) -> Result[SystemState]:
        if self.state_machine.state is SystemState.STOPPED:
            return Result.ok(SystemState.STOPPED)
        if self.composition is not None:
            self.composition.shutdown()
        repository: IStateRepository = self.registry.require("state")
        saved = repository.save({"state": self.state_machine.state.name, "reason": reason})
        if not saved.success:
            self.state_machine.transition(SystemState.ERROR, "shutdown persistence failure")
            return Result.fail(saved.error)
        transitioned = self.state_machine.transition(SystemState.STOPPED, reason)
        self.audit.record("shutdown", {"reason": reason, "success": transitioned.success})
        self.audit.flush()
        return transitioned

    def _startup_failure(self, code: str, message: str) -> Result[SystemState]:
        self.audit.record("startup_failure", {"code": code, "message": message})
        if self.state_machine.state is SystemState.INITIALIZING:
            self.state_machine.transition(SystemState.ERROR, code)
        return Result.fail(self._error(code, message))

    def _error(self, code: str, message: str) -> AMRTEError:
        clock = self.registry.require("clock")
        return AMRTEError(clock.now(), "Core.Engine", "initialize", Severity.CRITICAL,
                          code, message, recoverable=False)
