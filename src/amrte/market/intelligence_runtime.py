from __future__ import annotations

import hashlib
import json
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from amrte.core.composition import ComponentCapabilities, ComponentMetadata, ComponentType
from amrte.core.identity import deterministic_id
from amrte.core.types import HealthStatus
from amrte.market.events import (
    DeterministicEventProvider,
    EventImportance,
    EventProviderHealth,
    EventWindowPolicy,
    NewsRiskConfiguration,
    NewsRiskEngine,
)
from amrte.market.features import FeatureEngine, FeatureRequest
from amrte.market.intelligence import (
    IntelligenceAvailability,
    IntelligenceHealth,
    MarketIntelligenceAssembler,
    MarketIntelligenceSnapshot,
)
from amrte.market.models import (
    DataHealth,
    DataProvenance,
    MarketDataSnapshot,
    SpreadHealth,
    SpreadOrigin,
    SpreadState,
    SynchronizationStatus,
)
from amrte.market.observation import (
    CanonicalMarketDataset,
    CanonicalMarketObservation,
    observation_to_normalized_bar,
    schema_identity as market_data_schema_identity,
    validate_canonical_observation,
)
from amrte.market.regime import RegimeEngine
from amrte.market.session import (
    SessionConfiguration,
    SessionDefinition,
    SessionEngine,
    SessionType,
    TimeZoneService,
    WeekdayFallbackCalendar,
)
from amrte.market.structure import MarketStructureEngine
from amrte.research.data_quality_runtime import (
    TrustStatus,
    TrustedResearchObservation,
    quality_trust_schema_identity,
)


MARKET_INTELLIGENCE_RUNTIME_VERSION = "1.0"
UNIFIED_INTELLIGENCE_SCHEMA_VERSION = "1.0"


class RuntimeAcceptance(Enum):
    ACCEPTED = "ACCEPTED"
    BLOCKED = "BLOCKED"
    DUPLICATE = "DUPLICATE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class MarketIntelligenceRuntimeConfiguration:
    experiment_id: str = "P41_TRUSTED_MARKET_INTELLIGENCE"
    configuration_snapshot_id: str = "P41_MARKET_INTELLIGENCE_DEFAULT"
    maximum_history_per_scope: int = 512
    maximum_snapshots: int = 2048
    default_feature_requests: tuple[FeatureRequest, ...] = field(default_factory=lambda: (
        FeatureRequest("ADX", {"period": 3}),
        FeatureRequest("VOLATILITY_EXPANSION_RATIO", {"window": 3, "percentile_window": 5}),
        FeatureRequest("ATR_ADJUSTED_DISPLACEMENT", {"period": 3, "atr_period": 3}),
        FeatureRequest("BOLLINGER_BANDWIDTH", {"period": 3, "deviation": 2}),
        FeatureRequest("RANGE_ATR", {"window": 3, "atr_period": 3}),
        FeatureRequest("ATR_PERCENT_PRICE", {"period": 3}),
        FeatureRequest("REALIZED_VOLATILITY", {"window": 3}),
    ))
    session_configuration: SessionConfiguration = field(default_factory=lambda: SessionConfiguration(
        sessions=(
            SessionDefinition(
                "global_weekday",
                SessionType.CUSTOM,
                "Global Weekday Research Session",
                "UTC",
                datetime.min.time().replace(hour=0, minute=0),
                datetime.min.time().replace(hour=23, minute=59),
                frozenset({0, 1, 2, 3, 4}),
            ),
        )
    ))
    event_configuration: NewsRiskConfiguration = field(default_factory=lambda: NewsRiskConfiguration(
        windows={
            EventImportance.LOW: EventWindowPolicy(60, 10, 10, 30, 10),
            EventImportance.MEDIUM: EventWindowPolicy(120, 20, 20, 60, 20),
            EventImportance.HIGH: EventWindowPolicy(180, 30, 30, 90, 30),
            EventImportance.CRITICAL: EventWindowPolicy(240, 60, 60, 120, 60),
            EventImportance.UNKNOWN: EventWindowPolicy(180, 30, 30, 90, 30),
        },
        instrument_dimensions={},
    ))

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.experiment_id.strip():
            errors.append("P41_EXPERIMENT_ID_REQUIRED")
        if not self.configuration_snapshot_id.strip():
            errors.append("P41_CONFIGURATION_ID_REQUIRED")
        if min(self.maximum_history_per_scope, self.maximum_snapshots) < 1:
            errors.append("P41_BOUNDS_INVALID")
        if not self.default_feature_requests:
            errors.append("P41_FEATURE_REQUESTS_REQUIRED")
        return tuple(errors)


