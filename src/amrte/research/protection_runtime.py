from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from amrte.core.composition import ComponentCapabilities, ComponentMetadata, ComponentType
from amrte.core.identity import deterministic_id
from amrte.core.types import HealthStatus
from amrte.portfolio.research_portfolio_runtime import (
    PORTFOLIO_RESEARCH_SNAPSHOT_SCHEMA_VERSION,
    PortfolioResearchSnapshot,
    portfolio_research_snapshot_schema_identity,
)


RESEARCH_PROTECTION_RUNTIME_VERSION = "1.0"
RESEARCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION = "1.0"
PROTECTION_EVIDENCE_SCHEMA_VERSION = "1.0"


class ResearchProtectionPermission(Enum):
    ALLOWED = "ALLOWED"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class ProtectionRestrictionCategory(Enum):
    DATA_QUALITY = "DATA_QUALITY"
    RELIABILITY = "RELIABILITY"
    TEMPORAL = "TEMPORAL"
    STRATEGY_HEALTH = "STRATEGY_HEALTH"
    ABNORMAL_MARKET = "ABNORMAL_MARKET"
    LIFECYCLE = "LIFECYCLE"
    DEPENDENCY = "DEPENDENCY"
    RECOVERY = "RECOVERY"
    STALE_STATE = "STALE_STATE"
    SYSTEMIC = "SYSTEMIC"
    UPSTREAM = "UPSTREAM"
    UNKNOWN = "UNKNOWN"


PERMISSION_RANK = {
    ResearchProtectionPermission.ALLOWED.value: 0,
    ResearchProtectionPermission.RESTRICTED.value: 1,
    ResearchProtectionPermission.BLOCKED.value: 2,
}

SEVERITY_RANK = {"CRITICAL": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2, "INFO": 1, "UNKNOWN": 0}


@dataclass(frozen=True)
class ResearchProtectionRuntimeConfiguration:
    configuration_snapshot_id: str = "P45_RESEARCH_PROTECTION_DEFAULT"
    policy_version: str = "1.0"
    stale_after_seconds: int = 7200
    maximum_snapshots: int = 1024
    maximum_restrictions: int = 4096
    maximum_cooldowns: int = 1024
    require_positive_safety_evidence: bool = True
    require_lifecycle_evidence: bool = True
    require_dependency_evidence: bool = True

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.configuration_snapshot_id.strip():
            errors.append("P45_CONFIGURATION_ID_REQUIRED")
        if not self.policy_version.strip():
            errors.append("P45_POLICY_VERSION_REQUIRED")
        if self.stale_after_seconds <= 0:
            errors.append("P45_STALENESS_THRESHOLD_INVALID")
        if min(self.maximum_snapshots, self.maximum_restrictions, self.maximum_cooldowns) < 1:
            errors.append("P45_BOUNDS_INVALID")
        return tuple(dict.fromkeys(errors))


@dataclass(frozen=True)
class DependencyProtectionEvidence:
    component_id: str
    required: bool
    status: str
    health: str
    evidence_id: str
    as_of_timestamp_utc: datetime
    stale: bool = False


@dataclass(frozen=True)
class CooldownEvidence:
    cooldown_id: str
    reason: str
    started_at_utc: datetime
    eligible_reassessment_at_utc: datetime
    status: str
    trigger_evidence_id: str


@dataclass(frozen=True)
class ResearchProtectionEvidence:
    evidence_id: str
    schema_version: str
    schema_identity: str
    dataset_id: str
    dataset_fingerprint: str
    as_of_timestamp_utc: datetime
    knowledge_cutoff_utc: datetime
    configuration_identity: str
    recovery_epoch: int
    observation_trust_status: str | None = None
    observation_evidence_id: str | None = None
    reliability_stage: str | None = None
    reliability_evidence_id: str | None = None
    strategy_health: str | None = None
    strategy_health_evidence_id: str | None = None
    temporal_stage: str | None = None
    temporal_evidence_id: str | None = None
    cooldowns: tuple[CooldownEvidence, ...] = ()
    degradation_states: tuple[Mapping[str, Any], ...] = ()
    abnormal_condition_state: str | None = None
    lifecycle_state: str | None = None
    lifecycle_health: str | None = None
    lifecycle_evidence_id: str | None = None
    dependency_states: tuple[DependencyProtectionEvidence, ...] = ()
    recovery_restricted: bool = False
    recovery_evidence_id: str | None = None
    system_safety_state: str | None = None
    system_safety_evidence_id: str | None = None
    warnings: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "degradation_states", tuple(MappingProxyType(dict(item)) for item in self.degradation_states))

    @classmethod
    def create(
        cls,
        *,
        dataset_id: str,
        dataset_fingerprint: str,
        as_of_timestamp_utc: datetime,
        knowledge_cutoff_utc: datetime,
        configuration_identity: str,
        recovery_epoch: int,
        observation_trust_status: str | None = "TRUSTED",
        reliability_stage: str | None = "NORMAL",
        strategy_health: str | None = "HEALTHY",
        temporal_stage: str | None = "NORMAL",
        lifecycle_state: str | None = "ACTIVE",
        lifecycle_health: str | None = "HEALTHY",
        system_safety_state: str | None = "NORMAL",
        dependency_states: tuple[DependencyProtectionEvidence, ...] = (),
        cooldowns: tuple[CooldownEvidence, ...] = (),
        degradation_states: tuple[Mapping[str, Any], ...] = (),
        abnormal_condition_state: str | None = "NORMAL",
        recovery_restricted: bool = False,
        observation_evidence_id: str | None = None,
        reliability_evidence_id: str | None = None,
        strategy_health_evidence_id: str | None = None,
        temporal_evidence_id: str | None = None,
        lifecycle_evidence_id: str | None = None,
        recovery_evidence_id: str | None = None,
        system_safety_evidence_id: str | None = None,
        warnings: tuple[str, ...] = (),
        reason_codes: tuple[str, ...] = (),
    ) -> "ResearchProtectionEvidence":
        payload = {
            "dataset_id": dataset_id,
            "dataset_fingerprint": dataset_fingerprint,
            "as_of": as_of_timestamp_utc,
            "knowledge_cutoff": knowledge_cutoff_utc,
            "configuration_identity": configuration_identity,
            "recovery_epoch": recovery_epoch,
            "observation_trust_status": observation_trust_status,
            "reliability_stage": reliability_stage,
            "strategy_health": strategy_health,
            "temporal_stage": temporal_stage,
            "lifecycle_state": lifecycle_state,
            "lifecycle_health": lifecycle_health,
            "system_safety_state": system_safety_state,
            "dependency_states": dependency_states,
            "cooldowns": cooldowns,
            "degradation_states": degradation_states,
            "abnormal_condition_state": abnormal_condition_state,
            "recovery_restricted": recovery_restricted,
            "reason_codes": reason_codes,
        }
        fingerprint = _sha256_json(payload)
        evidence_id = deterministic_id("p45_research_protection_evidence", fingerprint)
        return cls(
            evidence_id,
            PROTECTION_EVIDENCE_SCHEMA_VERSION,
            protection_evidence_schema_identity(),
            dataset_id,
            dataset_fingerprint,
            as_of_timestamp_utc,
            knowledge_cutoff_utc,
            configuration_identity,
            recovery_epoch,
            observation_trust_status,
            observation_evidence_id or evidence_id,
            reliability_stage,
            reliability_evidence_id or evidence_id,
            strategy_health,
            strategy_health_evidence_id or evidence_id,
            temporal_stage,
            temporal_evidence_id or evidence_id,
            cooldowns,
            degradation_states,
            abnormal_condition_state,
            lifecycle_state,
            lifecycle_health,
            lifecycle_evidence_id or evidence_id,
            dependency_states,
            recovery_restricted,
            recovery_evidence_id or evidence_id,
            system_safety_state,
            system_safety_evidence_id or evidence_id,
            warnings,
            reason_codes,
        )


