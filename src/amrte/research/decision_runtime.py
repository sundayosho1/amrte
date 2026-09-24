from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from amrte.core.composition import ComponentCapabilities, ComponentMetadata, ComponentType
from amrte.core.identity import deterministic_id
from amrte.core.observability import DecisionTraceBuilder
from amrte.core.observability_types import DecisionOutcome, DecisionStatus, DecisionTrace
from amrte.core.recovery import IdempotencyLedger
from amrte.core.types import HealthStatus
from amrte.market.intelligence_runtime import (
    UNIFIED_INTELLIGENCE_SCHEMA_VERSION,
    market_intelligence_schema_identity,
)
from amrte.market.observation import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    MARKET_OBSERVATION_SCHEMA_VERSION,
    schema_identity as market_data_schema_identity,
)
from amrte.portfolio.research_portfolio_runtime import (
    CANDIDATE_RESEARCH_RISK_SCHEMA_VERSION,
    CORRELATION_RESEARCH_SCHEMA_VERSION,
    PORTFOLIO_RESEARCH_SNAPSHOT_SCHEMA_VERSION,
    candidate_research_risk_schema_identity,
    correlation_research_schema_identity,
    portfolio_research_snapshot_schema_identity,
)
from amrte.research.data_quality_runtime import (
    QUALITY_TRUST_SCHEMA_VERSION,
    quality_trust_schema_identity,
)
from amrte.research.protection_runtime import (
    RESEARCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION,
    ResearchProtectionPermission,
    ResearchProtectionSnapshot,
    research_protection_snapshot_schema_identity,
)
from amrte.strategies.evaluation_runtime import (
    RESEARCH_CANDIDATE_SCHEMA_VERSION,
    STRATEGY_EVALUATION_SET_SCHEMA_VERSION,
    research_candidate_schema_identity,
    strategy_evaluation_set_schema_identity,
)
from amrte.strategies.research_scoring_runtime import (
    RESEARCH_ARBITRATION_ASSESSMENT_SCHEMA_VERSION,
    SCORED_RESEARCH_CANDIDATE_SCHEMA_VERSION,
    research_arbitration_assessment_schema_identity,
    scored_research_candidate_schema_identity,
)


MASTER_RESEARCH_DECISION_RUNTIME_VERSION = "1.0"
RESEARCH_PROCESSING_CONTEXT_SCHEMA_VERSION = "1.0"
FINAL_RESEARCH_DECISION_SCHEMA_VERSION = "1.0"
RESEARCH_DECISION_TRACE_SCHEMA_VERSION = "1.0"