@dataclass(frozen=True)
class ComponentAvailability:
    component_id: str
    snapshot_id: str | None
    health: str
    critical: bool
    available: bool
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnifiedMarketIntelligenceSnapshot:
    unified_snapshot_id: str
    schema_version: str
    schema_identity: str
    snapshot_fingerprint: str
    created_at: datetime
    as_of_timestamp_utc: datetime
    knowledge_cutoff_utc: datetime
    trusted_observation_id: str
    observation_id: str
    observation_fingerprint: str
    trust_status: str
    quality_snapshot_id: str
    source_health_snapshot_id: str
    dataset_id: str
    dataset_fingerprint: str
    source_id: str
    instrument_id: str
    timeframe: str
    market_intelligence_snapshot_id: str
    market_intelligence: MarketIntelligenceSnapshot
    component_availability: Mapping[str, ComponentAvailability]
    intelligence_health: IntelligenceHealth
    intelligence_availability: IntelligenceAvailability
    restrictions: tuple[str, ...]
    warnings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    research_pipeline_active: bool
    financial_execution: str
    configuration_snapshot_id: str
    recovery_epoch: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "component_availability",
            MappingProxyType(dict(self.component_availability)),
        )


@dataclass(frozen=True)
class MarketIntelligenceRuntimeResult:
    acceptance: RuntimeAcceptance
    snapshot: UnifiedMarketIntelligenceSnapshot | None
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarketIntelligenceRecoveryState:
    schema_version: str
    runtime_version: str
    configuration_snapshot_id: str
    recovery_epoch: int
    processed_trusted_observation_ids: tuple[str, ...]
    bars_by_scope: tuple[tuple[str, tuple[Any, ...]], ...]
    snapshots: tuple[UnifiedMarketIntelligenceSnapshot, ...]
    latest_snapshot_by_scope: tuple[tuple[str, str], ...]
    regime_state: Mapping[str, Any]
    session_state: Mapping[str, Any]
    news_state: Mapping[str, Any]
    snapshot_by_trusted_observation_id: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "regime_state", MappingProxyType(dict(self.regime_state)))
        object.__setattr__(self, "session_state", MappingProxyType(dict(self.session_state)))
        object.__setattr__(self, "news_state", MappingProxyType(dict(self.news_state)))