@dataclass(frozen=True)
class ProtectionRestriction:
    restriction_id: str
    source_component: str
    source_evidence_id: str
    category: str
    severity: str
    effective_permission: str
    reason_code: str
    message: str
    first_observed_at_utc: datetime
    as_of_timestamp_utc: datetime
    knowledge_cutoff_utc: datetime
    configuration_identity: str
    recovery_epoch: int


@dataclass(frozen=True)
class ResearchProtectionSnapshot:
    protection_snapshot_id: str
    schema_version: str
    schema_identity: str
    p44_snapshot_id: str
    p44_snapshot_fingerprint: str
    p44_schema_identity: str
    as_of_timestamp_utc: datetime
    knowledge_cutoff_utc: datetime
    effective_permission: str
    upstream_restrictions: tuple[Mapping[str, Any], ...]
    observation_protection: Mapping[str, Any]
    reliability_assessment: Mapping[str, Any]
    strategy_health_assessment: Mapping[str, Any]
    temporal_assessment: Mapping[str, Any]
    cooldown_assessment: Mapping[str, Any]
    degradation_assessment: Mapping[str, Any]
    abnormal_condition_assessment: Mapping[str, Any]
    lifecycle_assessment: Mapping[str, Any]
    dependency_assessment: Mapping[str, Any]
    recovery_assessment: Mapping[str, Any]
    systemic_safety_assessment: Mapping[str, Any]
    aggregate_restrictions: tuple[ProtectionRestriction, ...]
    warnings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    configuration_identity: str
    policy_identity: str
    recovery_epoch: int
    snapshot_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "upstream_restrictions", tuple(MappingProxyType(dict(item)) for item in self.upstream_restrictions))
        for field_name in (
            "observation_protection",
            "reliability_assessment",
            "strategy_health_assessment",
            "temporal_assessment",
            "cooldown_assessment",
            "degradation_assessment",
            "abnormal_condition_assessment",
            "lifecycle_assessment",
            "dependency_assessment",
            "recovery_assessment",
            "systemic_safety_assessment",
        ):
            object.__setattr__(self, field_name, MappingProxyType(dict(getattr(self, field_name))))


@dataclass(frozen=True)
class ResearchProtectionRuntimeResult:
    acceptance: str
    snapshot: ResearchProtectionSnapshot | None
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchProtectionRecoveryState:
    schema_version: str
    runtime_version: str
    p44_schema_identity: str
    protection_schema_identity: str
    evidence_schema_identity: str
    configuration_identity: str
    policy_identity: str
    recovery_epoch: int
    processed_p44_snapshot_ids: tuple[str, ...]
    snapshots: tuple[ResearchProtectionSnapshot, ...]
    active_cooldowns: tuple[CooldownEvidence, ...]