class ResearchDecisionAcceptance(Enum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"


class FinalResearchClassification(Enum):
    NO_ACTION = "NO_ACTION"
    REJECTED = "REJECTED"
    RESTRICTED = "RESTRICTED"
    ELIGIBLE_RESEARCH = "ELIGIBLE_RESEARCH"
    FAILED = "FAILED"


class ResearchStageStatus(Enum):
    PRESENT = "PRESENT"
    MISSING = "MISSING"
    INVALID = "INVALID"


REQUIRED_STAGE_ORDER = (
    "P39_MARKET_OBSERVATION",
    "P39_DATASET_MANIFEST",
    "P40_QUALITY_TRUST",
    "P41_MARKET_INTELLIGENCE",
    "P42_RESEARCH_CANDIDATE",
    "P42_STRATEGY_EVALUATION_SET",
    "P43_SCORED_RESEARCH_CANDIDATE",
    "P43_RESEARCH_ARBITRATION",
    "P44_CANDIDATE_RISK",
    "P44_CORRELATION",
    "P44_PORTFOLIO_SNAPSHOT",
    "P45_RESEARCH_PROTECTION",
)


@dataclass(frozen=True)
class ResearchStageEvidence:
    stage: str
    evidence_id: str
    schema_version: str
    schema_identity: str
    dataset_id: str
    dataset_fingerprint: str
    as_of_timestamp_utc: datetime
    knowledge_cutoff_utc: datetime
    configuration_identity: str
    recovery_epoch: int
    evidence_fingerprint: str
    status: str = ResearchStageStatus.PRESENT.value
    source_evidence_ids: tuple[str, ...] = ()
    stage_decision: str | None = None


@dataclass(frozen=True)
class ResearchProcessingContext:
    context_id: str
    schema_version: str
    schema_identity: str
    created_at_utc: datetime
    dataset_id: str
    dataset_fingerprint: str
    knowledge_cutoff_utc: datetime
    configuration_identity: str
    recovery_epoch: int
    p45_protection_snapshot_id: str
    stage_records: tuple[ResearchStageEvidence, ...]
    context_fingerprint: str
    idempotency_key: str

    @classmethod
    def create(
        cls,
        *,
        created_at_utc: datetime,
        dataset_id: str,
        dataset_fingerprint: str,
        knowledge_cutoff_utc: datetime,
        configuration_identity: str,
        recovery_epoch: int,
        p45_protection_snapshot_id: str,
        stage_records: tuple[ResearchStageEvidence, ...],
    ) -> "ResearchProcessingContext":
        fingerprint = _sha256_json(
            {
                "dataset_id": dataset_id,
                "dataset_fingerprint": dataset_fingerprint,
                "knowledge_cutoff": knowledge_cutoff_utc,
                "configuration_identity": configuration_identity,
                "recovery_epoch": recovery_epoch,
                "p45_protection_snapshot_id": p45_protection_snapshot_id,
                "stages": tuple((item.stage, item.evidence_id, item.evidence_fingerprint) for item in stage_records),
            }
        )
        context_id = deterministic_id("p46_research_processing_context", fingerprint)
        return cls(
            context_id,
            RESEARCH_PROCESSING_CONTEXT_SCHEMA_VERSION,
            research_processing_context_schema_identity(),
            created_at_utc,
            dataset_id,
            dataset_fingerprint,
            knowledge_cutoff_utc,
            configuration_identity,
            recovery_epoch,
            p45_protection_snapshot_id,
            stage_records,
            fingerprint,
            deterministic_id("p46_research_decision_idempotency", context_id, p45_protection_snapshot_id),
        )


@dataclass(frozen=True)
class FinalResearchDecision:
    decision_id: str
    schema_version: str
    schema_identity: str
    context_id: str
    p45_protection_snapshot_id: str
    final_classification: str
    effective_permission: str
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    lineage_stage_ids: tuple[tuple[str, str], ...]
    created_at_utc: datetime
    knowledge_cutoff_utc: datetime
    configuration_identity: str
    recovery_epoch: int
    decision_fingerprint: str
    research_only: bool = True
    trade_authorization: str = "NONE"
    financial_authorization: str = "NONE"
    financial_execution: str = "NONE"


@dataclass(frozen=True)
class ResearchDecisionTrace:
    trace_id: str
    schema_version: str
    schema_identity: str
    decision_id: str
    context_id: str
    core_trace: DecisionTrace
    stage_outcomes: tuple[Mapping[str, Any], ...]
    trace_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage_outcomes", tuple(MappingProxyType(dict(item)) for item in self.stage_outcomes))


@dataclass(frozen=True)
class ResearchDecisionLedgerEntry:
    ledger_entry_id: str
    idempotency_key: str
    context_id: str
    decision_id: str
    trace_id: str
    classification: str
    committed_at_utc: datetime
    recovery_epoch: int


@dataclass(frozen=True)
class MasterResearchDecisionRuntimeResult:
    acceptance: ResearchDecisionAcceptance
    context: ResearchProcessingContext
    decision: FinalResearchDecision
    trace: ResearchDecisionTrace
    ledger_entry: ResearchDecisionLedgerEntry
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MasterResearchDecisionRecoveryState:
    schema_version: str
    runtime_version: str
    context_schema_identity: str
    decision_schema_identity: str
    trace_schema_identity: str
    required_stage_order: tuple[str, ...]
    required_stage_schema_identities: tuple[tuple[str, str], ...]
    configuration_identity: str
    recovery_epoch: int
    committed_idempotency_keys: tuple[str, ...]
    contexts: tuple[ResearchProcessingContext, ...]
    decisions: tuple[FinalResearchDecision, ...]
    traces: tuple[ResearchDecisionTrace, ...]
    ledger_entries: tuple[ResearchDecisionLedgerEntry, ...]


class MasterResearchDecisionOrchestrator:
    """Prompt 46 final research decision authority over P39-P45 evidence."""

    def __init__(
        self,
        *,
        clock: Any,
        audit: Any,
        maximum_decisions: int = 1024,
    ) -> None:
        if maximum_decisions < 1:
            raise ValueError("P46_BOUNDS_INVALID")
        self.clock = clock
        self.audit = audit
        self.maximum_decisions = maximum_decisions
        self.contexts: OrderedDict[str, ResearchProcessingContext] = OrderedDict()
        self.decisions: OrderedDict[str, FinalResearchDecision] = OrderedDict()
        self.traces: OrderedDict[str, ResearchDecisionTrace] = OrderedDict()
        self.ledger_entries: OrderedDict[str, ResearchDecisionLedgerEntry] = OrderedDict()
        self.ledger = IdempotencyLedger()
        self.recovery_restricted = False
        self.metrics = {
            "contexts_received": 0,
            "decisions_published": 0,
            "duplicate_contexts": 0,
            "failed_closed": 0,
            "eligible_research": 0,
            "restricted": 0,
            "rejected": 0,
            "no_action": 0,
            "recovery_divergences": 0,
        }

    @property
    def configuration_identity(self) -> str:
        return "P46_MASTER_RESEARCH_DECISION_DEFAULT"

    def decide(
        self,
        context: ResearchProcessingContext,
        protection_snapshot: ResearchProtectionSnapshot,
    ) -> MasterResearchDecisionRuntimeResult:
        self.metrics["contexts_received"] += 1
        existing = self._existing_result(context)
        if existing is not None:
            self.metrics["duplicate_contexts"] += 1
            decision, trace, entry = existing
            return MasterResearchDecisionRuntimeResult(
                ResearchDecisionAcceptance.DUPLICATE,
                context,
                decision,
                trace,
                entry,
                ("P46_DUPLICATE_PROCESSING_CONTEXT",),
                decision.warnings,
            )

        validation_reasons = self._validate_context(context, protection_snapshot)
        classification = self._classify(validation_reasons, context, protection_snapshot)
        if classification is FinalResearchClassification.FAILED:
            self.metrics["failed_closed"] += 1
        elif classification is FinalResearchClassification.ELIGIBLE_RESEARCH:
            self.metrics["eligible_research"] += 1
        elif classification is FinalResearchClassification.RESTRICTED:
            self.metrics["restricted"] += 1
        elif classification is FinalResearchClassification.REJECTED:
            self.metrics["rejected"] += 1
        elif classification is FinalResearchClassification.NO_ACTION:
            self.metrics["no_action"] += 1

        decision = self._decision(context, protection_snapshot, classification, validation_reasons)
        trace = self._trace(context, decision, validation_reasons)
        entry = self._ledger_entry(context, decision, trace)

        self.contexts[context.context_id] = context
        self.decisions[decision.decision_id] = decision
        self.traces[trace.trace_id] = trace
        self.ledger_entries[entry.ledger_entry_id] = entry
        self.ledger.commit(context.idempotency_key)
        self.metrics["decisions_published"] += 1
        self._bound()
        self._record(
            "master_research_decision_published",
            {
                "decision_id": decision.decision_id,
                "classification": decision.final_classification,
                "p45_snapshot_id": decision.p45_protection_snapshot_id,
            },
        )
        return MasterResearchDecisionRuntimeResult(
            ResearchDecisionAcceptance.ACCEPTED,
            context,
            decision,
            trace,
            entry,
            decision.reason_codes,
            decision.warnings,
        )

    def recovery_state(self, recovery_epoch: int) -> MasterResearchDecisionRecoveryState:
        return MasterResearchDecisionRecoveryState(
            FINAL_RESEARCH_DECISION_SCHEMA_VERSION,
            MASTER_RESEARCH_DECISION_RUNTIME_VERSION,
            research_processing_context_schema_identity(),
            final_research_decision_schema_identity(),
            research_decision_trace_schema_identity(),
            REQUIRED_STAGE_ORDER,
            tuple(sorted(required_stage_schema_identities().items())),
            self.configuration_identity,
            recovery_epoch,
            self.ledger.snapshot(),
            tuple(self.contexts.values()),
            tuple(self.decisions.values()),
            tuple(self.traces.values()),
            tuple(self.ledger_entries.values()),
        )

    def restore(self, state: MasterResearchDecisionRecoveryState, expected_recovery_epoch: int) -> bool:
        if (
            state.schema_version != FINAL_RESEARCH_DECISION_SCHEMA_VERSION
            or state.runtime_version != MASTER_RESEARCH_DECISION_RUNTIME_VERSION
            or state.context_schema_identity != research_processing_context_schema_identity()
            or state.decision_schema_identity != final_research_decision_schema_identity()
            or state.trace_schema_identity != research_decision_trace_schema_identity()
            or state.required_stage_order != REQUIRED_STAGE_ORDER
            or state.required_stage_schema_identities != tuple(sorted(required_stage_schema_identities().items()))
            or state.configuration_identity != self.configuration_identity
            or state.recovery_epoch != expected_recovery_epoch
        ):
            self.recovery_restricted = True
            self.metrics["recovery_divergences"] += 1
            return False
        self.ledger = IdempotencyLedger(state.committed_idempotency_keys)
        self.contexts = OrderedDict((item.context_id, item) for item in state.contexts)
        self.decisions = OrderedDict((item.decision_id, item) for item in state.decisions)
        self.traces = OrderedDict((item.trace_id, item) for item in state.traces)
        self.ledger_entries = OrderedDict((item.ledger_entry_id, item) for item in state.ledger_entries)
        self.recovery_restricted = False
        self._bound()
        self._record("master_research_decision_runtime_recovered", {"decisions": len(self.decisions)})
        return True

    def reconcile(self, recovery_epoch: int) -> tuple[str, ...]:
        issues: list[str] = []
        if self.recovery_restricted:
            issues.append("P46_RECOVERY_RESTRICTED")
        if any(item.recovery_epoch > recovery_epoch for item in self.decisions.values()):
            issues.append("P46_RECOVERY_EPOCH_REGRESSION")
        if any(item.final_classification == FinalResearchClassification.ELIGIBLE_RESEARCH.value and item.effective_permission != ResearchProtectionPermission.ALLOWED.value for item in self.decisions.values()):
            issues.append("P46_PERMISSION_DIVERGENCE")
        return tuple(dict.fromkeys(issues))

    def diagnostics(self) -> dict[str, Any]:
        latest = next(reversed(self.decisions.values()), None) if self.decisions else None
        return {
            "runtime_version": MASTER_RESEARCH_DECISION_RUNTIME_VERSION,
            "processing_context_schema_version": RESEARCH_PROCESSING_CONTEXT_SCHEMA_VERSION,
            "processing_context_schema_identity": research_processing_context_schema_identity(),
            "final_decision_schema_version": FINAL_RESEARCH_DECISION_SCHEMA_VERSION,
            "final_decision_schema_identity": final_research_decision_schema_identity(),
            "trace_schema_version": RESEARCH_DECISION_TRACE_SCHEMA_VERSION,
            "trace_schema_identity": research_decision_trace_schema_identity(),
            "required_stage_order": list(REQUIRED_STAGE_ORDER),
            "required_stage_schema_identities": required_stage_schema_identities(),
            "policy": {
                "policy_id": "P46_MASTER_RESEARCH_DECISION_POLICY",
                "version": "1.0",
                "configuration_identity": self.configuration_identity,
                "fail_closed": True,
                "p45_restrictions_preserved": True,
            },
            "latest_decision": _decision_summary(latest),
            "metrics": dict(self.metrics),
            "recovery_restricted": self.recovery_restricted,
            "research_only": True,
            "trade_authorization": "NONE",
            "financial_authorization": "NONE",
            "financial_execution": "NONE",
        }

    def component_ready(self, context: Any) -> bool:
        return not self.recovery_restricted

    def component_health(self, context: Any) -> HealthStatus:
        return HealthStatus.DEGRADED if self.recovery_restricted else HealthStatus.HEALTHY

    def _existing_result(
        self,
        context: ResearchProcessingContext,
    ) -> tuple[FinalResearchDecision, ResearchDecisionTrace, ResearchDecisionLedgerEntry] | None:
        if not self.ledger.is_committed(context.idempotency_key):
            return None
        entry = next((item for item in self.ledger_entries.values() if item.idempotency_key == context.idempotency_key), None)
        if entry is None:
            return None
        decision = self.decisions[entry.decision_id]
        trace = self.traces[entry.trace_id]
        return decision, trace, entry

    def _validate_context(
        self,
        context: ResearchProcessingContext,
        protection_snapshot: ResearchProtectionSnapshot,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if context.schema_version != RESEARCH_PROCESSING_CONTEXT_SCHEMA_VERSION or context.schema_identity != research_processing_context_schema_identity():
            reasons.append("P46_PROCESSING_CONTEXT_SCHEMA_MISMATCH")
        expected_context_id = deterministic_id("p46_research_processing_context", context.context_fingerprint)
        if context.context_id != expected_context_id:
            reasons.append("P46_PROCESSING_CONTEXT_IDENTITY_MISMATCH")
        if context.p45_protection_snapshot_id != protection_snapshot.protection_snapshot_id:
            reasons.append("P46_P45_LINEAGE_MISMATCH")
        if protection_snapshot.schema_version != RESEARCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION or protection_snapshot.schema_identity != research_protection_snapshot_schema_identity():
            reasons.append("P46_P45_SCHEMA_MISMATCH")
        expected_p45_id = deterministic_id("p45_research_protection_snapshot", protection_snapshot.snapshot_fingerprint)
        if protection_snapshot.protection_snapshot_id != expected_p45_id:
            reasons.append("P46_P45_IDENTITY_MISMATCH")
        if protection_snapshot.knowledge_cutoff_utc != context.knowledge_cutoff_utc:
            reasons.append("P46_KNOWLEDGE_CUTOFF_MISMATCH")
        if protection_snapshot.configuration_identity != context.configuration_identity:
            reasons.append("P46_CONFIGURATION_MISMATCH")
        if protection_snapshot.recovery_epoch != context.recovery_epoch:
            reasons.append("P46_RECOVERY_EPOCH_MISMATCH")
        if not getattr(context, "__dataclass_params__", None) or not context.__dataclass_params__.frozen:
            reasons.append("P46_PROCESSING_CONTEXT_NOT_IMMUTABLE")
        if not getattr(protection_snapshot, "__dataclass_params__", None) or not protection_snapshot.__dataclass_params__.frozen:
            reasons.append("P46_P45_SNAPSHOT_NOT_IMMUTABLE")
        reasons.extend(self._validate_stages(context, protection_snapshot))
        return tuple(dict.fromkeys(reasons))

    def _validate_stages(
        self,
        context: ResearchProcessingContext,
        protection_snapshot: ResearchProtectionSnapshot,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        stages = tuple(item.stage for item in context.stage_records)
        if set(stages) != set(REQUIRED_STAGE_ORDER) or len(stages) != len(REQUIRED_STAGE_ORDER):
            reasons.append("P46_STAGE_EVIDENCE_INCOMPLETE")
        if stages != REQUIRED_STAGE_ORDER:
            reasons.append("P46_STAGE_ORDER_VIOLATION")
        expected_identities = required_stage_schema_identities()
        expected_versions = required_stage_schema_versions()
        previous_as_of: datetime | None = None
        by_stage = {item.stage: item for item in context.stage_records}
        for stage in REQUIRED_STAGE_ORDER:
            record = by_stage.get(stage)
            if record is None:
                continue
            if record.status != ResearchStageStatus.PRESENT.value:
                reasons.append(f"P46_{stage}_EVIDENCE_UNAVAILABLE")
            if record.schema_version != expected_versions[stage] or record.schema_identity != expected_identities[stage]:
                reasons.append(f"P46_{stage}_SCHEMA_MISMATCH")
            if record.dataset_id != context.dataset_id or record.dataset_fingerprint != context.dataset_fingerprint:
                reasons.append("P46_STAGE_DATASET_MISMATCH")
            if record.knowledge_cutoff_utc != context.knowledge_cutoff_utc:
                reasons.append("P46_STAGE_KNOWLEDGE_CUTOFF_MISMATCH")
            if record.configuration_identity != context.configuration_identity:
                reasons.append("P46_STAGE_CONFIGURATION_MISMATCH")
            if record.recovery_epoch != context.recovery_epoch:
                reasons.append("P46_STAGE_RECOVERY_EPOCH_MISMATCH")
            if record.as_of_timestamp_utc > context.knowledge_cutoff_utc:
                reasons.append("P46_TEMPORAL_ORDER_VIOLATION")
            if previous_as_of is not None and record.as_of_timestamp_utc < previous_as_of:
                reasons.append("P46_STAGE_TEMPORAL_ORDER_VIOLATION")
            previous_as_of = record.as_of_timestamp_utc
        p44 = by_stage.get("P44_PORTFOLIO_SNAPSHOT")
        if p44 is not None and p44.evidence_id != protection_snapshot.p44_snapshot_id:
            reasons.append("P46_P44_LINEAGE_MISMATCH")
        p45 = by_stage.get("P45_RESEARCH_PROTECTION")
        if p45 is not None and p45.evidence_id != protection_snapshot.protection_snapshot_id:
            reasons.append("P46_P45_STAGE_LINEAGE_MISMATCH")
        return reasons

    def _classify(
        self,
        validation_reasons: tuple[str, ...],
        context: ResearchProcessingContext,
        protection_snapshot: ResearchProtectionSnapshot,
    ) -> FinalResearchClassification:
        if validation_reasons or self.recovery_restricted:
            return FinalResearchClassification.FAILED
        permission = protection_snapshot.effective_permission
        if permission == ResearchProtectionPermission.BLOCKED.value:
            return FinalResearchClassification.REJECTED
        if any(item.stage_decision in {"NO_ACTION", "NO_ELIGIBLE_CANDIDATE", "NO_SELECTION"} for item in context.stage_records):
            return FinalResearchClassification.NO_ACTION
        if permission == ResearchProtectionPermission.RESTRICTED.value:
            return FinalResearchClassification.RESTRICTED
        return FinalResearchClassification.ELIGIBLE_RESEARCH

    def _decision(
        self,
        context: ResearchProcessingContext,
        protection_snapshot: ResearchProtectionSnapshot,
        classification: FinalResearchClassification,
        validation_reasons: tuple[str, ...],
    ) -> FinalResearchDecision:
        reason_codes = tuple(
            dict.fromkeys(
                (
                    "P46_RESEARCH_ONLY_FINAL_DECISION",
                    "P46_FINAL_DECISION_IS_NOT_FINANCIAL_AUTHORIZATION",
                    *validation_reasons,
                    *protection_snapshot.reason_codes,
                    classification.value,
                )
            )
        )
        warnings = tuple(sorted(set(protection_snapshot.warnings)))
        lineage = tuple((item.stage, item.evidence_id) for item in context.stage_records)
        fingerprint = _sha256_json(
            {
                "context_id": context.context_id,
                "p45_snapshot_id": protection_snapshot.protection_snapshot_id,
                "classification": classification.value,
                "permission": protection_snapshot.effective_permission,
                "reasons": reason_codes,
                "configuration_identity": context.configuration_identity,
                "recovery_epoch": context.recovery_epoch,
            }
        )
        return FinalResearchDecision(
            deterministic_id("p46_final_research_decision", fingerprint),
            FINAL_RESEARCH_DECISION_SCHEMA_VERSION,
            final_research_decision_schema_identity(),
            context.context_id,
            protection_snapshot.protection_snapshot_id,
            classification.value,
            protection_snapshot.effective_permission,
            reason_codes,
            warnings,
            lineage,
            self.clock.now(),
            context.knowledge_cutoff_utc,
            context.configuration_identity,
            context.recovery_epoch,
            fingerprint,
        )

    def _trace(
        self,
        context: ResearchProcessingContext,
        decision: FinalResearchDecision,
        validation_reasons: tuple[str, ...],
    ) -> ResearchDecisionTrace:
        builder = DecisionTraceBuilder(
            self.clock,
            deterministic_id("p46_decision_trace_core", decision.decision_id),
            deterministic_id("p46_research_decision_correlation", context.context_id),
        )
        stage_outcomes = []
        for stage in REQUIRED_STAGE_ORDER:
            record = next((item for item in context.stage_records if item.stage == stage), None)
            failed = record is None or record.status != ResearchStageStatus.PRESENT.value or any(reason.startswith(f"P46_{stage}") for reason in validation_reasons)
            status = DecisionStatus.FAILED if failed else DecisionStatus.PASSED
            reason = f"{stage}_VALIDATED" if not failed else f"{stage}_FAILED_CLOSED"
            builder.evaluate(stage.lower(), status, reason, "stage evidence validated" if not failed else "stage evidence unavailable or invalid", (record.evidence_id,) if record else ())
            stage_outcomes.append({"stage": stage, "status": status.name, "reason_code": reason, "evidence_id": record.evidence_id if record else None})
            if failed:
                break
        if validation_reasons and all(item["status"] != DecisionStatus.FAILED.name for item in stage_outcomes):
            builder.evaluate("final_validation", DecisionStatus.FAILED, "P46_FINAL_VALIDATION_FAILED_CLOSED", "processing context failed final validation", validation_reasons)
            stage_outcomes.append({"stage": "P46_FINAL_VALIDATION", "status": DecisionStatus.FAILED.name, "reason_code": "P46_FINAL_VALIDATION_FAILED_CLOSED", "evidence_id": None})
        outcome = _decision_outcome(decision.final_classification)
        core = builder.complete(outcome, decision.final_classification)
        fingerprint = _sha256_json(
            {
                "decision_id": decision.decision_id,
                "context_id": context.context_id,
                "evaluations": tuple((item.gate, item.status.name, item.reason_code) for item in core.evaluations),
                "outcome": core.outcome.name,
            }
        )
        trace_id = deterministic_id("p46_research_decision_trace", fingerprint)
        return ResearchDecisionTrace(
            trace_id,
            RESEARCH_DECISION_TRACE_SCHEMA_VERSION,
            research_decision_trace_schema_identity(),
            decision.decision_id,
            context.context_id,
            core,
            tuple(stage_outcomes),
            fingerprint,
        )

    def _ledger_entry(
        self,
        context: ResearchProcessingContext,
        decision: FinalResearchDecision,
        trace: ResearchDecisionTrace,
    ) -> ResearchDecisionLedgerEntry:
        return ResearchDecisionLedgerEntry(
            deterministic_id("p46_research_decision_ledger", context.idempotency_key, decision.decision_id, trace.trace_id),
            context.idempotency_key,
            context.context_id,
            decision.decision_id,
            trace.trace_id,
            decision.final_classification,
            self.clock.now(),
            context.recovery_epoch,
        )

    def _bound(self) -> None:
        for store in (self.contexts, self.decisions, self.traces, self.ledger_entries):
            while len(store) > self.maximum_decisions:
                store.popitem(last=False)

    def _record(self, event: str, payload: Mapping[str, Any]) -> None:
        if self.audit is not None:
            self.audit.record(event, payload)


class MasterResearchDecisionRuntimeComponent:
    def __init__(self, component_id: str, runtime_holder: dict[str, MasterResearchDecisionOrchestrator] | None = None) -> None:
        self.component_id = component_id
        self.runtime: MasterResearchDecisionOrchestrator | None = None
        self._runtime_holder = runtime_holder

    def initialize_component(self, context: Any) -> None:
        if self.runtime is None:
            if self._runtime_holder is not None and "runtime" in self._runtime_holder:
                self.runtime = self._runtime_holder["runtime"]
            else:
                self.runtime = MasterResearchDecisionOrchestrator(clock=context.services["clock"], audit=context.services["audit"])
                if self._runtime_holder is not None:
                    self._runtime_holder["runtime"] = self.runtime
        audit = context.services.get("audit") if hasattr(context, "services") else None
        if audit is not None:
            audit.record("master_research_decision_runtime_initialized", {"component_id": self.component_id, "decision_schema_identity": final_research_decision_schema_identity()})

    def component_ready(self, context: Any) -> bool:
        return self.runtime is not None and self.runtime.component_ready(context)

    def component_health(self, context: Any) -> HealthStatus:
        return self.runtime.component_health(context) if self.runtime is not None else HealthStatus.UNKNOWN

    def diagnostics(self) -> dict[str, Any]:
        payload = self.runtime.diagnostics() if self.runtime is not None else {}
        payload["component_id"] = self.component_id
        return payload


def master_research_decision_component_registrations() -> tuple[tuple[ComponentMetadata, MasterResearchDecisionRuntimeComponent], ...]:
    holder: dict[str, MasterResearchDecisionOrchestrator] = {}
    capabilities = ComponentCapabilities(lifecycle=True, persistence=True, recovery=True, health=True, diagnostics=True, activation=True)
    definitions = (
        ("research_processing_context", ("research_protection_snapshot",)),
        ("stage_evidence_verification", ("research_processing_context",)),
        ("master_research_decision", ("stage_evidence_verification",)),
        ("research_decision_trace", ("master_research_decision",)),
        ("research_decision_ledger", ("research_decision_trace",)),
    )
    return tuple((ComponentMetadata(component_id, ComponentType.RESEARCH, MASTER_RESEARCH_DECISION_RUNTIME_VERSION, True, dependencies, capabilities), MasterResearchDecisionRuntimeComponent(component_id, holder)) for component_id, dependencies in definitions)


def master_research_decision_components_from_inventory(inventory: tuple[Mapping[str, Any], ...]) -> dict[str, Mapping[str, Any]]:
    ids = {"research_processing_context", "stage_evidence_verification", "master_research_decision", "research_decision_trace", "research_decision_ledger"}
    return {item["component_id"]: item for item in inventory if item.get("component_id") in ids}


def stage_records_for_protection_snapshot(
    protection_snapshot: ResearchProtectionSnapshot,
    *,
    dataset_id: str,
    dataset_fingerprint: str,
) -> tuple[ResearchStageEvidence, ...]:
    identities = required_stage_schema_identities()
    versions = required_stage_schema_versions()
    cutoff = protection_snapshot.knowledge_cutoff_utc
    configuration = protection_snapshot.configuration_identity
    epoch = protection_snapshot.recovery_epoch
    generic_ids = {
        "P39_MARKET_OBSERVATION": f"{dataset_id}:observation",
        "P39_DATASET_MANIFEST": dataset_id,
        "P40_QUALITY_TRUST": f"{dataset_id}:quality-trust",
        "P41_MARKET_INTELLIGENCE": f"{dataset_id}:market-intelligence",
        "P42_RESEARCH_CANDIDATE": f"{dataset_id}:research-candidate",
        "P42_STRATEGY_EVALUATION_SET": f"{dataset_id}:strategy-evaluation-set",
        "P43_SCORED_RESEARCH_CANDIDATE": f"{dataset_id}:scored-research-candidate",
        "P43_RESEARCH_ARBITRATION": f"{dataset_id}:research-arbitration",
        "P44_CANDIDATE_RISK": f"{protection_snapshot.p44_snapshot_id}:candidate-risk",
        "P44_CORRELATION": f"{protection_snapshot.p44_snapshot_id}:correlation",
        "P44_PORTFOLIO_SNAPSHOT": protection_snapshot.p44_snapshot_id,
        "P45_RESEARCH_PROTECTION": protection_snapshot.protection_snapshot_id,
    }
    records: list[ResearchStageEvidence] = []
    previous: str | None = None
    for stage in REQUIRED_STAGE_ORDER:
        evidence_id = generic_ids[stage]
        fingerprint = _sha256_json({"stage": stage, "evidence_id": evidence_id, "schema_identity": identities[stage]})
        records.append(
            ResearchStageEvidence(
                stage,
                evidence_id,
                versions[stage],
                identities[stage],
                dataset_id,
                dataset_fingerprint,
                protection_snapshot.as_of_timestamp_utc,
                cutoff,
                configuration,
                epoch,
                fingerprint,
                source_evidence_ids=() if previous is None else (previous,),
                stage_decision=_stage_decision(stage, protection_snapshot),
            )
        )
        previous = evidence_id
    return tuple(records)


def research_processing_context_schema_identity() -> str:
    return _sha256_json({"schema": "p46_research_processing_context", "version": RESEARCH_PROCESSING_CONTEXT_SCHEMA_VERSION, "fields": tuple(ResearchProcessingContext.__dataclass_fields__), "required_stages": REQUIRED_STAGE_ORDER, "stage_schemas": required_stage_schema_identities()})


def final_research_decision_schema_identity() -> str:
    return _sha256_json({"schema": "p46_final_research_decision", "version": FINAL_RESEARCH_DECISION_SCHEMA_VERSION, "fields": tuple(FinalResearchDecision.__dataclass_fields__), "context_schema_identity": research_processing_context_schema_identity(), "p45": research_protection_snapshot_schema_identity()})


def research_decision_trace_schema_identity() -> str:
    return _sha256_json({"schema": "p46_research_decision_trace", "version": RESEARCH_DECISION_TRACE_SCHEMA_VERSION, "fields": tuple(ResearchDecisionTrace.__dataclass_fields__), "decision_schema_identity": final_research_decision_schema_identity()})


def required_stage_schema_identities() -> dict[str, str]:
    return {
        "P39_MARKET_OBSERVATION": market_data_schema_identity("observation"),
        "P39_DATASET_MANIFEST": market_data_schema_identity("dataset_manifest"),
        "P40_QUALITY_TRUST": quality_trust_schema_identity(),
        "P41_MARKET_INTELLIGENCE": market_intelligence_schema_identity(),
        "P42_RESEARCH_CANDIDATE": research_candidate_schema_identity(),
        "P42_STRATEGY_EVALUATION_SET": strategy_evaluation_set_schema_identity(),
        "P43_SCORED_RESEARCH_CANDIDATE": scored_research_candidate_schema_identity(),
        "P43_RESEARCH_ARBITRATION": research_arbitration_assessment_schema_identity(),
        "P44_CANDIDATE_RISK": candidate_research_risk_schema_identity(),
        "P44_CORRELATION": correlation_research_schema_identity(),
        "P44_PORTFOLIO_SNAPSHOT": portfolio_research_snapshot_schema_identity(),
        "P45_RESEARCH_PROTECTION": research_protection_snapshot_schema_identity(),
    }


def required_stage_schema_versions() -> dict[str, str]:
    return {
        "P39_MARKET_OBSERVATION": MARKET_OBSERVATION_SCHEMA_VERSION,
        "P39_DATASET_MANIFEST": DATASET_MANIFEST_SCHEMA_VERSION,
        "P40_QUALITY_TRUST": QUALITY_TRUST_SCHEMA_VERSION,
        "P41_MARKET_INTELLIGENCE": UNIFIED_INTELLIGENCE_SCHEMA_VERSION,
        "P42_RESEARCH_CANDIDATE": RESEARCH_CANDIDATE_SCHEMA_VERSION,
        "P42_STRATEGY_EVALUATION_SET": STRATEGY_EVALUATION_SET_SCHEMA_VERSION,
        "P43_SCORED_RESEARCH_CANDIDATE": SCORED_RESEARCH_CANDIDATE_SCHEMA_VERSION,
        "P43_RESEARCH_ARBITRATION": RESEARCH_ARBITRATION_ASSESSMENT_SCHEMA_VERSION,
        "P44_CANDIDATE_RISK": CANDIDATE_RESEARCH_RISK_SCHEMA_VERSION,
        "P44_CORRELATION": CORRELATION_RESEARCH_SCHEMA_VERSION,
        "P44_PORTFOLIO_SNAPSHOT": PORTFOLIO_RESEARCH_SNAPSHOT_SCHEMA_VERSION,
        "P45_RESEARCH_PROTECTION": RESEARCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION,
    }


def _stage_decision(stage: str, protection_snapshot: ResearchProtectionSnapshot) -> str | None:
    if stage == "P44_PORTFOLIO_SNAPSHOT":
        return next((item for item in protection_snapshot.reason_codes if item in {"NO_ACTION", "UNAVAILABLE", "INVALID", "ACCEPTABLE", "RESTRICTED"}), None)
    if stage == "P45_RESEARCH_PROTECTION":
        return protection_snapshot.effective_permission
    return None


def _decision_outcome(classification: str) -> DecisionOutcome:
    if classification == FinalResearchClassification.ELIGIBLE_RESEARCH.value:
        return DecisionOutcome.ACCEPTED
    if classification == FinalResearchClassification.NO_ACTION.value:
        return DecisionOutcome.NO_ACTION
    return DecisionOutcome.BLOCKED


def _decision_summary(item: FinalResearchDecision | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "decision_id": item.decision_id,
        "decision_fingerprint": item.decision_fingerprint,
        "context_id": item.context_id,
        "p45_protection_snapshot_id": item.p45_protection_snapshot_id,
        "final_classification": item.final_classification,
        "effective_permission": item.effective_permission,
        "reason_codes": list(item.reason_codes),
        "research_only": item.research_only,
        "trade_authorization": item.trade_authorization,
        "financial_authorization": item.financial_authorization,
        "financial_execution": item.financial_execution,
    }


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