class MarketIntelligenceRuntime:
    """Trusted-observation-only coordinator for the Prompt 41 intelligence segment."""

    def __init__(
        self,
        configuration: MarketIntelligenceRuntimeConfiguration = MarketIntelligenceRuntimeConfiguration(),
        *,
        clock: Any,
        audit: Any,
        structure_engine: MarketStructureEngine | None = None,
        feature_engine: FeatureEngine | None = None,
        regime_engine: RegimeEngine | None = None,
        session_engine: SessionEngine | None = None,
        news_engine: NewsRiskEngine | None = None,
        assembler: MarketIntelligenceAssembler | None = None,
    ) -> None:
        errors = configuration.validate()
        if errors:
            raise ValueError(";".join(errors))
        self.configuration = configuration
        self.clock = clock
        self.audit = audit
        self.structure = structure_engine or MarketStructureEngine(clock, audit)
        self.features = feature_engine or FeatureEngine(clock, audit)
        self.regime = regime_engine or RegimeEngine(clock, audit)
        self.session = session_engine or SessionEngine(
            clock,
            audit,
            configuration.session_configuration,
            WeekdayFallbackCalendar(),
        )
        self.news = news_engine or self._default_news_engine(configuration, clock, audit)
        self.assembler = assembler or MarketIntelligenceAssembler(clock, audit)
        self._bars_by_scope: dict[str, tuple[Any, ...]] = defaultdict(tuple)
        self._processed: set[str] = set()
        self.snapshots: OrderedDict[str, UnifiedMarketIntelligenceSnapshot] = OrderedDict()
        self._latest_by_scope: dict[str, str] = {}
        self._snapshot_by_trusted_observation_id: dict[str, str] = {}
        self.recovery_restricted = False

    @property
    def configuration_identity(self) -> str:
        return self.configuration.configuration_snapshot_id

    def process_trusted_observation(
        self,
        trusted: TrustedResearchObservation,
        observation: CanonicalMarketObservation,
        *,
        dataset: CanonicalMarketDataset | None = None,
        logical_time: datetime | None = None,
        recovery_epoch: int | None = None,
    ) -> MarketIntelligenceRuntimeResult:
        as_of = _aware_utc(logical_time or trusted.as_of)
        epoch = trusted.envelope.recovery_epoch if recovery_epoch is None else recovery_epoch
        reasons, warnings = self._validate_boundary(trusted, observation, dataset, as_of, epoch)
        if trusted.trusted_observation_id in self._processed:
            snapshot = self.snapshots.get(self._snapshot_by_trusted_observation_id.get(trusted.trusted_observation_id))
            return MarketIntelligenceRuntimeResult(
                RuntimeAcceptance.DUPLICATE,
                snapshot,
                ("P41_DUPLICATE_TRUSTED_OBSERVATION",),
                warnings,
            )
        if reasons:
            self._record("market_intelligence_observation_blocked", {"trusted_observation_id": trusted.trusted_observation_id, "reasons": reasons})
            return MarketIntelligenceRuntimeResult(RuntimeAcceptance.BLOCKED, None, tuple(dict.fromkeys(reasons)), warnings)

        scope = self._scope(observation, trusted.envelope.dataset_id)
        bar = observation_to_normalized_bar(observation)
        history = tuple(item for item in self._bars_by_scope[scope] if item.close_time and item.close_time <= as_of)
        if not any(item.bar_id == bar.bar_id for item in history):
            history = tuple(sorted((*history, bar), key=lambda item: (item.close_time or item.open_time, item.bar_id)))
        history = history[-self.configuration.maximum_history_per_scope:]
        self._bars_by_scope[scope] = history

        market = self._market_snapshot(trusted, observation, history, as_of, epoch)
        structure = self.structure.analyze(market, configuration_hash=self.configuration_identity)
        features = self.features.snapshot(
            market,
            self.configuration.default_feature_requests,
            configuration_hash=self.configuration_identity,
            structure_snapshot_id=structure.structure_snapshot_id if structure else None,
        )
        if structure is None or features is None:
            return MarketIntelligenceRuntimeResult(
                RuntimeAcceptance.UNAVAILABLE,
                None,
                tuple(reason for reason, value in (("P41_STRUCTURE_UNAVAILABLE", structure), ("P41_FEATURES_UNAVAILABLE", features)) if value is None),
                warnings,
            )
        regime = self.regime.analyze(market, structure, features, configuration_hash=self.configuration_identity)
        session = self.session.analyze(market)
        news = self.news.analyze(as_of, observation.instrument.canonical_id, self.configuration_identity, epoch, configuration_hash=self.configuration_identity)
        if regime is None or session is None:
            return MarketIntelligenceRuntimeResult(
                RuntimeAcceptance.UNAVAILABLE,
                None,
                tuple(reason for reason, value in (("P41_REGIME_UNAVAILABLE", regime), ("P41_SESSION_UNAVAILABLE", session)) if value is None),
                warnings,
            )
        intelligence = self.assembler.assemble(market, structure, features, regime, session, news)
        if intelligence is None:
            return MarketIntelligenceRuntimeResult(RuntimeAcceptance.UNAVAILABLE, None, ("P41_INTELLIGENCE_LINEAGE_REJECTED",), warnings)
        unified = self._unified_snapshot(trusted, observation, intelligence, as_of, epoch, warnings)
        self.snapshots[unified.unified_snapshot_id] = unified
        self._latest_by_scope[scope] = unified.unified_snapshot_id
        self._processed.add(trusted.trusted_observation_id)
        self._snapshot_by_trusted_observation_id[trusted.trusted_observation_id] = unified.unified_snapshot_id
        self._bound()
        self._record(
            "unified_market_intelligence_snapshot_created",
            {
                "unified_snapshot_id": unified.unified_snapshot_id,
                "health": unified.intelligence_health.name,
                "availability": unified.intelligence_availability.name,
            },
        )
        return MarketIntelligenceRuntimeResult(RuntimeAcceptance.ACCEPTED, unified, unified.reason_codes, warnings)

    def recovery_state(self, recovery_epoch: int) -> MarketIntelligenceRecoveryState:
        return MarketIntelligenceRecoveryState(
            UNIFIED_INTELLIGENCE_SCHEMA_VERSION,
            MARKET_INTELLIGENCE_RUNTIME_VERSION,
            self.configuration_identity,
            recovery_epoch,
            tuple(sorted(self._processed)),
            tuple(sorted((scope, bars) for scope, bars in self._bars_by_scope.items())),
            tuple(self.snapshots.values()),
            tuple(sorted(self._latest_by_scope.items())),
            self.regime.recovery_state(),
            self.session.recovery_state(),
            self.news.recovery_state(),
            tuple(sorted(self._snapshot_by_trusted_observation_id.items())),
        )

    def restore(self, state: MarketIntelligenceRecoveryState, expected_recovery_epoch: int) -> bool:
        if (
            state.schema_version != UNIFIED_INTELLIGENCE_SCHEMA_VERSION
            or state.runtime_version != MARKET_INTELLIGENCE_RUNTIME_VERSION
            or state.configuration_snapshot_id != self.configuration_identity
            or state.recovery_epoch != expected_recovery_epoch
        ):
            self.recovery_restricted = True
            return False
        try:
            self._processed = set(state.processed_trusted_observation_ids)
            self._bars_by_scope = defaultdict(tuple, {scope: bars for scope, bars in state.bars_by_scope})
            self.snapshots = OrderedDict((snapshot.unified_snapshot_id, snapshot) for snapshot in state.snapshots)
            if len(self.snapshots) != len(state.snapshots):
                raise ValueError("duplicate snapshot in recovery state")
            self._latest_by_scope = dict(state.latest_snapshot_by_scope)
            self._snapshot_by_trusted_observation_id = dict(state.snapshot_by_trusted_observation_id)
            self._restore_regime_state(state.regime_state)
            self._restore_session_state(state.session_state)
            self.recovery_restricted = False
            return True
        except Exception:
            self.recovery_restricted = True
            return False

    def reconcile(self, recovery_epoch: int) -> tuple[str, ...]:
        issues: list[str] = []
        if self.recovery_restricted:
            issues.append("P41_RECOVERY_RESTRICTED")
        if any(snapshot.recovery_epoch > recovery_epoch for snapshot in self.snapshots.values()):
            issues.append("P41_RECOVERY_EPOCH_REGRESSION")
        for scope, snapshot_id in self._latest_by_scope.items():
            if snapshot_id not in self.snapshots:
                issues.append(f"P41_LATEST_SNAPSHOT_MISSING:{scope}")
        return tuple(dict.fromkeys(issues))

    def diagnostics(self) -> dict[str, Any]:
        latest = next(reversed(self.snapshots.values()), None) if self.snapshots else None
        return {
            "schema_version": UNIFIED_INTELLIGENCE_SCHEMA_VERSION,
            "schema_identity": market_intelligence_schema_identity(),
            "runtime_version": MARKET_INTELLIGENCE_RUNTIME_VERSION,
            "configuration_identity": self.configuration_identity,
            "trusted_observation_input_required": True,
            "raw_observation_bypass_available": False,
            "snapshot_count": len(self.snapshots),
            "scope_count": len(self._bars_by_scope),
            "latest_snapshot": _snapshot_summary(latest),
            "recovery_restricted": self.recovery_restricted,
            "component_chain": [
                "data_trust",
                "market_structure",
                "market_features",
                "market_regime",
                "market_session",
                "market_event_context",
                "market_intelligence",
            ],
            "schema_lineage": {
                "p39_observation_schema_identity": market_data_schema_identity("observation"),
                "p39_dataset_manifest_schema_identity": market_data_schema_identity("dataset_manifest"),
                "p40_quality_trust_schema_identity": quality_trust_schema_identity(),
                "p41_market_intelligence_schema_identity": market_intelligence_schema_identity(),
            },
            "research_pipeline_active": False,
            "financial_execution_available": False,
        }

    def component_ready(self, context: Any) -> bool:
        return not self.recovery_restricted

    def component_health(self, context: Any) -> HealthStatus:
        return HealthStatus.DEGRADED if self.recovery_restricted else HealthStatus.HEALTHY

    def _validate_boundary(
        self,
        trusted: TrustedResearchObservation,
        observation: CanonicalMarketObservation,
        dataset: CanonicalMarketDataset | None,
        as_of: datetime,
        recovery_epoch: int,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        reasons: list[str] = []
        warnings = list(trusted.warning_reasons)
        if trusted.trust_status not in (TrustStatus.TRUSTED, TrustStatus.TRUSTED_WITH_WARNINGS):
            reasons.append(f"P41_TRUST_STATUS_BLOCKED:{trusted.trust_status.value}")
        if not trusted.authoritative_effect_applied:
            reasons.append("P41_TRUSTED_OBSERVATION_NOT_AUTHORITATIVE")
        if trusted.blocking_reasons:
            reasons.extend(f"P41_UPSTREAM_BLOCKER:{reason}" for reason in trusted.blocking_reasons)
        envelope = trusted.envelope
        expected = {
            "observation_id": observation.observation_id,
            "observation_fingerprint": observation.observation_fingerprint,
            "source_id": observation.source.source_id,
            "schema_version": observation.schema_version,
        }
        for field_name, value in expected.items():
            if getattr(envelope, field_name) != value:
                reasons.append(f"P41_TRUST_ENVELOPE_{field_name.upper()}_MISMATCH")
        if dataset is not None:
            if envelope.dataset_id != dataset.manifest.dataset_id:
                reasons.append("P41_TRUST_ENVELOPE_DATASET_ID_MISMATCH")
            if envelope.dataset_fingerprint != dataset.manifest.dataset_fingerprint:
                reasons.append("P41_TRUST_ENVELOPE_DATASET_FINGERPRINT_MISMATCH")
        if envelope.configuration_identity and envelope.configuration_identity != trusted.envelope.configuration_identity:
            reasons.append("P41_TRUST_ENVELOPE_CONFIGURATION_MISMATCH")
        if envelope.recovery_epoch != recovery_epoch:
            reasons.append("P41_TRUST_ENVELOPE_RECOVERY_EPOCH_MISMATCH")
        validation = validate_canonical_observation(observation, logical_time=as_of)
        if not validation.valid:
            reasons.extend(f"P41_CANONICAL_VALIDATION:{issue.reason.value}" for issue in validation.issues)
        if observation.available_at > as_of:
            reasons.append("P41_OBSERVATION_NOT_AVAILABLE_AT_KNOWLEDGE_CUTOFF")
        if trusted.trust_status is TrustStatus.TRUSTED_WITH_WARNINGS:
            warnings.append("P41_ACCEPTED_TRUSTED_WITH_WARNINGS")
        return tuple(dict.fromkeys(reasons)), tuple(dict.fromkeys(warnings))

    def _market_snapshot(
        self,
        trusted: TrustedResearchObservation,
        observation: CanonicalMarketObservation,
        bars: tuple[Any, ...],
        as_of: datetime,
        recovery_epoch: int,
    ) -> MarketDataSnapshot:
        latest = bars[-1]
        provenance = DataProvenance(
            observation.source.source_id,
            trusted.envelope.dataset_id,
            observation.source.source_version,
            trusted.envelope.dataset_fingerprint,
            observation.source.adapter_type,
            observation.received_at,
            "UTC",
            "UTC",
            observation.instrument.canonical_id,
            observation.timeframe,
            actual_start=bars[0].open_time if bars else None,
            actual_end=latest.close_time if bars else None,
        )
        spread = SpreadState(
            latest.spread,
            latest.spread,
            None,
            None,
            None,
            SpreadHealth.NORMAL if latest.spread is not None else SpreadHealth.UNAVAILABLE,
            SpreadOrigin.OBSERVED if latest.spread is not None else SpreadOrigin.UNAVAILABLE,
        )
        snapshot_id = deterministic_id(
            "p41_market_data_snapshot",
            trusted.trusted_observation_id,
            trusted.envelope.dataset_id,
            trusted.envelope.dataset_fingerprint,
            observation.instrument.canonical_id,
            observation.timeframe,
            as_of.isoformat(),
            self.configuration_identity,
            recovery_epoch,
            *(item.bar_id for item in bars),
        )
        return MarketDataSnapshot(
            snapshot_id,
            self.clock.now(),
            as_of,
            self.configuration.experiment_id,
            trusted.envelope.dataset_id,
            trusted.envelope.dataset_fingerprint,
            observation.instrument.canonical_id,
            spread,
            bars,
            bars,
            bars,
            SynchronizationStatus.SYNCHRONIZED,
            DataHealth.HEALTHY,
            100.0,
            {observation.source.source_id: provenance},
            self.configuration_identity,
            recovery_epoch,
        )

    def _unified_snapshot(
        self,
        trusted: TrustedResearchObservation,
        observation: CanonicalMarketObservation,
        intelligence: MarketIntelligenceSnapshot,
        as_of: datetime,
        recovery_epoch: int,
        warnings: tuple[str, ...],
    ) -> UnifiedMarketIntelligenceSnapshot:
        components = _component_availability(intelligence)
        identity = deterministic_id(
            "p41_unified_market_intelligence",
            trusted.trusted_observation_id,
            intelligence.market_intelligence_snapshot_id,
            as_of.isoformat(),
            market_intelligence_schema_identity(),
            recovery_epoch,
        )
        fingerprint = _sha256_json(
            {
                "schema_version": UNIFIED_INTELLIGENCE_SCHEMA_VERSION,
                "trusted_observation_id": trusted.trusted_observation_id,
                "quality_snapshot_id": trusted.quality_snapshot_id,
                "observation_id": observation.observation_id,
                "observation_fingerprint": observation.observation_fingerprint,
                "market_intelligence_snapshot_id": intelligence.market_intelligence_snapshot_id,
                "component_ids": {key: value.snapshot_id for key, value in components.items()},
                "health": intelligence.overall_intelligence_health.name,
                "availability": intelligence.intelligence_availability.name,
                "as_of": as_of,
                "configuration_snapshot_id": self.configuration_identity,
                "recovery_epoch": recovery_epoch,
            }
        )
        return UnifiedMarketIntelligenceSnapshot(
            identity,
            UNIFIED_INTELLIGENCE_SCHEMA_VERSION,
            market_intelligence_schema_identity(),
            fingerprint,
            self.clock.now(),
            intelligence.as_of_timestamp_utc,
            as_of,
            trusted.trusted_observation_id,
            observation.observation_id,
            observation.observation_fingerprint,
            trusted.trust_status.value,
            trusted.quality_snapshot_id,
            trusted.source_health_snapshot_id,
            trusted.envelope.dataset_id,
            trusted.envelope.dataset_fingerprint,
            observation.source.source_id,
            observation.instrument.canonical_id,
            observation.timeframe,
            intelligence.market_intelligence_snapshot_id,
            intelligence,
            components,
            intelligence.overall_intelligence_health,
            intelligence.intelligence_availability,
            intelligence.restrictions,
            tuple(dict.fromkeys((*warnings, *intelligence.warnings))),
            intelligence.reason_codes,
            False,
            "NONE",
            self.configuration_identity,
            recovery_epoch,
        )

    def _default_news_engine(self, configuration: MarketIntelligenceRuntimeConfiguration, clock: Any, audit: Any) -> NewsRiskEngine:
        start = datetime(1970, 1, 1, tzinfo=timezone.utc)
        end = datetime(2100, 1, 1, tzinfo=timezone.utc)
        provider = DeterministicEventProvider(
            (),
            provider_id="P41_OFFLINE_EVENTS",
            provider_version="1",
            dataset_id="P41_EMPTY_EVENT_DATASET",
            coverage_start_utc=start,
            coverage_end_utc=end,
            imported_at_utc=start,
            source_description="Prompt 41 deterministic empty event context",
            health=EventProviderHealth.HEALTHY,
            configuration_snapshot_id=configuration.configuration_snapshot_id,
        )
        return NewsRiskEngine(clock, audit, TimeZoneService(), provider, configuration.event_configuration)

    def _restore_regime_state(self, state: Mapping[str, Any]) -> None:
        from amrte.market.regime import PrimaryRegime

        stable = state.get("stable_regime")
        candidate = state.get("candidate_regime")
        if stable in PrimaryRegime.__members__:
            self.regime._stable = PrimaryRegime[stable]
        if candidate in PrimaryRegime.__members__:
            self.regime._candidate = PrimaryRegime[candidate]
        self.regime._candidate_count = int(state.get("candidate_count", 0) or 0)
        self.regime._persistence = int(state.get("persistence", 0) or 0)
        self.regime._cooldown = int(state.get("cooldown", 0) or 0)

    def _restore_session_state(self, state: Mapping[str, Any]) -> None:
        last = state.get("last_processed_utc")
        if isinstance(last, str):
            self.session._last_instant = datetime.fromisoformat(last.replace("Z", "+00:00")).astimezone(timezone.utc)

    def _bound(self) -> None:
        while len(self.snapshots) > self.configuration.maximum_snapshots:
            _, removed = self.snapshots.popitem(last=False)
            for scope, snapshot_id in tuple(self._latest_by_scope.items()):
                if snapshot_id == removed.unified_snapshot_id:
                    del self._latest_by_scope[scope]
            for trusted_id, snapshot_id in tuple(self._snapshot_by_trusted_observation_id.items()):
                if snapshot_id == removed.unified_snapshot_id:
                    del self._snapshot_by_trusted_observation_id[trusted_id]
        while len(self._processed) > self.configuration.maximum_snapshots:
            self._processed = set(sorted(self._processed)[-self.configuration.maximum_snapshots:])

    def _scope(self, observation: CanonicalMarketObservation, dataset_id: str) -> str:
        return "|".join((observation.source.source_id, dataset_id, observation.instrument.canonical_id, observation.timeframe))

    def _record(self, event: str, payload: Mapping[str, Any]) -> None:
        if self.audit is not None:
            self.audit.record(event, payload)


class MarketIntelligenceRuntimeComponent:
    def __init__(
        self,
        component_id: str,
        runtime: MarketIntelligenceRuntime | None = None,
        runtime_holder: dict[str, MarketIntelligenceRuntime] | None = None,
    ) -> None:
        self.component_id = component_id
        self.runtime = runtime
        self._runtime_holder = runtime_holder

    def initialize_component(self, context: Any) -> None:
        if self.runtime is None:
            if self._runtime_holder is not None and "runtime" in self._runtime_holder:
                self.runtime = self._runtime_holder["runtime"]
            else:
                clock = context.services["clock"]
                audit = context.services["audit"]
                self.runtime = MarketIntelligenceRuntime(clock=clock, audit=audit)
                if self._runtime_holder is not None:
                    self._runtime_holder["runtime"] = self.runtime
        audit = context.services.get("audit") if hasattr(context, "services") else None
        if audit is not None:
            audit.record(
                "market_intelligence_runtime_initialized",
                {"component_id": self.component_id, "schema_identity": market_intelligence_schema_identity()},
            )

    def component_ready(self, context: Any) -> bool:
        return self.runtime is not None and self.runtime.component_ready(context)

    def component_health(self, context: Any) -> HealthStatus:
        if self.runtime is None:
            return HealthStatus.UNKNOWN
        return self.runtime.component_health(context)

    def diagnostics(self) -> dict[str, Any]:
        payload = self.runtime.diagnostics() if self.runtime is not None else {}
        payload["component_id"] = self.component_id
        return payload


def market_intelligence_schema_identity() -> str:
    payload = {
        "schema": "p41_unified_market_intelligence_snapshot",
        "version": UNIFIED_INTELLIGENCE_SCHEMA_VERSION,
        "runtime_version": MARKET_INTELLIGENCE_RUNTIME_VERSION,
        "snapshot_fields": tuple(UnifiedMarketIntelligenceSnapshot.__dataclass_fields__),
        "component_availability_fields": tuple(ComponentAvailability.__dataclass_fields__),
        "input_contract": "TrustedResearchObservation",
        "upstream_schema_identities": {
            "p39_observation": market_data_schema_identity("observation"),
            "p39_dataset_manifest": market_data_schema_identity("dataset_manifest"),
            "p40_quality_trust": quality_trust_schema_identity(),
        },
    }
    return _sha256_json(payload)


def market_intelligence_component_registrations() -> tuple[tuple[ComponentMetadata, MarketIntelligenceRuntimeComponent], ...]:
    capabilities = ComponentCapabilities(lifecycle=True, persistence=True, recovery=True, health=True, diagnostics=True, activation=True)
    runtime_holder: dict[str, MarketIntelligenceRuntime] = {}
    definitions = (
        ("market_structure", ("data_trust",)),
        ("market_features", ("data_trust", "market_structure")),
        ("market_session", ("data_trust",)),
        ("market_event_context", ("data_trust",)),
        ("market_regime", ("market_structure", "market_features")),
        ("market_intelligence", ("market_regime", "market_session", "market_event_context")),
    )
    return tuple(
        (
            ComponentMetadata(
                component_id=component_id,
                component_type=ComponentType.RESEARCH,
                component_version=MARKET_INTELLIGENCE_RUNTIME_VERSION,
                required=True,
                dependencies=dependencies,
                capabilities=capabilities,
            ),
            MarketIntelligenceRuntimeComponent(component_id, runtime_holder=runtime_holder),
        )
        for component_id, dependencies in definitions
    )


def market_intelligence_components_from_inventory(inventory: tuple[Mapping[str, Any], ...]) -> dict[str, Mapping[str, Any]]:
    ids = {"market_structure", "market_features", "market_session", "market_event_context", "market_regime", "market_intelligence"}
    return {item["component_id"]: item for item in inventory if item.get("component_id") in ids}


def _component_availability(intelligence: MarketIntelligenceSnapshot) -> dict[str, ComponentAvailability]:
    values = {
        "market_data": (intelligence.market_data_snapshot_id, intelligence.data_health.name, True, intelligence.data_health.name == "HEALTHY"),
        "market_structure": (intelligence.structure_snapshot_id, intelligence.structure_health.name, True, intelligence.structure_health.name == "HEALTHY"),
        "market_features": (intelligence.feature_snapshot_id, intelligence.feature_health.name, True, intelligence.feature_health.name in {"VALID", "VALID_WITH_WARNINGS"}),
        "market_regime": (intelligence.regime_snapshot_id, intelligence.regime_health.name, True, intelligence.regime_health.name == "HEALTHY"),
        "market_session": (intelligence.session_snapshot_id, intelligence.session_health.name, True, intelligence.session_health.name == "HEALTHY"),
        "market_event_context": (intelligence.news_risk_snapshot_id, intelligence.news_risk_health.name, True, intelligence.news_risk_health.name == "HEALTHY"),
        "market_intelligence": (intelligence.market_intelligence_snapshot_id, intelligence.overall_intelligence_health.name, True, intelligence.intelligence_availability.name == "AVAILABLE"),
    }
    return {
        key: ComponentAvailability(key, snapshot_id, health, critical, available, () if available else (health,))
        for key, (snapshot_id, health, critical, available) in values.items()
    }


def _snapshot_summary(snapshot: UnifiedMarketIntelligenceSnapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {
        "unified_snapshot_id": snapshot.unified_snapshot_id,
        "snapshot_fingerprint": snapshot.snapshot_fingerprint,
        "as_of_timestamp_utc": _jsonable(snapshot.as_of_timestamp_utc),
        "trusted_observation_id": snapshot.trusted_observation_id,
        "observation_id": snapshot.observation_id,
        "dataset_id": snapshot.dataset_id,
        "dataset_fingerprint": snapshot.dataset_fingerprint,
        "instrument_id": snapshot.instrument_id,
        "timeframe": snapshot.timeframe,
        "intelligence_health": snapshot.intelligence_health.name,
        "intelligence_availability": snapshot.intelligence_availability.name,
        "component_availability": _jsonable(snapshot.component_availability),
        "research_pipeline_active": snapshot.research_pipeline_active,
        "financial_execution": snapshot.financial_execution,
    }


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("P41_NAIVE_KNOWLEDGE_CUTOFF")
    return value.astimezone(timezone.utc)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(nested) for key, nested in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {field: _jsonable(getattr(value, field)) for field in value.__dataclass_fields__}
    return value