class ResearchProtectionRuntime:
    def __init__(
        self,
        configuration: ResearchProtectionRuntimeConfiguration = ResearchProtectionRuntimeConfiguration(),
        *,
        clock: Any,
        audit: Any,
    ) -> None:
        errors = configuration.validate()
        if errors:
            raise ValueError(";".join(errors))
        self.configuration = configuration
        self.clock = clock
        self.audit = audit
        self.snapshots: OrderedDict[str, ResearchProtectionSnapshot] = OrderedDict()
        self.restrictions: OrderedDict[str, ProtectionRestriction] = OrderedDict()
        self.cooldowns: OrderedDict[str, CooldownEvidence] = OrderedDict()
        self._processed_p44_snapshot_ids: set[str] = set()
        self.recovery_restricted = False
        self.metrics = {
            "p44_snapshots_received": 0,
            "protection_assessments": 0,
            "allowed_states": 0,
            "restricted_states": 0,
            "blocked_states": 0,
            "quality_restrictions": 0,
            "reliability_restrictions": 0,
            "temporal_restrictions": 0,
            "strategy_health_restrictions": 0,
            "cooldowns": 0,
            "degradations": 0,
            "lifecycle_restrictions": 0,
            "dependency_failures": 0,
            "recovery_restrictions": 0,
            "systemic_blocks": 0,
            "recovery_divergences": 0,
        }

    @property
    def configuration_identity(self) -> str:
        return self.configuration.configuration_snapshot_id

    def assess(
        self,
        portfolio_snapshot: PortfolioResearchSnapshot,
        evidence: ResearchProtectionEvidence | None = None,
    ) -> ResearchProtectionRuntimeResult:
        self.metrics["p44_snapshots_received"] += 1
        boundary = self._validate_input(portfolio_snapshot, evidence)
        if portfolio_snapshot.portfolio_snapshot_id in self._processed_p44_snapshot_ids:
            existing = next((item for item in self.snapshots.values() if item.p44_snapshot_id == portfolio_snapshot.portfolio_snapshot_id), None)
            return ResearchProtectionRuntimeResult("DUPLICATE", existing, ("P45_DUPLICATE_P44_SNAPSHOT",))
        if boundary:
            self._record("research_protection_restricted", {"p44_snapshot_id": portfolio_snapshot.portfolio_snapshot_id, "reasons": boundary})
            return ResearchProtectionRuntimeResult("BLOCKED", None, boundary)

        restrictions = list(self._upstream_restrictions(portfolio_snapshot))
        restrictions.extend(self._evidence_restrictions(portfolio_snapshot, evidence))
        restrictions = list(self._dedupe_restrictions(restrictions))
        permission = self.compose_permissions((ResearchProtectionPermission.ALLOWED.value, *(item.effective_permission for item in restrictions)))
        snapshot = self._snapshot(portfolio_snapshot, evidence, tuple(restrictions), permission)

        for item in restrictions:
            self.restrictions[item.restriction_id] = item
        if evidence is not None:
            for cooldown in evidence.cooldowns:
                self.cooldowns[cooldown.cooldown_id] = cooldown
        self.snapshots[snapshot.protection_snapshot_id] = snapshot
        self._processed_p44_snapshot_ids.add(portfolio_snapshot.portfolio_snapshot_id)
        self.metrics["protection_assessments"] += 1
        self.metrics[f"{permission.lower()}_states"] += 1
        self.metrics["quality_restrictions"] += sum(1 for item in restrictions if item.category == ProtectionRestrictionCategory.DATA_QUALITY.value)
        self.metrics["reliability_restrictions"] += sum(1 for item in restrictions if item.category == ProtectionRestrictionCategory.RELIABILITY.value)
        self.metrics["temporal_restrictions"] += sum(1 for item in restrictions if item.category in {ProtectionRestrictionCategory.TEMPORAL.value, ProtectionRestrictionCategory.STALE_STATE.value})
        self.metrics["strategy_health_restrictions"] += sum(1 for item in restrictions if item.category == ProtectionRestrictionCategory.STRATEGY_HEALTH.value)
        self.metrics["cooldowns"] += len(evidence.cooldowns) if evidence is not None else 0
        self.metrics["degradations"] += len(evidence.degradation_states) if evidence is not None else 0
        self.metrics["lifecycle_restrictions"] += sum(1 for item in restrictions if item.category == ProtectionRestrictionCategory.LIFECYCLE.value)
        self.metrics["dependency_failures"] += sum(1 for item in restrictions if item.category == ProtectionRestrictionCategory.DEPENDENCY.value)
        self.metrics["recovery_restrictions"] += sum(1 for item in restrictions if item.category == ProtectionRestrictionCategory.RECOVERY.value)
        self.metrics["systemic_blocks"] += sum(1 for item in restrictions if item.category == ProtectionRestrictionCategory.SYSTEMIC.value and item.effective_permission == ResearchProtectionPermission.BLOCKED.value)
        self._bound()
        self._record("protection_snapshot_published", {"snapshot_id": snapshot.protection_snapshot_id, "permission": permission})
        return ResearchProtectionRuntimeResult("ACCEPTED", snapshot, snapshot.reason_codes, snapshot.warnings)

    @staticmethod
    def compose_permissions(permissions: tuple[str, ...]) -> str:
        if not permissions:
            return ResearchProtectionPermission.BLOCKED.value
        return max(permissions, key=lambda item: PERMISSION_RANK.get(item, PERMISSION_RANK[ResearchProtectionPermission.BLOCKED.value]))

    def recovery_state(self, recovery_epoch: int) -> ResearchProtectionRecoveryState:
        return ResearchProtectionRecoveryState(
            RESEARCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION,
            RESEARCH_PROTECTION_RUNTIME_VERSION,
            portfolio_research_snapshot_schema_identity(),
            research_protection_snapshot_schema_identity(),
            protection_evidence_schema_identity(),
            self.configuration_identity,
            self._policy_identity(),
            recovery_epoch,
            tuple(sorted(self._processed_p44_snapshot_ids)),
            tuple(self.snapshots.values()),
            tuple(self.cooldowns.values()),
        )

    def restore(self, state: ResearchProtectionRecoveryState, expected_recovery_epoch: int) -> bool:
        if (
            state.schema_version != RESEARCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION
            or state.runtime_version != RESEARCH_PROTECTION_RUNTIME_VERSION
            or state.p44_schema_identity != portfolio_research_snapshot_schema_identity()
            or state.protection_schema_identity != research_protection_snapshot_schema_identity()
            or state.evidence_schema_identity != protection_evidence_schema_identity()
            or state.configuration_identity != self.configuration_identity
            or state.policy_identity != self._policy_identity()
            or state.recovery_epoch != expected_recovery_epoch
        ):
            self.recovery_restricted = True
            self.metrics["recovery_divergences"] += 1
            return False
        self._processed_p44_snapshot_ids = set(state.processed_p44_snapshot_ids)
        self.snapshots = OrderedDict((item.protection_snapshot_id, item) for item in state.snapshots)
        self.restrictions = OrderedDict((restriction.restriction_id, restriction) for item in state.snapshots for restriction in item.aggregate_restrictions)
        self.cooldowns = OrderedDict((item.cooldown_id, item) for item in state.active_cooldowns)
        self.recovery_restricted = False
        self._bound()
        self._record("research_protection_runtime_recovered", {"snapshots": len(self.snapshots)})
        return True

    def reconcile(self, recovery_epoch: int) -> tuple[str, ...]:
        issues: list[str] = []
        if self.recovery_restricted:
            issues.append("P45_RECOVERY_RESTRICTED")
        if any(item.recovery_epoch > recovery_epoch for item in self.snapshots.values()):
            issues.append("P45_RECOVERY_EPOCH_REGRESSION")
        if any(item.effective_permission == ResearchProtectionPermission.ALLOWED.value and item.aggregate_restrictions for item in self.snapshots.values()):
            issues.append("P45_PERMISSION_RESTRICTION_DIVERGENCE")
        return tuple(dict.fromkeys(issues))

    def diagnostics(self) -> dict[str, Any]:
        latest = next(reversed(self.snapshots.values()), None) if self.snapshots else None
        return {
            "runtime_version": RESEARCH_PROTECTION_RUNTIME_VERSION,
            "protection_snapshot_schema_version": RESEARCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION,
            "protection_snapshot_schema_identity": research_protection_snapshot_schema_identity(),
            "protection_evidence_schema_version": PROTECTION_EVIDENCE_SCHEMA_VERSION,
            "protection_evidence_schema_identity": protection_evidence_schema_identity(),
            "p44_schema_identity": portfolio_research_snapshot_schema_identity(),
            "configuration_identity": self.configuration_identity,
            "policy": {
                "policy_id": "P45_RESEARCH_PROTECTION_POLICY",
                "version": self.configuration.policy_version,
                "identity": self._policy_identity(),
                "configuration_identity": self.configuration_identity,
                "fail_closed": True,
            },
            "latest_snapshot": _snapshot_summary(latest),
            "metrics": dict(self.metrics),
            "recovery_restricted": self.recovery_restricted,
            "financial_execution": "NONE",
        }

    def component_ready(self, context: Any) -> bool:
        return not self.recovery_restricted and not self.configuration.validate()

    def component_health(self, context: Any) -> HealthStatus:
        return HealthStatus.DEGRADED if self.recovery_restricted else HealthStatus.HEALTHY

    def _validate_input(self, snapshot: PortfolioResearchSnapshot, evidence: ResearchProtectionEvidence | None) -> tuple[str, ...]:
        reasons: list[str] = []
        if snapshot.schema_version != PORTFOLIO_RESEARCH_SNAPSHOT_SCHEMA_VERSION:
            reasons.append("P45_P44_SCHEMA_VERSION_MISMATCH")
        if snapshot.schema_identity != portfolio_research_snapshot_schema_identity():
            reasons.append("P45_P44_SCHEMA_MISMATCH")
        expected = deterministic_id("p44_portfolio_research_snapshot", snapshot.snapshot_fingerprint)
        if snapshot.portfolio_snapshot_id != expected:
            reasons.append("P45_P44_IDENTITY_MISMATCH")
        if not snapshot.p43_assessment_id or not snapshot.p43_assessment_fingerprint:
            reasons.append("P45_LINEAGE_MISMATCH")
        if not getattr(snapshot, "__dataclass_params__", None) or not snapshot.__dataclass_params__.frozen:
            reasons.append("P45_P44_SNAPSHOT_NOT_IMMUTABLE")
        if evidence is None:
            if self.configuration.require_positive_safety_evidence:
                reasons.append("P45_REQUIRED_EVIDENCE_UNAVAILABLE")
            return tuple(dict.fromkeys(reasons))
        if evidence.schema_version != PROTECTION_EVIDENCE_SCHEMA_VERSION or evidence.schema_identity != protection_evidence_schema_identity():
            reasons.append("P45_PROTECTION_EVIDENCE_SCHEMA_MISMATCH")
        if evidence.knowledge_cutoff_utc != snapshot.knowledge_cutoff_utc:
            reasons.append("P45_KNOWLEDGE_CUTOFF_MISMATCH")
        if evidence.configuration_identity != snapshot.configuration_identity:
            reasons.append("P45_CONFIGURATION_MISMATCH")
        if evidence.recovery_epoch != snapshot.recovery_epoch:
            reasons.append("P45_RECOVERY_EPOCH_MISMATCH")
        if evidence.as_of_timestamp_utc < snapshot.as_of_timestamp_utc or evidence.as_of_timestamp_utc > snapshot.knowledge_cutoff_utc:
            reasons.append("P45_TEMPORAL_RESTRICTED")
        return tuple(dict.fromkeys(reasons))

    def _upstream_restrictions(self, snapshot: PortfolioResearchSnapshot) -> tuple[ProtectionRestriction, ...]:
        permission = self._permission_from_p44_state(snapshot.portfolio_research_state, snapshot)
        items: list[ProtectionRestriction] = []
        if permission != ResearchProtectionPermission.ALLOWED.value:
            items.append(self._restriction("portfolio_research_snapshot", snapshot.portfolio_snapshot_id, ProtectionRestrictionCategory.UPSTREAM.value, "HIGH", permission, "P45_UPSTREAM_P44_RESTRICTED", "P44 portfolio research state is not fully allowed", snapshot.knowledge_cutoff_utc, snapshot.as_of_timestamp_utc, snapshot.knowledge_cutoff_utc, snapshot.recovery_epoch))
        for item in snapshot.aggregate_restrictions:
            severity = item.severity if item.severity in SEVERITY_RANK else "MEDIUM"
            perm = ResearchProtectionPermission.BLOCKED.value if severity in {"CRITICAL", "HIGH"} and ("UNAVAILABLE" in item.reason_code or "BLOCK" in item.reason_code) else ResearchProtectionPermission.RESTRICTED.value
            items.append(self._restriction(item.source_component, item.source_evidence_id, ProtectionRestrictionCategory.UPSTREAM.value, severity, perm, item.reason_code, "Upstream P44 restriction preserved", item.knowledge_cutoff_utc, snapshot.as_of_timestamp_utc, snapshot.knowledge_cutoff_utc, snapshot.recovery_epoch))
        return tuple(items)

    def _evidence_restrictions(self, snapshot: PortfolioResearchSnapshot, evidence: ResearchProtectionEvidence | None) -> tuple[ProtectionRestriction, ...]:
        if evidence is None:
            return (self._restriction("research_protection", snapshot.portfolio_snapshot_id, ProtectionRestrictionCategory.UNKNOWN.value, "CRITICAL", ResearchProtectionPermission.BLOCKED.value, "P45_REQUIRED_EVIDENCE_UNAVAILABLE", "Required protection evidence is unavailable", snapshot.knowledge_cutoff_utc, snapshot.as_of_timestamp_utc, snapshot.knowledge_cutoff_utc, snapshot.recovery_epoch),)
        items: list[ProtectionRestriction] = []
        items.extend(self._map_observation(evidence))
        items.extend(self._map_reliability(evidence))
        items.extend(self._map_strategy_health(evidence))
        items.extend(self._map_temporal(evidence))
        items.extend(self._map_cooldowns(evidence))
        items.extend(self._map_degradations(evidence))
        items.extend(self._map_abnormal(evidence))
        items.extend(self._map_lifecycle(evidence))
        items.extend(self._map_dependencies(evidence))
        items.extend(self._map_recovery(evidence))
        items.extend(self._map_system_safety(evidence))
        if evidence.as_of_timestamp_utc - evidence.knowledge_cutoff_utc > timedelta(seconds=self.configuration.stale_after_seconds):
            items.append(self._evidence_restriction(evidence, "temporal_protection", evidence.evidence_id, ProtectionRestrictionCategory.STALE_STATE.value, "HIGH", ResearchProtectionPermission.BLOCKED.value, "P45_STALE_STATE", "Protection evidence is stale"))
        return tuple(items)

    def _map_observation(self, evidence: ResearchProtectionEvidence) -> tuple[ProtectionRestriction, ...]:
        value = _upper(evidence.observation_trust_status)
        if value in {"TRUSTED", "HEALTHY"}:
            return ()
        if value in {"TRUSTED_WITH_WARNINGS", "RESTRICTED"}:
            return (self._evidence_restriction(evidence, "observation_protection", evidence.observation_evidence_id or evidence.evidence_id, ProtectionRestrictionCategory.DATA_QUALITY.value, "MEDIUM", ResearchProtectionPermission.RESTRICTED.value, "P45_OBSERVATION_PROTECTION_RESTRICTED", "Observation protection is restricted"),)
        return (self._evidence_restriction(evidence, "observation_protection", evidence.observation_evidence_id or evidence.evidence_id, ProtectionRestrictionCategory.DATA_QUALITY.value, "HIGH", ResearchProtectionPermission.BLOCKED.value, "P45_OBSERVATION_PROTECTION_RESTRICTED", "Observation protection evidence is unavailable or blocked"),)

    def _map_reliability(self, evidence: ResearchProtectionEvidence) -> tuple[ProtectionRestriction, ...]:
        value = _upper(evidence.reliability_stage)
        if value == "NORMAL":
            return ()
        if value in {"WATCH", "RESTRICTED", "PROTECTED"}:
            return (self._evidence_restriction(evidence, "research_reliability", evidence.reliability_evidence_id or evidence.evidence_id, ProtectionRestrictionCategory.RELIABILITY.value, "MEDIUM", ResearchProtectionPermission.RESTRICTED.value, "P45_RELIABILITY_RESTRICTED", f"Reliability stage is {value}"),)
        return (self._evidence_restriction(evidence, "research_reliability", evidence.reliability_evidence_id or evidence.evidence_id, ProtectionRestrictionCategory.RELIABILITY.value, "HIGH", ResearchProtectionPermission.BLOCKED.value, "P45_RELIABILITY_RESTRICTED", "Reliability evidence is suspended, unknown, or unavailable"),)

    def _map_strategy_health(self, evidence: ResearchProtectionEvidence) -> tuple[ProtectionRestriction, ...]:
        value = _upper(evidence.strategy_health)
        if value == "HEALTHY":
            return ()
        if value in {"DEGRADED", "RESTRICTED", "STALE"}:
            return (self._evidence_restriction(evidence, "strategy_health_protection", evidence.strategy_health_evidence_id or evidence.evidence_id, ProtectionRestrictionCategory.STRATEGY_HEALTH.value, "MEDIUM", ResearchProtectionPermission.RESTRICTED.value, "P45_STRATEGY_HEALTH_RESTRICTED", f"Strategy health is {value}"),)
        return (self._evidence_restriction(evidence, "strategy_health_protection", evidence.strategy_health_evidence_id or evidence.evidence_id, ProtectionRestrictionCategory.STRATEGY_HEALTH.value, "HIGH", ResearchProtectionPermission.BLOCKED.value, "P45_STRATEGY_HEALTH_RESTRICTED", "Strategy health is unavailable, failed, invalid, or unknown"),)

    def _map_temporal(self, evidence: ResearchProtectionEvidence) -> tuple[ProtectionRestriction, ...]:
        value = _upper(evidence.temporal_stage)
        if value == "NORMAL":
            return ()
        if value in {"WATCH", "RESTRICTED"}:
            return (self._evidence_restriction(evidence, "temporal_protection", evidence.temporal_evidence_id or evidence.evidence_id, ProtectionRestrictionCategory.TEMPORAL.value, "MEDIUM", ResearchProtectionPermission.RESTRICTED.value, "P45_TEMPORAL_RESTRICTED", f"Temporal protection stage is {value}"),)
        return (self._evidence_restriction(evidence, "temporal_protection", evidence.temporal_evidence_id or evidence.evidence_id, ProtectionRestrictionCategory.TEMPORAL.value, "HIGH", ResearchProtectionPermission.BLOCKED.value, "P45_TEMPORAL_RESTRICTED", "Temporal protection is cooldown, suspended, unknown, or unavailable"),)

    def _map_cooldowns(self, evidence: ResearchProtectionEvidence) -> tuple[ProtectionRestriction, ...]:
        items = []
        for cooldown in evidence.cooldowns:
            status = _upper(cooldown.status)
            if status == "ACTIVE":
                items.append(self._evidence_restriction(evidence, "cooldown_protection", cooldown.cooldown_id, ProtectionRestrictionCategory.TEMPORAL.value, "HIGH", ResearchProtectionPermission.BLOCKED.value, "P45_COOLDOWN_ACTIVE", "Cooldown is active"))
            elif status == "EXPIRED_PENDING_CONFIRMATION":
                items.append(self._evidence_restriction(evidence, "cooldown_protection", cooldown.cooldown_id, ProtectionRestrictionCategory.TEMPORAL.value, "MEDIUM", ResearchProtectionPermission.RESTRICTED.value, "P45_COOLDOWN_ACTIVE", "Cooldown expiry requires reassessment confirmation"))
        return tuple(items)

    def _map_degradations(self, evidence: ResearchProtectionEvidence) -> tuple[ProtectionRestriction, ...]:
        items = []
        for item in evidence.degradation_states:
            component = str(item.get("component_id", "degradation"))
            required = bool(item.get("required", True))
            state = _upper(item.get("state"))
            if state in {"DEGRADED", "RESTRICTED"}:
                permission = ResearchProtectionPermission.RESTRICTED.value if not required else ResearchProtectionPermission.RESTRICTED.value
                items.append(self._evidence_restriction(evidence, component, str(item.get("evidence_id", evidence.evidence_id)), ProtectionRestrictionCategory.DEPENDENCY.value, "MEDIUM", permission, "P45_DEGRADED_COMPONENT", f"Component {component} is degraded"))
            elif state in {"FAILED", "UNAVAILABLE", "UNKNOWN"} and required:
                items.append(self._evidence_restriction(evidence, component, str(item.get("evidence_id", evidence.evidence_id)), ProtectionRestrictionCategory.DEPENDENCY.value, "HIGH", ResearchProtectionPermission.BLOCKED.value, "P45_DEPENDENCY_UNAVAILABLE", f"Required component {component} is unavailable"))
        return tuple(items)

    def _map_abnormal(self, evidence: ResearchProtectionEvidence) -> tuple[ProtectionRestriction, ...]:
        value = _upper(evidence.abnormal_condition_state)
        if value in {"NORMAL", "NONE", ""}:
            return ()
        if value in {"CAUTION", "DEGRADED", "ABNORMAL"}:
            return (self._evidence_restriction(evidence, "abnormal_condition_protection", evidence.evidence_id, ProtectionRestrictionCategory.ABNORMAL_MARKET.value, "MEDIUM", ResearchProtectionPermission.RESTRICTED.value, "P45_ABNORMAL_CONDITION_RESTRICTED", f"Abnormal condition state is {value}"),)
        return (self._evidence_restriction(evidence, "abnormal_condition_protection", evidence.evidence_id, ProtectionRestrictionCategory.ABNORMAL_MARKET.value, "HIGH", ResearchProtectionPermission.BLOCKED.value, "P45_ABNORMAL_CONDITION_RESTRICTED", "Abnormal condition is blocked or unknown"),)

    def _map_lifecycle(self, evidence: ResearchProtectionEvidence) -> tuple[ProtectionRestriction, ...]:
        value = _upper(evidence.lifecycle_state)
        health = _upper(evidence.lifecycle_health)
        if value in {"ACTIVE", "SAFEGUARDED", "MONITORED"} and health == "HEALTHY":
            return ()
        if value in {"PROPOSED", "VALIDATED", "AUTHORIZED", "QUEUED", "ACTIVATED", "RECOVERING"} or health in {"DEGRADED", "QUARANTINED"}:
            return (self._evidence_restriction(evidence, "lifecycle_protection", evidence.lifecycle_evidence_id or evidence.evidence_id, ProtectionRestrictionCategory.LIFECYCLE.value, "MEDIUM", ResearchProtectionPermission.RESTRICTED.value, "P45_LIFECYCLE_RESTRICTED", f"Lifecycle state is {value or health}"),)
        return (self._evidence_restriction(evidence, "lifecycle_protection", evidence.lifecycle_evidence_id or evidence.evidence_id, ProtectionRestrictionCategory.LIFECYCLE.value, "HIGH", ResearchProtectionPermission.BLOCKED.value, "P45_LIFECYCLE_RESTRICTED", "Lifecycle evidence is terminal, failed, invalid, or unknown"),)

    def _map_dependencies(self, evidence: ResearchProtectionEvidence) -> tuple[ProtectionRestriction, ...]:
        if not evidence.dependency_states and self.configuration.require_dependency_evidence:
            return (self._evidence_restriction(evidence, "dependency_protection", evidence.evidence_id, ProtectionRestrictionCategory.DEPENDENCY.value, "HIGH", ResearchProtectionPermission.BLOCKED.value, "P45_REQUIRED_EVIDENCE_UNAVAILABLE", "Dependency protection evidence is unavailable"),)
        items = []
        for item in evidence.dependency_states:
            status = _upper(item.status)
            health = _upper(item.health)
            if item.required and (item.stale or status in {"FAILED", "UNAVAILABLE", "STOPPED", "UNKNOWN"} or health in {"UNHEALTHY", "UNKNOWN"}):
                items.append(self._evidence_restriction(evidence, item.component_id, item.evidence_id, ProtectionRestrictionCategory.DEPENDENCY.value, "HIGH", ResearchProtectionPermission.BLOCKED.value, "P45_DEPENDENCY_UNAVAILABLE", f"Required dependency {item.component_id} is unavailable"))
            elif item.required and (status in {"DEGRADED"} or health == "DEGRADED"):
                items.append(self._evidence_restriction(evidence, item.component_id, item.evidence_id, ProtectionRestrictionCategory.DEPENDENCY.value, "MEDIUM", ResearchProtectionPermission.RESTRICTED.value, "P45_DEGRADED_COMPONENT", f"Required dependency {item.component_id} is degraded"))
            elif not item.required and (item.stale or status in {"FAILED", "UNAVAILABLE", "UNKNOWN"} or health in {"UNHEALTHY", "UNKNOWN"}):
                pass
        return tuple(items)

    def _map_recovery(self, evidence: ResearchProtectionEvidence) -> tuple[ProtectionRestriction, ...]:
        if evidence.recovery_restricted or self.recovery_restricted:
            return (self._evidence_restriction(evidence, "recovery_protection", evidence.recovery_evidence_id or evidence.evidence_id, ProtectionRestrictionCategory.RECOVERY.value, "HIGH", ResearchProtectionPermission.BLOCKED.value, "P45_RECOVERY_RESTRICTED", "Recovery state is restricted"),)
        return ()

    def _map_system_safety(self, evidence: ResearchProtectionEvidence) -> tuple[ProtectionRestriction, ...]:
        value = _upper(evidence.system_safety_state)
        if value == "NORMAL":
            return ()
        if value in {"CAUTION", "RESTRICTED", "PROBATION"}:
            return (self._evidence_restriction(evidence, "system_safety", evidence.system_safety_evidence_id or evidence.evidence_id, ProtectionRestrictionCategory.SYSTEMIC.value, "MEDIUM", ResearchProtectionPermission.RESTRICTED.value, "P45_SYSTEM_SAFETY_BLOCKED", f"System safety state is {value}"),)
        return (self._evidence_restriction(evidence, "system_safety", evidence.system_safety_evidence_id or evidence.evidence_id, ProtectionRestrictionCategory.SYSTEMIC.value, "CRITICAL", ResearchProtectionPermission.BLOCKED.value, "P45_SYSTEM_SAFETY_BLOCKED", "System safety is blocked, recovery pending, emergency, or unknown"),)

    def _snapshot(self, p44: PortfolioResearchSnapshot, evidence: ResearchProtectionEvidence | None, restrictions: tuple[ProtectionRestriction, ...], permission: str) -> ResearchProtectionSnapshot:
        reason_codes = tuple(dict.fromkeys((
            "P45_RESEARCH_ONLY",
            "P45_ALLOWED_IS_NOT_AUTHORIZATION",
            *p44.reason_codes,
            *(evidence.reason_codes if evidence else ()),
            *(item.reason_code for item in restrictions),
            permission,
        )))
        warnings = tuple(sorted(set((*p44.warnings, *((evidence.warnings if evidence else ()))))))
        upstream = tuple(
            {
                "restriction_id": item.restriction_id,
                "source_component": item.source_component,
                "reason_code": item.reason_code,
                "severity": item.severity,
            }
            for item in restrictions
            if item.category == ProtectionRestrictionCategory.UPSTREAM.value
        )
        assessments = self._assessment_payloads(evidence)
        fingerprint = _sha256_json(
            {
                "p44_snapshot_id": p44.portfolio_snapshot_id,
                "p44_fingerprint": p44.snapshot_fingerprint,
                "evidence": evidence.evidence_id if evidence else "MISSING",
                "permission": permission,
                "restrictions": tuple(item.restriction_id for item in restrictions),
                "configuration_identity": self.configuration_identity,
                "policy_identity": self._policy_identity(),
                "recovery_epoch": p44.recovery_epoch,
            }
        )
        return ResearchProtectionSnapshot(
            deterministic_id("p45_research_protection_snapshot", fingerprint),
            RESEARCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION,
            research_protection_snapshot_schema_identity(),
            p44.portfolio_snapshot_id,
            p44.snapshot_fingerprint,
            portfolio_research_snapshot_schema_identity(),
            evidence.as_of_timestamp_utc if evidence else p44.as_of_timestamp_utc,
            p44.knowledge_cutoff_utc,
            permission,
            upstream,
            assessments["observation"],
            assessments["reliability"],
            assessments["strategy_health"],
            assessments["temporal"],
            assessments["cooldown"],
            assessments["degradation"],
            assessments["abnormal"],
            assessments["lifecycle"],
            assessments["dependency"],
            assessments["recovery"],
            assessments["systemic"],
            restrictions,
            warnings,
            reason_codes,
            self.configuration_identity,
            self._policy_identity(),
            p44.recovery_epoch,
            fingerprint,
        )

    def _assessment_payloads(self, evidence: ResearchProtectionEvidence | None) -> dict[str, Mapping[str, Any]]:
        if evidence is None:
            unavailable = {"available": False, "state": "UNAVAILABLE", "permission": ResearchProtectionPermission.BLOCKED.value}
            return {key: unavailable for key in ("observation", "reliability", "strategy_health", "temporal", "cooldown", "degradation", "abnormal", "lifecycle", "dependency", "recovery", "systemic")}
        return {
            "observation": {"available": evidence.observation_trust_status is not None, "state": evidence.observation_trust_status, "evidence_id": evidence.observation_evidence_id},
            "reliability": {"available": evidence.reliability_stage is not None, "state": evidence.reliability_stage, "evidence_id": evidence.reliability_evidence_id},
            "strategy_health": {"available": evidence.strategy_health is not None, "state": evidence.strategy_health, "evidence_id": evidence.strategy_health_evidence_id},
            "temporal": {"available": evidence.temporal_stage is not None, "state": evidence.temporal_stage, "evidence_id": evidence.temporal_evidence_id},
            "cooldown": {"count": len(evidence.cooldowns), "states": tuple(item.status for item in evidence.cooldowns)},
            "degradation": {"count": len(evidence.degradation_states), "states": tuple(dict(item) for item in evidence.degradation_states)},
            "abnormal": {"state": evidence.abnormal_condition_state},
            "lifecycle": {"state": evidence.lifecycle_state, "health": evidence.lifecycle_health, "evidence_id": evidence.lifecycle_evidence_id},
            "dependency": {"count": len(evidence.dependency_states), "states": tuple({"component_id": item.component_id, "required": item.required, "status": item.status, "health": item.health, "stale": item.stale} for item in evidence.dependency_states)},
            "recovery": {"restricted": evidence.recovery_restricted, "evidence_id": evidence.recovery_evidence_id},
            "systemic": {"state": evidence.system_safety_state, "evidence_id": evidence.system_safety_evidence_id},
        }

    def _permission_from_p44_state(self, value: str, snapshot: PortfolioResearchSnapshot) -> str:
        if value == "ACCEPTABLE" and not snapshot.aggregate_restrictions:
            return ResearchProtectionPermission.ALLOWED.value
        if value in {"INVALID", "UNAVAILABLE"}:
            return ResearchProtectionPermission.BLOCKED.value
        if any(risk.risk_state in {"BLOCKED", "INVALID", "UNAVAILABLE"} for risk in snapshot.candidate_risk_assessments):
            return ResearchProtectionPermission.BLOCKED.value
        return ResearchProtectionPermission.RESTRICTED.value

    def _evidence_restriction(self, evidence: ResearchProtectionEvidence, component: str, source_id: str, category: str, severity: str, permission: str, reason: str, message: str) -> ProtectionRestriction:
        return self._restriction(component, source_id, category, severity, permission, reason, message, evidence.as_of_timestamp_utc, evidence.as_of_timestamp_utc, evidence.knowledge_cutoff_utc, evidence.recovery_epoch)

    def _restriction(self, component: str, source_id: str, category: str, severity: str, permission: str, reason: str, message: str, first_observed: datetime, as_of: datetime, cutoff: datetime, recovery_epoch: int) -> ProtectionRestriction:
        rid = deterministic_id("p45_protection_restriction", component, source_id, category, severity, permission, reason, first_observed.isoformat(), as_of.isoformat(), self.configuration_identity)
        return ProtectionRestriction(rid, component, source_id, category, severity, permission, reason, message, first_observed, as_of, cutoff, self.configuration_identity, recovery_epoch)

    def _dedupe_restrictions(self, restrictions: list[ProtectionRestriction]) -> tuple[ProtectionRestriction, ...]:
        unique = {item.restriction_id: item for item in restrictions}
        return tuple(sorted(unique.values(), key=lambda item: (-PERMISSION_RANK[item.effective_permission], -SEVERITY_RANK.get(item.severity, 0), item.category, item.source_component, item.reason_code, item.restriction_id)))

    def _policy_identity(self) -> str:
        return deterministic_id("p45_research_protection_policy", self.configuration.policy_version, self.configuration_identity, self.configuration.stale_after_seconds, self.configuration.require_positive_safety_evidence, self.configuration.require_dependency_evidence)

    def _bound(self) -> None:
        for store, limit in ((self.snapshots, self.configuration.maximum_snapshots), (self.restrictions, self.configuration.maximum_restrictions), (self.cooldowns, self.configuration.maximum_cooldowns)):
            while len(store) > limit:
                store.popitem(last=False)

    def _record(self, event: str, payload: Mapping[str, Any]) -> None:
        if self.audit is not None:
            self.audit.record(event, payload)


