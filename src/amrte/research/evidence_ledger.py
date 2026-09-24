from __future__ import annotations

import hashlib
import json
import os
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from amrte.core.composition import ComponentCapabilities, ComponentMetadata, ComponentType
from amrte.core.constants import AMRTE_VERSION
from amrte.core.identity import deterministic_id
from amrte.core.types import HealthStatus
from amrte.research.decision_runtime import (
    FINAL_RESEARCH_DECISION_SCHEMA_VERSION,
    MASTER_RESEARCH_DECISION_RUNTIME_VERSION,
    RESEARCH_DECISION_TRACE_SCHEMA_VERSION,
    RESEARCH_PROCESSING_CONTEXT_SCHEMA_VERSION,
    FinalResearchDecision,
    ResearchDecisionTrace,
    ResearchProcessingContext,
    final_research_decision_schema_identity,
    required_stage_schema_identities,
    research_decision_trace_schema_identity,
    research_processing_context_schema_identity,
)


RESEARCH_DECISION_EVIDENCE_LEDGER_VERSION = "1.0"
RESEARCH_DECISION_EVIDENCE_RECORD_SCHEMA_VERSION = "1.0"
RESEARCH_DECISION_EVIDENCE_BUNDLE_SCHEMA_VERSION = "1.0"
LEDGER_INTEGRITY_STATE_SCHEMA_VERSION = "1.0"
REPLAY_VERIFICATION_EVIDENCE_SCHEMA_VERSION = "1.0"


class EvidenceCompleteness(Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    INVALID = "INVALID"
    UNVERIFIABLE = "UNVERIFIABLE"


class EvidenceRecordType(Enum):
    ORIGINAL_DECISION = "ORIGINAL_DECISION"
    CORRECTION = "CORRECTION"
    SUPERSESSION = "SUPERSESSION"
    INVALIDATION = "INVALIDATION"
    REPLAY_VERIFICATION = "REPLAY_VERIFICATION"
    REPLAY_DIVERGENCE = "REPLAY_DIVERGENCE"
    PRE_LEDGER_HISTORICAL = "PRE_LEDGER_HISTORICAL"


class LedgerVerificationStatus(Enum):
    VERIFIED = "VERIFIED"
    INVALID = "INVALID"
    INCOMPLETE = "INCOMPLETE"
    UNAVAILABLE = "UNAVAILABLE"


class LedgerCommitAcceptance(Enum):
    COMMITTED = "COMMITTED"
    DUPLICATE = "DUPLICATE"


class ReplayVerificationStatus(Enum):
    MATCH = "MATCH"
    DIVERGED = "DIVERGED"
    CROSS_VERSION_REPLAY = "CROSS_VERSION_REPLAY"
    INVALID = "INVALID"


class ResearchEvidenceLedgerError(RuntimeError):
    code = "P47_RESEARCH_EVIDENCE_LEDGER_ERROR"


class LedgerValidationError(ResearchEvidenceLedgerError):
    code = "P47_LEDGER_VALIDATION_FAILED"


class LedgerConflictError(ResearchEvidenceLedgerError):
    code = "P47_LEDGER_CONFLICT"


class LedgerIntegrityError(ResearchEvidenceLedgerError):
    code = "P47_LEDGER_INTEGRITY_FAILED"


@dataclass(frozen=True)
class LedgerPolicy:
    policy_id: str
    version: str
    serialization: str
    hash_algorithm: str
    chain_model: str
    partition_model: str
    required_evidence: tuple[str, ...]
    retention_policy: str
    verification_policy: str
    policy_identity: str

    @classmethod
    def current(cls) -> "LedgerPolicy":
        required = (
            "P46_PROCESSING_CONTEXT",
            "P46_FINAL_DECISION",
            "P46_DECISION_TRACE",
            "P39_P45_STAGE_EVIDENCE",
            "RELEASE_PROVENANCE",
            "CONFIGURATION_IDENTITY",
            "KNOWLEDGE_CUTOFF",
        )
        payload = {
            "policy_id": "P47_RESEARCH_DECISION_EVIDENCE_LEDGER_POLICY",
            "version": "1.0",
            "serialization": "canonical-json:v1",
            "hash_algorithm": "sha256",
            "chain_model": "linear-genesis-previous-record-hash",
            "partition_model": "single-global-ledger-with-dataset-and-run-identities",
            "required_evidence": required,
            "retention_policy": "append-only-historical-records-independent-of-runtime-retention",
            "verification_policy": "verify-record-hash-sequence-previous-link-head-and-schema",
        }
        return cls(
            payload["policy_id"],
            payload["version"],
            payload["serialization"],
            payload["hash_algorithm"],
            payload["chain_model"],
            payload["partition_model"],
            required,
            payload["retention_policy"],
            payload["verification_policy"],
            _sha256_json(payload),
        )


@dataclass(frozen=True)
class ResearchEvidenceReleaseProvenance:
    application_version: str
    git_commit: str
    source_content_sha256: str
    dependency_declaration_sha256: str
    resolved_dependency_identity: str | None
    pipeline_identity: str
    package: str = "amrte-research-core"


@dataclass(frozen=True)
class ResearchDecisionEvidenceRecord:
    evidence_record_id: str
    schema_version: str
    schema_identity: str
    ledger_sequence: int
    record_type: str
    ingestion_key: str
    dataset_id: str
    dataset_fingerprint: str
    observation_id: str | None
    source_id: str | None
    event_time_utc: datetime | None
    available_at_utc: datetime | None
    knowledge_cutoff_utc: datetime
    logical_time_utc: datetime
    processing_time_utc: datetime
    ledger_commit_logical_time_utc: datetime
    configuration_identity: str
    pipeline_identity: str
    recovery_epoch: int
    decision_id: str
    trace_id: str
    processing_context_id: str
    final_classification: str
    reason_codes: tuple[str, ...]
    restriction_references: tuple[str, ...]
    failure_reasons: tuple[str, ...]
    completeness: str
    completeness_reasons: tuple[str, ...]
    release_provenance: Mapping[str, Any]
    schema_identities: Mapping[str, str]
    policy_identities: Mapping[str, str]
    stage_evidence: tuple[Mapping[str, Any], ...]
    p46_processing_context: Mapping[str, Any]
    p46_final_decision: Mapping[str, Any]
    p46_decision_trace: Mapping[str, Any]
    replay_verification: Mapping[str, Any] | None
    supersedes_record_id: str | None
    invalidates_record_id: str | None
    correction_of_record_id: str | None
    correction_reason: str | None
    previous_record_hash: str
    evidence_fingerprint: str
    record_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "release_provenance", MappingProxyType(dict(self.release_provenance)))
        object.__setattr__(self, "schema_identities", MappingProxyType(dict(self.schema_identities)))
        object.__setattr__(self, "policy_identities", MappingProxyType(dict(self.policy_identities)))
        object.__setattr__(self, "stage_evidence", tuple(MappingProxyType(dict(item)) for item in self.stage_evidence))
        object.__setattr__(self, "p46_processing_context", MappingProxyType(dict(self.p46_processing_context)))
        object.__setattr__(self, "p46_final_decision", MappingProxyType(dict(self.p46_final_decision)))
        object.__setattr__(self, "p46_decision_trace", MappingProxyType(dict(self.p46_decision_trace)))
        if self.replay_verification is not None:
            object.__setattr__(self, "replay_verification", MappingProxyType(dict(self.replay_verification)))