class ResearchProtectionRuntimeComponent:
    def __init__(self, component_id: str, runtime_holder: dict[str, ResearchProtectionRuntime] | None = None) -> None:
        self.component_id = component_id
        self.runtime: ResearchProtectionRuntime | None = None
        self._runtime_holder = runtime_holder

    def initialize_component(self, context: Any) -> None:
        if self.runtime is None:
            if self._runtime_holder is not None and "runtime" in self._runtime_holder:
                self.runtime = self._runtime_holder["runtime"]
            else:
                self.runtime = ResearchProtectionRuntime(clock=context.services["clock"], audit=context.services["audit"])
                if self._runtime_holder is not None:
                    self._runtime_holder["runtime"] = self.runtime
        audit = context.services.get("audit") if hasattr(context, "services") else None
        if audit is not None:
            audit.record("research_protection_runtime_initialized", {"component_id": self.component_id, "schema_identity": research_protection_snapshot_schema_identity()})

    def component_ready(self, context: Any) -> bool:
        return self.runtime is not None and self.runtime.component_ready(context)

    def component_health(self, context: Any) -> HealthStatus:
        return self.runtime.component_health(context) if self.runtime is not None else HealthStatus.UNKNOWN

    def diagnostics(self) -> dict[str, Any]:
        payload = self.runtime.diagnostics() if self.runtime is not None else {}
        payload["component_id"] = self.component_id
        return payload