@dataclass(frozen=True)
class LedgerIntegrityState:
    schema_version: str
    ledger_version: str
    ledger_policy_identity: str
    genesis_identity: str
    ledger_head: str
    latest_sequence: int
    ledger_record_count: int
    latest_record_id: str | None
    latest_decision_id: str | None
    latest_trace_id: str | None
    verification_status: str
    reason_codes: tuple[str, ...]
    verified_at_utc: datetime | None


@dataclass(frozen=True)
class LedgerVerificationResult:
    status: LedgerVerificationStatus
    reason_codes: tuple[str, ...]
    checked_count: int
    ledger_head: str
    latest_sequence: int
    ledger_record_count: int
    verified_at_utc: datetime


@dataclass(frozen=True)
class ResearchDecisionEvidenceBundle:
    schema_version: str
    record: ResearchDecisionEvidenceRecord
    integrity: LedgerVerificationResult
    decision: Mapping[str, Any]
    trace: Mapping[str, Any]
    processing_context: Mapping[str, Any]
    stage_evidence: tuple[Mapping[str, Any], ...]
    release_provenance: Mapping[str, Any]
    reconstruction_recomputed_decision: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision", MappingProxyType(dict(self.decision)))
        object.__setattr__(self, "trace", MappingProxyType(dict(self.trace)))
        object.__setattr__(self, "processing_context", MappingProxyType(dict(self.processing_context)))
        object.__setattr__(self, "stage_evidence", tuple(MappingProxyType(dict(item)) for item in self.stage_evidence))
        object.__setattr__(self, "release_provenance", MappingProxyType(dict(self.release_provenance)))


@dataclass(frozen=True)
class ReplayVerificationEvidence:
    replay_evidence_id: str
    schema_version: str
    original_decision_id: str
    original_trace_id: str
    original_evidence_record_id: str
    replay_decision_fingerprint: str
    replay_trace_fingerprint: str
    expected_decision_fingerprint: str
    expected_trace_fingerprint: str
    status: str
    reason_codes: tuple[str, ...]
    verified_at_utc: datetime
    software_pipeline_identity: str


@dataclass(frozen=True)
class LedgerCommitResult:
    acceptance: LedgerCommitAcceptance
    record: ResearchDecisionEvidenceRecord
    integrity: LedgerVerificationResult
    reason_codes: tuple[str, ...]