def research_protection_component_registrations() -> tuple[tuple[ComponentMetadata, ResearchProtectionRuntimeComponent], ...]:
    holder: dict[str, ResearchProtectionRuntime] = {}
    capabilities = ComponentCapabilities(lifecycle=True, persistence=True, recovery=True, health=True, diagnostics=True, activation=True)
    definitions = (
        ("protection_input_monitor", ("portfolio_research_snapshot", "data_trust")),
        ("strategy_health_protection", ("post_scoring_research_assessment", "protection_input_monitor")),
        ("temporal_safety_protection", ("temporal_quality", "protection_input_monitor")),
        ("lifecycle_protection", ("temporal_safety_protection",)),
        ("dependency_protection", ("protection_input_monitor",)),
        ("system_safety_protection", ("data_trust", "dependency_protection")),
        ("research_protection", ("strategy_health_protection", "temporal_safety_protection", "lifecycle_protection", "dependency_protection", "system_safety_protection")),
        ("research_protection_snapshot", ("research_protection",)),
    )
    return tuple((ComponentMetadata(component_id, ComponentType.RESEARCH, RESEARCH_PROTECTION_RUNTIME_VERSION, True, dependencies, capabilities), ResearchProtectionRuntimeComponent(component_id, holder)) for component_id, dependencies in definitions)