class ResearchDecisionEvidenceLedger:
    """Authoritative append-only historical evidence ledger for P46 decisions."""

    HEAD_FILE = "ledger.head.json"
    RECORD_DIR = "records"
    QUARANTINE_DIR = "quarantine"
    TEMP_SUFFIX = ".tmp"

    def __init__(
        self,
        *,
        root: Path,
        clock: Any,
        audit: Any,
        release_provenance: ResearchEvidenceReleaseProvenance | None = None,
        max_recent_records: int = 128,
        max_query_limit: int = 100,
        failure_stage: str | None = None,
    ) -> None:
        self.root = Path(root)
        self.clock = clock
        self.audit = audit
        self.policy = LedgerPolicy.current()
        self.release_provenance = release_provenance or ResearchEvidenceReleaseProvenance(
            AMRTE_VERSION,
            "UNKNOWN",
            "UNKNOWN",
            "UNKNOWN",
            None,
            "P46_MASTER_RESEARCH_DECISION_RUNTIME",
        )
        self.max_recent_records = max(1, max_recent_records)
        self.max_query_limit = max(1, min(max_query_limit, 500))
        self.failure_stage = failure_stage
        self.restricted = False
        self._recent_records: OrderedDict[str, ResearchDecisionEvidenceRecord] = OrderedDict()
        self.metrics = {
            "commit_count": 0,
            "duplicate_count": 0,
            "conflict_count": 0,
            "verification_success": 0,
            "verification_failure": 0,
            "reconstruction_count": 0,
            "replay_match_count": 0,
            "replay_divergence_count": 0,
            "recovery_count": 0,
            "integrity_failure_count": 0,
            "commit_latency_units": 0,
            "verification_latency_units": 0,
        }
        self.initialize()

    @property
    def records_dir(self) -> Path:
        return self.root / self.RECORD_DIR

    @property
    def head_path(self) -> Path:
        return self.root / self.HEAD_FILE

    @property
    def genesis_identity(self) -> str:
        return research_evidence_genesis_identity()

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.records_dir.mkdir(exist_ok=True)
        (self.root / self.QUARANTINE_DIR).mkdir(exist_ok=True)
        self._quarantine_stale_temporaries()
        if not self.head_path.exists():
            state = self._empty_integrity_state()
            self._write_json_atomic(self.head_path, _jsonable(state))
        self._record_audit("research_evidence_ledger_initialized", {"head": self._head().ledger_head})

    def commit_decision_evidence(
        self,
        context: ResearchProcessingContext,
        decision: FinalResearchDecision,
        trace: ResearchDecisionTrace,
        *,
        record_type: EvidenceRecordType = EvidenceRecordType.ORIGINAL_DECISION,
        correction_of_record_id: str | None = None,
        supersedes_record_id: str | None = None,
        invalidates_record_id: str | None = None,
        correction_reason: str | None = None,
        replay_verification: ReplayVerificationEvidence | None = None,
    ) -> LedgerCommitResult:
        if self.restricted:
            raise LedgerIntegrityError("P47_LEDGER_RESTRICTED")
        self._record_audit("research_evidence_commit_started", {"decision_id": decision.decision_id})
        reasons = self._validate_p46_evidence(context, decision, trace)
        if reasons:
            raise LedgerValidationError(";".join(reasons))

        existing = self._find_by_ingestion_key(self._ingestion_key(context, decision, trace, record_type, replay_verification))
        candidate = self._build_record(
            context,
            decision,
            trace,
            record_type=record_type,
            correction_of_record_id=correction_of_record_id,
            supersedes_record_id=supersedes_record_id,
            invalidates_record_id=invalidates_record_id,
            correction_reason=correction_reason,
            replay_verification=replay_verification,
            sequence=(self._head().latest_sequence + 1),
            previous_hash=self._head().ledger_head,
        )
        if existing is not None:
            if existing.evidence_fingerprint != candidate.evidence_fingerprint:
                self.metrics["conflict_count"] += 1
                self._record_audit("research_evidence_conflict_detected", {"decision_id": decision.decision_id, "existing_record_id": existing.evidence_record_id})
                raise LedgerConflictError("P47_IDENTITY_COLLISION")
            self.metrics["duplicate_count"] += 1
            self._record_audit("research_evidence_duplicate_detected", {"record_id": existing.evidence_record_id})
            return LedgerCommitResult(LedgerCommitAcceptance.DUPLICATE, existing, self.verify_record(existing.evidence_record_id), ("P47_DUPLICATE_EVIDENCE",))

        self._detect_conflicts(candidate)
        if self.failure_stage == "before_record_write":
            raise OSError("injected before record write failure")
        record_path = self._record_path(candidate.ledger_sequence, candidate.evidence_record_id)
        self._write_json_atomic(record_path, _record_to_dict(candidate), stage="record")
        if self.failure_stage == "after_record_write":
            raise OSError("injected after record write failure")
        head = LedgerIntegrityState(
            LEDGER_INTEGRITY_STATE_SCHEMA_VERSION,
            RESEARCH_DECISION_EVIDENCE_LEDGER_VERSION,
            self.policy.policy_identity,
            self.genesis_identity,
            candidate.record_hash,
            candidate.ledger_sequence,
            self._head().ledger_record_count + 1,
            candidate.evidence_record_id,
            candidate.decision_id,
            candidate.trace_id,
            LedgerVerificationStatus.VERIFIED.value,
            (),
            self.clock.now(),
        )
        if self.failure_stage == "before_head_update":
            raise OSError("injected before head update failure")
        self._write_json_atomic(self.head_path, _jsonable(head), stage="head")
        if self.failure_stage == "after_head_update":
            raise OSError("injected after head update failure")
        self._remember(candidate)
        self.metrics["commit_count"] += 1
        integrity = self.verify_record(candidate.evidence_record_id)
        self._record_audit("research_evidence_committed", {"record_id": candidate.evidence_record_id, "sequence": candidate.ledger_sequence})
        return LedgerCommitResult(LedgerCommitAcceptance.COMMITTED, candidate, integrity, ("P47_EVIDENCE_COMMITTED",))

    def append_correction(self, original_record_id: str, reason: str) -> LedgerCommitResult:
        original = self.get_record(original_record_id)
        context, decision, trace = self._p46_objects_from_record(original)
        return self.commit_decision_evidence(
            context,
            decision,
            trace,
            record_type=EvidenceRecordType.CORRECTION,
            correction_of_record_id=original_record_id,
            correction_reason=reason,
        )

    def append_supersession(self, original_record_id: str, reason: str) -> LedgerCommitResult:
        original = self.get_record(original_record_id)
        context, decision, trace = self._p46_objects_from_record(original)
        return self.commit_decision_evidence(
            context,
            decision,
            trace,
            record_type=EvidenceRecordType.SUPERSESSION,
            supersedes_record_id=original_record_id,
            correction_reason=reason,
        )

    def append_invalidation(self, original_record_id: str, reason: str) -> LedgerCommitResult:
        original = self.get_record(original_record_id)
        context, decision, trace = self._p46_objects_from_record(original)
        return self.commit_decision_evidence(
            context,
            decision,
            trace,
            record_type=EvidenceRecordType.INVALIDATION,
            invalidates_record_id=original_record_id,
            correction_reason=reason,
        )

    def verify_replay(
        self,
        record_id: str,
        replay_decision: FinalResearchDecision,
        replay_trace: ResearchDecisionTrace,
        *,
        pipeline_identity: str | None = None,
        persist: bool = True,
    ) -> ReplayVerificationEvidence:
        record = self.get_record(record_id)
        original_decision_fp = str(record.p46_final_decision["decision_fingerprint"])
        original_trace_fp = str(record.p46_decision_trace["trace_fingerprint"])
        cross_version = pipeline_identity is not None and pipeline_identity != record.pipeline_identity
        status = (
            ReplayVerificationStatus.CROSS_VERSION_REPLAY
            if cross_version
            else ReplayVerificationStatus.MATCH
            if replay_decision.decision_fingerprint == original_decision_fp and replay_trace.trace_fingerprint == original_trace_fp
            else ReplayVerificationStatus.DIVERGED
        )
        reasons = ("P47_REPLAY_MATCH",) if status is ReplayVerificationStatus.MATCH else (f"P47_{status.value}",)
        evidence_id = deterministic_id(
            "p47_replay_verification_evidence",
            record_id,
            replay_decision.decision_fingerprint,
            replay_trace.trace_fingerprint,
            status.value,
            pipeline_identity or record.pipeline_identity,
        )
        evidence = ReplayVerificationEvidence(
            evidence_id,
            REPLAY_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
            record.decision_id,
            record.trace_id,
            record_id,
            replay_decision.decision_fingerprint,
            replay_trace.trace_fingerprint,
            original_decision_fp,
            original_trace_fp,
            status.value,
            reasons,
            self.clock.now(),
            pipeline_identity or record.pipeline_identity,
        )
        if status is ReplayVerificationStatus.MATCH:
            self.metrics["replay_match_count"] += 1
        elif status is ReplayVerificationStatus.DIVERGED:
            self.metrics["replay_divergence_count"] += 1
        if persist and status is not ReplayVerificationStatus.MATCH:
            context, decision, trace = self._p46_objects_from_record(record)
            self.commit_decision_evidence(
                context,
                decision,
                trace,
                record_type=EvidenceRecordType.REPLAY_DIVERGENCE,
                correction_of_record_id=record_id,
                correction_reason=status.value,
                replay_verification=evidence,
            )
        elif persist:
            context, decision, trace = self._p46_objects_from_record(record)
            self.commit_decision_evidence(
                context,
                decision,
                trace,
                record_type=EvidenceRecordType.REPLAY_VERIFICATION,
                correction_of_record_id=record_id,
                correction_reason=status.value,
                replay_verification=evidence,
            )
        self._record_audit("research_evidence_replay_verified", {"record_id": record_id, "status": status.value})
        return evidence

    def verify_ledger(self, *, start_sequence: int | None = None, end_sequence: int | None = None) -> LedgerVerificationResult:
        self._record_audit("research_evidence_verification_started", {"start": start_sequence, "end": end_sequence})
        head = self._head()
        reasons: list[str] = []
        records = self._load_records()
        if any(record.ledger_sequence > head.latest_sequence for record in records):
            reasons.append("P47_UNCOMMITTED_RECORD_PRESENT")
        committed = tuple(record for record in records if record.ledger_sequence <= head.latest_sequence)
        if len({record.ledger_sequence for record in committed}) != len(committed):
            reasons.append("P47_SEQUENCE_CONFLICT")
        if len({record.evidence_record_id for record in committed}) != len(committed):
            reasons.append("P47_RECORD_ID_CONFLICT")
        if len(committed) != head.ledger_record_count:
            reasons.append("P47_RECORD_COUNT_MISMATCH")
        if start_sequence is not None or end_sequence is not None:
            start = start_sequence if start_sequence is not None else 1
            end = end_sequence if end_sequence is not None else head.latest_sequence
            committed = tuple(record for record in committed if start <= record.ledger_sequence <= end)
        previous = self.genesis_identity
        all_committed = tuple(record for record in records if record.ledger_sequence <= head.latest_sequence)
        by_sequence = {record.ledger_sequence: record for record in all_committed}
        for sequence in range(1, head.latest_sequence + 1):
            record = by_sequence.get(sequence)
            if record is None:
                reasons.append("P47_RECORD_DELETION_DETECTED")
                previous = "MISSING"
                continue
            record_reasons = self._verify_record_content(record, expected_previous=previous)
            reasons.extend(record_reasons)
            previous = record.record_hash
        if previous != head.ledger_head:
            reasons.append("P47_HEAD_MISMATCH")
        status = LedgerVerificationStatus.VERIFIED if not reasons else LedgerVerificationStatus.INVALID
        if reasons:
            self.metrics["verification_failure"] += 1
            self.metrics["integrity_failure_count"] += 1
            self.restricted = True
            self._record_audit("research_evidence_verification_failed", {"reasons": tuple(dict.fromkeys(reasons))})
        else:
            self.metrics["verification_success"] += 1
            self._record_audit("research_evidence_verified", {"count": len(committed)})
        return LedgerVerificationResult(status, tuple(dict.fromkeys(reasons)), len(committed), head.ledger_head, head.latest_sequence, head.ledger_record_count, self.clock.now())

    def verify_record(self, record_id: str) -> LedgerVerificationResult:
        record = self.get_record(record_id)
        previous = self.genesis_identity
        if record.ledger_sequence > 1:
            prior = self._find_by_sequence(record.ledger_sequence - 1)
            previous = prior.record_hash if prior is not None else "MISSING"
        reasons = self._verify_record_content(record, expected_previous=previous)
        status = LedgerVerificationStatus.VERIFIED if not reasons else LedgerVerificationStatus.INVALID
        if reasons:
            self.restricted = True
        return LedgerVerificationResult(status, tuple(dict.fromkeys(reasons)), 1, self._head().ledger_head, self._head().latest_sequence, self._head().ledger_record_count, self.clock.now())

    def recover(self) -> LedgerVerificationResult:
        self.metrics["recovery_count"] += 1
        self._record_audit("research_evidence_recovery_started", {})
        self._quarantine_stale_temporaries()
        self._quarantine_uncommitted_records()
        result = self.verify_ledger()
        if result.status is LedgerVerificationStatus.VERIFIED:
            self.restricted = False
            self._record_audit("research_evidence_recovery_completed", {"record_count": result.ledger_record_count})
        else:
            self.restricted = True
            self._record_audit("research_evidence_recovery_failed", {"reasons": result.reason_codes})
        return result

    def reconstruct_by_record_id(self, record_id: str) -> ResearchDecisionEvidenceBundle:
        record = self.get_record(record_id)
        integrity = self.verify_record(record_id)
        self.metrics["reconstruction_count"] += 1
        self._record_audit("research_evidence_reconstructed", {"record_id": record_id})
        return ResearchDecisionEvidenceBundle(
            RESEARCH_DECISION_EVIDENCE_BUNDLE_SCHEMA_VERSION,
            record,
            integrity,
            record.p46_final_decision,
            record.p46_decision_trace,
            record.p46_processing_context,
            record.stage_evidence,
            record.release_provenance,
        )

    def reconstruct_by_decision_id(self, decision_id: str) -> ResearchDecisionEvidenceBundle:
        return self.reconstruct_by_record_id(self._require_one(self.query(decision_id=decision_id)).evidence_record_id)

    def reconstruct_by_trace_id(self, trace_id: str) -> ResearchDecisionEvidenceBundle:
        return self.reconstruct_by_record_id(self._require_one(self.query(trace_id=trace_id)).evidence_record_id)

    def query(
        self,
        *,
        evidence_record_id: str | None = None,
        decision_id: str | None = None,
        trace_id: str | None = None,
        processing_id: str | None = None,
        observation_id: str | None = None,
        dataset_id: str | None = None,
        classification: str | None = None,
        sequence_start: int | None = None,
        sequence_end: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[ResearchDecisionEvidenceRecord, ...]:
        limit = max(1, min(limit, self.max_query_limit))
        selected: list[ResearchDecisionEvidenceRecord] = []
        for record in self._load_records():
            if evidence_record_id is not None and record.evidence_record_id != evidence_record_id:
                continue
            if decision_id is not None and record.decision_id != decision_id:
                continue
            if trace_id is not None and record.trace_id != trace_id:
                continue
            if processing_id is not None and record.processing_context_id != processing_id:
                continue
            if observation_id is not None and record.observation_id != observation_id:
                continue
            if dataset_id is not None and record.dataset_id != dataset_id:
                continue
            if classification is not None and record.final_classification != classification:
                continue
            if sequence_start is not None and record.ledger_sequence < sequence_start:
                continue
            if sequence_end is not None and record.ledger_sequence > sequence_end:
                continue
            selected.append(record)
        selected.sort(key=lambda item: item.ledger_sequence)
        return tuple(selected[offset : offset + limit])

    def get_record(self, record_id: str) -> ResearchDecisionEvidenceRecord:
        if record_id in self._recent_records:
            return self._recent_records[record_id]
        matches = self.query(evidence_record_id=record_id, limit=1)
        if not matches:
            raise KeyError(record_id)
        self._remember(matches[0])
        return matches[0]

    def diagnostics(self) -> dict[str, Any]:
        head = self._head()
        return {
            "runtime_version": RESEARCH_DECISION_EVIDENCE_LEDGER_VERSION,
            "record_schema_version": RESEARCH_DECISION_EVIDENCE_RECORD_SCHEMA_VERSION,
            "record_schema_identity": research_decision_evidence_record_schema_identity(),
            "bundle_schema_version": RESEARCH_DECISION_EVIDENCE_BUNDLE_SCHEMA_VERSION,
            "bundle_schema_identity": research_decision_evidence_bundle_schema_identity(),
            "integrity_schema_version": LEDGER_INTEGRITY_STATE_SCHEMA_VERSION,
            "integrity_schema_identity": ledger_integrity_state_schema_identity(),
            "replay_schema_version": REPLAY_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
            "replay_schema_identity": replay_verification_evidence_schema_identity(),
            "ledger_policy": _jsonable(self.policy),
            "genesis_identity": self.genesis_identity,
            "ledger_head": head.ledger_head,
            "latest_sequence": head.latest_sequence,
            "ledger_record_count": head.ledger_record_count,
            "latest_record_id": head.latest_record_id,
            "latest_decision_id": head.latest_decision_id,
            "latest_trace_id": head.latest_trace_id,
            "integrity_status": head.verification_status,
            "last_verification": head.verified_at_utc.isoformat() if head.verified_at_utc else None,
            "metrics": dict(self.metrics),
            "health": self.component_health(None).name,
            "restricted": self.restricted,
            "memory": {"recent_record_cache_size": len(self._recent_records), "recent_record_cache_limit": self.max_recent_records},
            "financial_execution": "NONE",
        }

    def component_ready(self, context: Any) -> bool:
        return not self.restricted and self.verify_ledger().status is LedgerVerificationStatus.VERIFIED

    def component_health(self, context: Any) -> HealthStatus:
        if self.restricted:
            return HealthStatus.RESTRICTED
        try:
            return HealthStatus.HEALTHY if self._head().verification_status == LedgerVerificationStatus.VERIFIED.value else HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.UNHEALTHY

    def _build_record(
        self,
        context: ResearchProcessingContext,
        decision: FinalResearchDecision,
        trace: ResearchDecisionTrace,
        *,
        record_type: EvidenceRecordType,
        correction_of_record_id: str | None,
        supersedes_record_id: str | None,
        invalidates_record_id: str | None,
        correction_reason: str | None,
        replay_verification: ReplayVerificationEvidence | None,
        sequence: int,
        previous_hash: str,
    ) -> ResearchDecisionEvidenceRecord:
        stage = tuple(_jsonable(item) for item in context.stage_records)
        schema_identities = {
            **required_stage_schema_identities(),
            "P46_PROCESSING_CONTEXT": research_processing_context_schema_identity(),
            "P46_FINAL_DECISION": final_research_decision_schema_identity(),
            "P46_DECISION_TRACE": research_decision_trace_schema_identity(),
            "P47_EVIDENCE_RECORD": research_decision_evidence_record_schema_identity(),
        }
        policies = {
            "P46_MASTER_RESEARCH_DECISION_POLICY": "P46_MASTER_RESEARCH_DECISION_DEFAULT",
            self.policy.policy_id: self.policy.policy_identity,
        }
        completeness, completeness_reasons = self._completeness(context, decision, trace)
        release = _jsonable(self.release_provenance)
        replay_payload = _jsonable(replay_verification) if replay_verification is not None else None
        ingestion_key = self._ingestion_key(context, decision, trace, record_type, replay_verification)
        content = {
            "record_type": record_type.value,
            "ingestion_key": ingestion_key,
            "dataset_id": context.dataset_id,
            "dataset_fingerprint": context.dataset_fingerprint,
            "knowledge_cutoff": context.knowledge_cutoff_utc,
            "configuration_identity": context.configuration_identity,
            "pipeline_identity": self.release_provenance.pipeline_identity,
            "recovery_epoch": context.recovery_epoch,
            "decision_id": decision.decision_id,
            "trace_id": trace.trace_id,
            "context_id": context.context_id,
            "classification": decision.final_classification,
            "reason_codes": decision.reason_codes,
            "release": release,
            "schemas": schema_identities,
            "policies": policies,
            "stage": stage,
            "context": _jsonable(context),
            "decision": _jsonable(decision),
            "trace": _jsonable(trace),
            "replay": replay_payload,
            "links": (correction_of_record_id, supersedes_record_id, invalidates_record_id, correction_reason),
        }
        evidence_fingerprint = _sha256_json(content)
        record_id = deterministic_id("p47_research_decision_evidence", evidence_fingerprint)
        record_hash = _record_hash(record_id, sequence, previous_hash, evidence_fingerprint)
        observation_stage = next((item for item in context.stage_records if item.stage == "P39_MARKET_OBSERVATION"), None)
        restrictions = tuple(item for item in decision.reason_codes if "RESTRICT" in item or "BLOCK" in item or "PROTECT" in item)
        failures = tuple(item for item in decision.reason_codes if "FAILED" in item or "MISMATCH" in item or "UNAVAILABLE" in item)
        return ResearchDecisionEvidenceRecord(
            record_id,
            RESEARCH_DECISION_EVIDENCE_RECORD_SCHEMA_VERSION,
            research_decision_evidence_record_schema_identity(),
            sequence,
            record_type.value,
            ingestion_key,
            context.dataset_id,
            context.dataset_fingerprint,
            observation_stage.evidence_id if observation_stage else None,
            None,
            None,
            observation_stage.as_of_timestamp_utc if observation_stage else None,
            context.knowledge_cutoff_utc,
            context.created_at_utc,
            decision.created_at_utc,
            self.clock.now(),
            context.configuration_identity,
            self.release_provenance.pipeline_identity,
            context.recovery_epoch,
            decision.decision_id,
            trace.trace_id,
            context.context_id,
            decision.final_classification,
            decision.reason_codes,
            restrictions,
            failures,
            completeness.value,
            completeness_reasons,
            release,
            schema_identities,
            policies,
            stage,
            _jsonable(context),
            _jsonable(decision),
            _jsonable(trace),
            replay_payload,
            supersedes_record_id,
            invalidates_record_id,
            correction_of_record_id,
            correction_reason,
            previous_hash,
            evidence_fingerprint,
            record_hash,
        )

    def _validate_p46_evidence(
        self,
        context: ResearchProcessingContext,
        decision: FinalResearchDecision,
        trace: ResearchDecisionTrace,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if context.schema_version != RESEARCH_PROCESSING_CONTEXT_SCHEMA_VERSION or context.schema_identity != research_processing_context_schema_identity():
            reasons.append("P47_PROCESSING_CONTEXT_SCHEMA_MISMATCH")
        if decision.schema_version != FINAL_RESEARCH_DECISION_SCHEMA_VERSION or decision.schema_identity != final_research_decision_schema_identity():
            reasons.append("P47_DECISION_SCHEMA_MISMATCH")
        if trace.schema_version != RESEARCH_DECISION_TRACE_SCHEMA_VERSION or trace.schema_identity != research_decision_trace_schema_identity():
            reasons.append("P47_TRACE_SCHEMA_MISMATCH")
        if decision.context_id != context.context_id or trace.context_id != context.context_id:
            reasons.append("P47_PROCESSING_CONTEXT_MISMATCH")
        if trace.decision_id != decision.decision_id:
            reasons.append("P47_DECISION_TRACE_MISMATCH")
        if decision.configuration_identity != context.configuration_identity:
            reasons.append("P47_CONFIGURATION_MISMATCH")
        if decision.knowledge_cutoff_utc != context.knowledge_cutoff_utc:
            reasons.append("P47_KNOWLEDGE_CUTOFF_MISMATCH")
        if decision.recovery_epoch != context.recovery_epoch:
            reasons.append("P47_RECOVERY_EPOCH_MISMATCH")
        stages = tuple(item.stage for item in context.stage_records)
        expected_stages = tuple(required_stage_schema_identities())
        if stages != expected_stages and decision.final_classification != "FAILED":
            reasons.append("P47_STAGE_ORDER_MISMATCH")
        elif stages != expected_stages:
            expected_position = {stage: index for index, stage in enumerate(expected_stages)}
            positions = [expected_position.get(stage, -1) for stage in stages]
            if any(position < 0 for position in positions) or positions != sorted(positions):
                reasons.append("P47_STAGE_ORDER_MISMATCH")
        if trace.trace_id != deterministic_id("p46_research_decision_trace", trace.trace_fingerprint):
            reasons.append("P47_TRACE_IDENTITY_MISMATCH")
        expected_decision_id = deterministic_id("p46_final_research_decision", decision.decision_fingerprint)
        if decision.decision_id != expected_decision_id:
            reasons.append("P47_DECISION_IDENTITY_MISMATCH")
        return tuple(dict.fromkeys(reasons))

    def _completeness(
        self,
        context: ResearchProcessingContext,
        decision: FinalResearchDecision,
        trace: ResearchDecisionTrace,
    ) -> tuple[EvidenceCompleteness, tuple[str, ...]]:
        reasons: list[str] = []
        if not context.stage_records:
            reasons.append("P47_STAGE_EVIDENCE_MISSING")
        if decision.final_classification == "FAILED":
            reasons.append("P47_FAILED_DECISION_AVAILABLE_EVIDENCE_ONLY")
            return EvidenceCompleteness.INCOMPLETE, tuple(reasons)
        if any(item.status != "PRESENT" for item in context.stage_records):
            reasons.append("P47_MANDATORY_STAGE_EVIDENCE_UNAVAILABLE")
        if not trace.stage_outcomes:
            reasons.append("P47_TRACE_EVALUATIONS_MISSING")
        return (EvidenceCompleteness.COMPLETE if not reasons else EvidenceCompleteness.INCOMPLETE), tuple(reasons)

    def _detect_conflicts(self, candidate: ResearchDecisionEvidenceRecord) -> None:
        for record in self._load_records():
            if record.record_type != EvidenceRecordType.ORIGINAL_DECISION.value or candidate.record_type != EvidenceRecordType.ORIGINAL_DECISION.value:
                continue
            if record.decision_id == candidate.decision_id and record.trace_id != candidate.trace_id:
                self.metrics["conflict_count"] += 1
                raise LedgerConflictError("P47_SAME_DECISION_DIFFERENT_TRACE")
            if record.trace_id == candidate.trace_id and record.decision_id != candidate.decision_id:
                self.metrics["conflict_count"] += 1
                raise LedgerConflictError("P47_SAME_TRACE_DIFFERENT_DECISION")
            if record.processing_context_id == candidate.processing_context_id and record.evidence_fingerprint != candidate.evidence_fingerprint:
                self.metrics["conflict_count"] += 1
                raise LedgerConflictError("P47_PROCESSING_CONTEXT_CONFLICT")
            if record.ledger_sequence == candidate.ledger_sequence:
                self.metrics["conflict_count"] += 1
                raise LedgerConflictError("P47_SEQUENCE_CONFLICT")
            if record.previous_record_hash == candidate.previous_record_hash and record.ledger_sequence == candidate.ledger_sequence:
                self.metrics["conflict_count"] += 1
                raise LedgerConflictError("P47_CHAIN_FORK_DETECTED")

    def _verify_record_content(self, record: ResearchDecisionEvidenceRecord, *, expected_previous: str) -> tuple[str, ...]:
        reasons: list[str] = []
        if record.schema_version != RESEARCH_DECISION_EVIDENCE_RECORD_SCHEMA_VERSION or record.schema_identity != research_decision_evidence_record_schema_identity():
            reasons.append("P47_RECORD_SCHEMA_MISMATCH")
        if record.previous_record_hash != expected_previous:
            reasons.append("P47_PREVIOUS_HASH_MISMATCH")
        if record.evidence_fingerprint != _record_content_fingerprint(record):
            reasons.append("P47_EVIDENCE_FINGERPRINT_MISMATCH")
        if record.evidence_record_id != deterministic_id("p47_research_decision_evidence", record.evidence_fingerprint):
            reasons.append("P47_RECORD_ID_MISMATCH")
        if record.record_hash != _record_hash(record.evidence_record_id, record.ledger_sequence, record.previous_record_hash, record.evidence_fingerprint):
            reasons.append("P47_RECORD_HASH_MISMATCH")
        if record.pipeline_identity != record.release_provenance.get("pipeline_identity"):
            reasons.append("P47_PIPELINE_IDENTITY_MISMATCH")
        if record.schema_identities.get("P46_PROCESSING_CONTEXT") != research_processing_context_schema_identity():
            reasons.append("P47_P46_CONTEXT_SCHEMA_MISMATCH")
        return reasons

    def _ingestion_key(
        self,
        context: ResearchProcessingContext,
        decision: FinalResearchDecision,
        trace: ResearchDecisionTrace,
        record_type: EvidenceRecordType,
        replay_verification: ReplayVerificationEvidence | None,
    ) -> str:
        return deterministic_id(
            "p47_research_evidence_ingestion",
            record_type.value,
            decision.decision_id,
            trace.trace_id,
            context.context_id,
            context.dataset_id,
            context.dataset_fingerprint,
            self.release_provenance.pipeline_identity,
            context.recovery_epoch,
            replay_verification.replay_evidence_id if replay_verification else "NO_REPLAY",
        )

    def _find_by_ingestion_key(self, key: str) -> ResearchDecisionEvidenceRecord | None:
        return next((record for record in self._load_records() if record.ingestion_key == key), None)

    def _find_by_sequence(self, sequence: int) -> ResearchDecisionEvidenceRecord | None:
        return next((record for record in self._load_records() if record.ledger_sequence == sequence), None)

    def _require_one(self, records: tuple[ResearchDecisionEvidenceRecord, ...]) -> ResearchDecisionEvidenceRecord:
        if not records:
            raise KeyError("P47_EVIDENCE_RECORD_NOT_FOUND")
        return records[0]

    def _head(self) -> LedgerIntegrityState:
        raw = json.loads(self.head_path.read_text(encoding="utf-8"))
        return _integrity_from_dict(raw)

    def _empty_integrity_state(self) -> LedgerIntegrityState:
        return LedgerIntegrityState(
            LEDGER_INTEGRITY_STATE_SCHEMA_VERSION,
            RESEARCH_DECISION_EVIDENCE_LEDGER_VERSION,
            self.policy.policy_identity,
            self.genesis_identity,
            self.genesis_identity,
            0,
            0,
            None,
            None,
            None,
            LedgerVerificationStatus.VERIFIED.value,
            (),
            self.clock.now(),
        )

    def _record_path(self, sequence: int, record_id: str) -> Path:
        return self.records_dir / f"{sequence:012d}-{record_id}.json"

    def _load_records(self) -> tuple[ResearchDecisionEvidenceRecord, ...]:
        records = []
        for path in sorted(self.records_dir.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            records.append(_record_from_dict(raw))
        return tuple(sorted(records, key=lambda item: (item.ledger_sequence, item.evidence_record_id)))

    def _write_json_atomic(self, path: Path, payload: Mapping[str, Any], *, stage: str | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + self.TEMP_SUFFIX)
        encoded = (canonical_json(payload) + "\n").encode("utf-8")
        with temporary.open("wb") as handle:
            if self.failure_stage == "during_record_write" and stage == "record":
                handle.write(encoded[: max(1, len(encoded) // 2)])
                handle.flush()
                os.fsync(handle.fileno())
                raise OSError("injected during record write failure")
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)

    def _quarantine_stale_temporaries(self) -> None:
        quarantine = self.root / self.QUARANTINE_DIR
        quarantine.mkdir(exist_ok=True)
        for temporary in self.root.rglob(f"*{self.TEMP_SUFFIX}"):
            if self.QUARANTINE_DIR in temporary.parts:
                continue
            target = quarantine / f"stale-{temporary.name}-{self.clock.now().strftime('%Y%m%dT%H%M%S%fZ')}"
            os.replace(temporary, target)
            self._record_audit("research_evidence_recovery_completed", {"quarantined_temporary": target.name})

    def _quarantine_uncommitted_records(self) -> None:
        head = self._head()
        quarantine = self.root / self.QUARANTINE_DIR
        for path in sorted(self.records_dir.glob("*.json")):
            try:
                record = _record_from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                target = quarantine / f"corrupt-{path.name}"
                os.replace(path, target)
                continue
            if record.ledger_sequence > head.latest_sequence:
                target = quarantine / f"uncommitted-{path.name}"
                os.replace(path, target)

    def _remember(self, record: ResearchDecisionEvidenceRecord) -> None:
        self._recent_records[record.evidence_record_id] = record
        while len(self._recent_records) > self.max_recent_records:
            self._recent_records.popitem(last=False)

    def _p46_objects_from_record(
        self,
        record: ResearchDecisionEvidenceRecord,
    ) -> tuple[ResearchProcessingContext, FinalResearchDecision, ResearchDecisionTrace]:
        return (
            _context_from_dict(record.p46_processing_context),
            _decision_from_dict(record.p46_final_decision),
            _trace_from_dict(record.p46_decision_trace),
        )

    def _record_audit(self, event: str, payload: Mapping[str, Any]) -> None:
        if self.audit is not None:
            self.audit.record(event, payload)


class ResearchDecisionEvidenceLedgerComponent:
    def __init__(self, component_id: str, runtime_holder: dict[str, ResearchDecisionEvidenceLedger] | None = None) -> None:
        self.component_id = component_id
        self.runtime: ResearchDecisionEvidenceLedger | None = None
        self._runtime_holder = runtime_holder

    def initialize_component(self, context: Any) -> None:
        if self.runtime is None:
            if self._runtime_holder is not None and "runtime" in self._runtime_holder:
                self.runtime = self._runtime_holder["runtime"]
            else:
                self.runtime = ResearchDecisionEvidenceLedger(root=Path("data/research-evidence-ledger"), clock=context.services["clock"], audit=context.services["audit"])
                if self._runtime_holder is not None:
                    self._runtime_holder["runtime"] = self.runtime
        audit = context.services.get("audit") if hasattr(context, "services") else None
        if audit is not None:
            audit.record("research_evidence_ledger_component_initialized", {"component_id": self.component_id, "schema_identity": research_decision_evidence_record_schema_identity()})

    def component_ready(self, context: Any) -> bool:
        return self.runtime is not None and self.runtime.component_ready(context)

    def component_health(self, context: Any) -> HealthStatus:
        return self.runtime.component_health(context) if self.runtime is not None else HealthStatus.UNKNOWN

    def diagnostics(self) -> dict[str, Any]:
        payload = self.runtime.diagnostics() if self.runtime is not None else {}
        payload["component_id"] = self.component_id
        return payload


def research_decision_evidence_component_registrations() -> tuple[tuple[ComponentMetadata, ResearchDecisionEvidenceLedgerComponent], ...]:
    holder: dict[str, ResearchDecisionEvidenceLedger] = {}
    capabilities = ComponentCapabilities(lifecycle=True, persistence=True, recovery=True, health=True, diagnostics=True, activation=True)
    definitions = (
        ("evidence_validation", ("master_research_decision", "research_decision_trace")),
        ("evidence_serialization", ("evidence_validation",)),
        ("research_evidence_ledger", ("evidence_serialization",)),
        ("ledger_integrity_verification", ("research_evidence_ledger",)),
        ("evidence_reconstruction", ("ledger_integrity_verification",)),
    )
    return tuple((ComponentMetadata(component_id, ComponentType.RESEARCH, RESEARCH_DECISION_EVIDENCE_LEDGER_VERSION, True, dependencies, capabilities), ResearchDecisionEvidenceLedgerComponent(component_id, holder)) for component_id, dependencies in definitions)


def research_decision_evidence_components_from_inventory(inventory: tuple[Mapping[str, Any], ...]) -> dict[str, Mapping[str, Any]]:
    ids = {"evidence_validation", "evidence_serialization", "research_evidence_ledger", "ledger_integrity_verification", "evidence_reconstruction"}
    return {item["component_id"]: item for item in inventory if item.get("component_id") in ids}


def canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def research_decision_evidence_record_schema_identity() -> str:
    return _sha256_json({"schema": "p47_research_decision_evidence_record", "version": RESEARCH_DECISION_EVIDENCE_RECORD_SCHEMA_VERSION, "fields": tuple(ResearchDecisionEvidenceRecord.__dataclass_fields__), "p46": {"context": research_processing_context_schema_identity(), "decision": final_research_decision_schema_identity(), "trace": research_decision_trace_schema_identity()}})


def research_decision_evidence_bundle_schema_identity() -> str:
    return _sha256_json({"schema": "p47_research_decision_evidence_bundle", "version": RESEARCH_DECISION_EVIDENCE_BUNDLE_SCHEMA_VERSION, "fields": tuple(ResearchDecisionEvidenceBundle.__dataclass_fields__), "record": research_decision_evidence_record_schema_identity()})


def ledger_integrity_state_schema_identity() -> str:
    return _sha256_json({"schema": "p47_ledger_integrity_state", "version": LEDGER_INTEGRITY_STATE_SCHEMA_VERSION, "fields": tuple(LedgerIntegrityState.__dataclass_fields__), "policy": LedgerPolicy.current().policy_identity})


def replay_verification_evidence_schema_identity() -> str:
    return _sha256_json({"schema": "p47_replay_verification_evidence", "version": REPLAY_VERIFICATION_EVIDENCE_SCHEMA_VERSION, "fields": tuple(ReplayVerificationEvidence.__dataclass_fields__), "record": research_decision_evidence_record_schema_identity()})


def research_evidence_genesis_identity() -> str:
    return _sha256_json({"schema": "p47_research_evidence_genesis", "version": "1.0", "ledger_policy_identity": LedgerPolicy.current().policy_identity, "ledger_version": RESEARCH_DECISION_EVIDENCE_LEDGER_VERSION})


def _record_hash(record_id: str, sequence: int, previous_hash: str, evidence_fingerprint: str) -> str:
    return _sha256_json({"record_id": record_id, "sequence": sequence, "previous_record_hash": previous_hash, "evidence_fingerprint": evidence_fingerprint, "hash_algorithm": "sha256"})


def _record_content_fingerprint(record: ResearchDecisionEvidenceRecord) -> str:
    return _sha256_json(
        {
            "record_type": record.record_type,
            "ingestion_key": record.ingestion_key,
            "dataset_id": record.dataset_id,
            "dataset_fingerprint": record.dataset_fingerprint,
            "knowledge_cutoff": record.knowledge_cutoff_utc,
            "configuration_identity": record.configuration_identity,
            "pipeline_identity": record.pipeline_identity,
            "recovery_epoch": record.recovery_epoch,
            "decision_id": record.decision_id,
            "trace_id": record.trace_id,
            "context_id": record.processing_context_id,
            "classification": record.final_classification,
            "reason_codes": record.reason_codes,
            "release": record.release_provenance,
            "schemas": record.schema_identities,
            "policies": record.policy_identities,
            "stage": record.stage_evidence,
            "context": record.p46_processing_context,
            "decision": record.p46_final_decision,
            "trace": record.p46_decision_trace,
            "replay": record.replay_verification,
            "links": (
                record.correction_of_record_id,
                record.supersedes_record_id,
                record.invalidates_record_id,
                record.correction_reason,
            ),
        }
    )


def _record_to_dict(record: ResearchDecisionEvidenceRecord) -> dict[str, Any]:
    return _jsonable(record)


def _record_from_dict(raw: Mapping[str, Any]) -> ResearchDecisionEvidenceRecord:
    return ResearchDecisionEvidenceRecord(
        str(raw["evidence_record_id"]),
        str(raw["schema_version"]),
        str(raw["schema_identity"]),
        int(raw["ledger_sequence"]),
        str(raw["record_type"]),
        str(raw["ingestion_key"]),
        str(raw["dataset_id"]),
        str(raw["dataset_fingerprint"]),
        raw.get("observation_id"),
        raw.get("source_id"),
        _dt(raw.get("event_time_utc")),
        _dt(raw.get("available_at_utc")),
        _dt_required(raw["knowledge_cutoff_utc"]),
        _dt_required(raw["logical_time_utc"]),
        _dt_required(raw["processing_time_utc"]),
        _dt_required(raw["ledger_commit_logical_time_utc"]),
        str(raw["configuration_identity"]),
        str(raw["pipeline_identity"]),
        int(raw["recovery_epoch"]),
        str(raw["decision_id"]),
        str(raw["trace_id"]),
        str(raw["processing_context_id"]),
        str(raw["final_classification"]),
        tuple(raw.get("reason_codes", ())),
        tuple(raw.get("restriction_references", ())),
        tuple(raw.get("failure_reasons", ())),
        str(raw["completeness"]),
        tuple(raw.get("completeness_reasons", ())),
        dict(raw.get("release_provenance", {})),
        dict(raw.get("schema_identities", {})),
        dict(raw.get("policy_identities", {})),
        tuple(dict(item) for item in raw.get("stage_evidence", ())),
        dict(raw["p46_processing_context"]),
        dict(raw["p46_final_decision"]),
        dict(raw["p46_decision_trace"]),
        dict(raw["replay_verification"]) if raw.get("replay_verification") is not None else None,
        raw.get("supersedes_record_id"),
        raw.get("invalidates_record_id"),
        raw.get("correction_of_record_id"),
        raw.get("correction_reason"),
        str(raw["previous_record_hash"]),
        str(raw["evidence_fingerprint"]),
        str(raw["record_hash"]),
    )


def _integrity_from_dict(raw: Mapping[str, Any]) -> LedgerIntegrityState:
    return LedgerIntegrityState(
        str(raw["schema_version"]),
        str(raw["ledger_version"]),
        str(raw["ledger_policy_identity"]),
        str(raw["genesis_identity"]),
        str(raw["ledger_head"]),
        int(raw["latest_sequence"]),
        int(raw["ledger_record_count"]),
        raw.get("latest_record_id"),
        raw.get("latest_decision_id"),
        raw.get("latest_trace_id"),
        str(raw["verification_status"]),
        tuple(raw.get("reason_codes", ())),
        _dt(raw.get("verified_at_utc")),
    )


def _context_from_dict(raw: Mapping[str, Any]) -> ResearchProcessingContext:
    from amrte.research.decision_runtime import ResearchStageEvidence

    return ResearchProcessingContext(
        str(raw["context_id"]),
        str(raw["schema_version"]),
        str(raw["schema_identity"]),
        _dt_required(raw["created_at_utc"]),
        str(raw["dataset_id"]),
        str(raw["dataset_fingerprint"]),
        _dt_required(raw["knowledge_cutoff_utc"]),
        str(raw["configuration_identity"]),
        int(raw["recovery_epoch"]),
        str(raw["p45_protection_snapshot_id"]),
        tuple(
            ResearchStageEvidence(
                str(item["stage"]),
                str(item["evidence_id"]),
                str(item["schema_version"]),
                str(item["schema_identity"]),
                str(item["dataset_id"]),
                str(item["dataset_fingerprint"]),
                _dt_required(item["as_of_timestamp_utc"]),
                _dt_required(item["knowledge_cutoff_utc"]),
                str(item["configuration_identity"]),
                int(item["recovery_epoch"]),
                str(item["evidence_fingerprint"]),
                str(item.get("status", "PRESENT")),
                tuple(item.get("source_evidence_ids", ())),
                item.get("stage_decision"),
            )
            for item in raw["stage_records"]
        ),
        str(raw["context_fingerprint"]),
        str(raw["idempotency_key"]),
    )


def _decision_from_dict(raw: Mapping[str, Any]) -> FinalResearchDecision:
    return FinalResearchDecision(
        str(raw["decision_id"]),
        str(raw["schema_version"]),
        str(raw["schema_identity"]),
        str(raw["context_id"]),
        str(raw["p45_protection_snapshot_id"]),
        str(raw["final_classification"]),
        str(raw["effective_permission"]),
        tuple(raw.get("reason_codes", ())),
        tuple(raw.get("warnings", ())),
        tuple(tuple(item) for item in raw.get("lineage_stage_ids", ())),
        _dt_required(raw["created_at_utc"]),
        _dt_required(raw["knowledge_cutoff_utc"]),
        str(raw["configuration_identity"]),
        int(raw["recovery_epoch"]),
        str(raw["decision_fingerprint"]),
        bool(raw.get("research_only", True)),
        str(raw.get("trade_authorization", "NONE")),
        str(raw.get("financial_authorization", "NONE")),
        str(raw.get("financial_execution", "NONE")),
    )


def _trace_from_dict(raw: Mapping[str, Any]) -> ResearchDecisionTrace:
    from amrte.core.observability_types import DecisionEvaluation, DecisionOutcome, DecisionStatus, DecisionTrace

    core_raw = raw["core_trace"]
    core = DecisionTrace(
        str(core_raw["decision_id"]),
        str(core_raw["correlation_id"]),
        _dt_required(core_raw["started_at"]),
        tuple(
            DecisionEvaluation(
                str(item["gate"]),
                DecisionStatus[str(item["status"])],
                str(item["reason_code"]),
                str(item["explanation"]),
                tuple(item.get("input_references", ())),
            )
            for item in core_raw["evaluations"]
        ),
        DecisionOutcome[str(core_raw["outcome"])],
        str(core_raw["outcome_reason"]),
        _dt_required(core_raw["completed_at"]),
        core_raw.get("short_circuited_at"),
    )
    return ResearchDecisionTrace(
        str(raw["trace_id"]),
        str(raw["schema_version"]),
        str(raw["schema_identity"]),
        str(raw["decision_id"]),
        str(raw["context_id"]),
        core,
        tuple(dict(item) for item in raw["stage_outcomes"]),
        str(raw["trace_fingerprint"]),
    )


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    return _dt_required(value)


def _dt_required(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, Mapping):
        return {str(key): _jsonable(nested) for key, nested in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {field: _jsonable(getattr(value, field)) for field in value.__dataclass_fields__}
    return value


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