def research_protection_components_from_inventory(inventory: tuple[Mapping[str, Any], ...]) -> dict[str, Mapping[str, Any]]:
    ids = {"protection_input_monitor", "strategy_health_protection", "temporal_safety_protection", "lifecycle_protection", "dependency_protection", "system_safety_protection", "research_protection", "research_protection_snapshot"}
    return {item["component_id"]: item for item in inventory if item.get("component_id") in ids}


def protection_evidence_schema_identity() -> str:
    return _sha256_json({"schema": "p45_research_protection_evidence", "version": PROTECTION_EVIDENCE_SCHEMA_VERSION, "fields": tuple(ResearchProtectionEvidence.__dataclass_fields__)})


def research_protection_snapshot_schema_identity() -> str:
    return _sha256_json({"schema": "p45_research_protection_snapshot", "version": RESEARCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION, "fields": tuple(ResearchProtectionSnapshot.__dataclass_fields__), "p44": portfolio_research_snapshot_schema_identity(), "evidence": protection_evidence_schema_identity()})


def _snapshot_summary(item: ResearchProtectionSnapshot | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "protection_snapshot_id": item.protection_snapshot_id,
        "snapshot_fingerprint": item.snapshot_fingerprint,
        "p44_snapshot_id": item.p44_snapshot_id,
        "effective_permission": item.effective_permission,
        "restriction_ids": [restriction.restriction_id for restriction in item.aggregate_restrictions],
        "reason_codes": list(item.reason_codes),
        "financial_execution": "NONE",
    }


def _upper(value: Any) -> str:
    return "" if value is None else str(value).strip().upper()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(nested) for key, nested in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {field: _jsonable(getattr(value, field)) for field in value.__dataclass_fields__}
    return value
