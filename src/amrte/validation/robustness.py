"""Deterministic robustness validation for neutral offline experiments.

This module is deliberately domain-neutral.  It evaluates timestamped numeric
observations and cannot submit orders, model financial positions, or authorize
participation in any financial or wagering activity.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum, auto
from hashlib import sha256
from random import Random
from statistics import median
from threading import RLock

from amrte.core.identity import deterministic_id
from amrte.core.observability_types import DecisionEvaluation, DecisionOutcome, DecisionStatus, DecisionTrace
from amrte.validation.experiments import NeutralObservation

VERSION = "1.0"
SCHEMA = "1.0"
ZERO = Decimal("0")


class ValidationMode(Enum):
    EXPLORATORY = auto()
    CONFIRMATORY = auto()
    PRE_REGISTERED = auto()


class WindowMode(Enum):
    ROLLING = auto()
    ANCHORED = auto()


class ResamplingMethod(Enum):
    IID = auto()
    BLOCK = auto()
    STRATIFIED = auto()


class ContaminationState(Enum):
    CLEAN = auto()
    POTENTIALLY_CONTAMINATED = auto()
    CONTAMINATED = auto()
    UNKNOWN = auto()


class RobustnessClassification(Enum):
    ROBUST_EVIDENCE = auto()
    MODERATE_EVIDENCE = auto()
    MIXED_EVIDENCE = auto()
    FRAGILE = auto()
    INSUFFICIENT_EVIDENCE = auto()
    CONTAMINATED = auto()
    INVALID = auto()


class EvidenceDirection(Enum):
    SUPPORTING = auto()
    WEAKENING = auto()
    NEUTRAL = auto()
    INVALIDATING = auto()


@dataclass(frozen=True)
class RobustnessConfiguration:
    maximum_windows: int = 128
    maximum_iterations: int = 10000
    maximum_evidence_records: int = 4096
    minimum_sample: int = 5
    minimum_windows: int = 2
    precision: Decimal = Decimal("0.00000001")
    configuration_snapshot_id: str = "NEUTRAL_ROBUSTNESS_DEFAULT"

    def validate(self):
        values = (self.maximum_windows, self.maximum_iterations, self.maximum_evidence_records,
                  self.minimum_sample, self.minimum_windows)
        if min(values) < 1 or not self.precision.is_finite() or self.precision <= ZERO:
            return ("ROBUSTNESS_CONFIGURATION_INVALID",)
        return ()


@dataclass(frozen=True)
class ResearchValidationHandoff:
    experiment_id: str
    dataset_fingerprint: str
    parameter_set_ids: tuple[str, ...]
    replay_fingerprint: str
    sample_count: int
    configuration_snapshot_id: str


@dataclass(frozen=True)
class RobustnessValidationPlan:
    plan_id: str
    handoff: ResearchValidationHandoff
    mode: ValidationMode
    window_mode: WindowMode
    coverage_start_utc: datetime
    coverage_end_utc: datetime
    development_duration: timedelta
    validation_duration: timedelta
    step: timedelta
    embargo: timedelta
    frozen_parameter_set_id: str
    resampling_method: ResamplingMethod
    resampling_iterations: int
    seed: int
    block_size: int
    stress_decrements: tuple[Decimal, ...]
    classification_policy_id: str
    configuration_snapshot_id: str
    registered_at_utc: datetime | None
    plan_fingerprint: str

    @classmethod
    def create(cls, handoff, mode, window_mode, coverage_start_utc, coverage_end_utc,
               development_duration, validation_duration, step, embargo,
               frozen_parameter_set_id, resampling_method, resampling_iterations,
               seed, block_size=1, stress_decrements=(),
               classification_policy_id="NEUTRAL_POLICY_V1",
               configuration_snapshot_id="NEUTRAL_ROBUSTNESS_DEFAULT",
               registered_at_utc=None):
        stresses = tuple(Decimal(str(x)) for x in stress_decrements)
        parts = (handoff.experiment_id, handoff.dataset_fingerprint, mode.name,
                 window_mode.name, coverage_start_utc.isoformat(), coverage_end_utc.isoformat(),
                 str(development_duration), str(validation_duration), str(step), str(embargo),
                 frozen_parameter_set_id, resampling_method.name, resampling_iterations, seed,
                 block_size, *stresses, classification_policy_id, configuration_snapshot_id,
                 registered_at_utc.isoformat() if registered_at_utc else "NONE")
        fingerprint = deterministic_id("robustness_plan_fingerprint", *parts)
        return cls(deterministic_id("robustness_plan", fingerprint), handoff, mode, window_mode,
                   coverage_start_utc, coverage_end_utc, development_duration,
                   validation_duration, step, embargo, frozen_parameter_set_id,
                   resampling_method, resampling_iterations, seed, block_size, stresses,
                   classification_policy_id, configuration_snapshot_id,
                   registered_at_utc, fingerprint)


@dataclass(frozen=True)
class HoldoutSeal:
    seal_id: str
    plan_id: str
    start_utc: datetime
    end_utc: datetime
    sealed_at_utc: datetime
    dataset_fingerprint: str
    seal_fingerprint: str


@dataclass(frozen=True)
class WalkForwardWindow:
    window_id: str
    plan_id: str
    sequence: int
    development_start_utc: datetime
    development_end_utc: datetime
    validation_start_utc: datetime
    validation_end_utc: datetime
    frozen_parameter_set_id: str


@dataclass(frozen=True)
class WindowResult:
    result_id: str
    window_id: str
    development_mean: Decimal
    validation_mean: Decimal
    generalization_gap: Decimal
    development_count: int
    validation_count: int
    contamination: ContaminationState


@dataclass(frozen=True)
class DistributionSummary:
    count: int
    minimum: Decimal
    maximum: Decimal
    mean: Decimal
    median: Decimal
    standard_deviation: Decimal
    lower_tail: Decimal
    upper_tail: Decimal


@dataclass(frozen=True)
class ParameterRobustness:
    center_parameter_id: str
    neighborhood_size: int
    score_range: Decimal
    cliff_detected: bool
    plateau_detected: bool
    isolated_peak: bool


@dataclass(frozen=True)
class RobustnessEvidenceRecord:
    evidence_id: str
    plan_id: str
    evidence_type: str
    direction: EvidenceDirection
    reference_id: str
    reason_code: str
    as_of_utc: datetime


@dataclass(frozen=True)
class ResearchRobustnessProfile:
    profile_id: str
    plan_id: str
    walk_forward_stability: Decimal | None
    resampling_stability: Decimal | None
    stress_stability: Decimal | None
    parameter_stability: Decimal | None
    contamination: ContaminationState
    classification: RobustnessClassification
    reason_codes: tuple[str, ...]
    as_of_utc: datetime


@dataclass(frozen=True)
class RobustnessValidationResult:
    result_id: str
    plan_id: str
    window_result_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    profile_id: str
    distribution: DistributionSummary | None
    replay_fingerprint: str
    completed_at_utc: datetime


@dataclass(frozen=True)
class RobustnessRecovery:
    schema_version: str
    engine_version: str
    configuration_snapshot_id: str
    recovery_epoch: int
    plans: tuple[RobustnessValidationPlan, ...]
    observations: tuple[NeutralObservation, ...]
    seals: tuple[HoldoutSeal, ...]
    windows: tuple[WalkForwardWindow, ...]
    window_results: tuple[WindowResult, ...]
    evidence: tuple[RobustnessEvidenceRecord, ...]
    profiles: tuple[ResearchRobustnessProfile, ...]
    results: tuple[RobustnessValidationResult, ...]


class DeterministicRobustnessEngine:
    def __init__(self, configuration=RobustnessConfiguration(), audit=None):
        errors = configuration.validate()
        if errors:
            raise ValueError(";".join(errors))
        self.configuration = configuration
        self.audit = audit
        self._lock = RLock()
        self.plans = OrderedDict()
        self.observations = OrderedDict()
        self.seals = OrderedDict()
        self.windows = OrderedDict()
        self.window_results = OrderedDict()
        self.evidence = OrderedDict()
        self.profiles = OrderedDict()
        self.results = OrderedDict()
        self.holdout_uses = defaultdict(int)
        self.recovery_restricted = False

    def register(self, plan, observations):
        with self._lock:
            if plan.plan_id in self.plans:
                return False, ("ROBUSTNESS_PLAN_DUPLICATE",)
            reasons = self._validate(plan, observations)
            if reasons:
                return False, reasons
            self.plans[plan.plan_id] = plan
            for item in sorted(observations, key=lambda x: (x.known_at_utc, x.observation_id)):
                self.observations[item.observation_id] = item
            self._audit("robustness_plan_created", {"plan_id": plan.plan_id})
            return True, ("ROBUSTNESS_PLAN_ACCEPTED",)

    def seal_holdout(self, plan_id, start_utc, end_utc, sealed_at_utc):
        with self._lock:
            plan = self.plans[plan_id]
            if start_utc <= plan.coverage_start_utc or end_utc > plan.coverage_end_utc or start_utc >= end_utc:
                raise ValueError("ROBUSTNESS_HOLDOUT_INVALID")
            fingerprint = deterministic_id("holdout_seal", plan_id, plan.handoff.dataset_fingerprint,
                                           start_utc.isoformat(), end_utc.isoformat(), sealed_at_utc.isoformat())
            seal = HoldoutSeal(deterministic_id("holdout_seal_id", fingerprint), plan_id, start_utc,
                               end_utc, sealed_at_utc, plan.handoff.dataset_fingerprint, fingerprint)
            self.seals[seal.seal_id] = seal
            self._audit("holdout_sealed", {"seal_id": seal.seal_id})
            return seal

    def generate_windows(self, plan_id):
        with self._lock:
            plan = self.plans[plan_id]
            generated = []
            cursor = plan.coverage_start_utc
            sequence = 1
            while True:
                development_start = plan.coverage_start_utc if plan.window_mode is WindowMode.ANCHORED else cursor
                development_end = cursor + plan.development_duration
                validation_start = development_end + plan.embargo
                validation_end = validation_start + plan.validation_duration
                if validation_end > plan.coverage_end_utc:
                    break
                if len(generated) >= self.configuration.maximum_windows:
                    raise ValueError("ROBUSTNESS_WINDOW_BOUND")
                wid = deterministic_id("walk_forward_window", plan_id, sequence,
                                       development_start.isoformat(), development_end.isoformat(),
                                       validation_start.isoformat(), validation_end.isoformat(),
                                       plan.frozen_parameter_set_id)
                window = WalkForwardWindow(wid, plan_id, sequence, development_start, development_end,
                                           validation_start, validation_end, plan.frozen_parameter_set_id)
                self.windows.setdefault(wid, window)
                generated.append(self.windows[wid])
                cursor += plan.step
                sequence += 1
            return tuple(generated)

    def run(self, plan_id, at):
        with self._lock:
            existing = next((x for x in self.results.values()
                             if x.plan_id == plan_id and x.completed_at_utc == at), None)
            if existing:
                return existing
            plan = self.plans[plan_id]
            windows = self.generate_windows(plan_id)
            results = []
            validation_values = []
            contamination = ContaminationState.CLEAN
            applicable_seals = [x for x in self.seals.values() if x.plan_id == plan_id]
            prior_holdout_uses = {x.seal_id: self.holdout_uses[x.seal_id] for x in applicable_seals}
            for window in windows:
                development = self._values(plan, window.development_start_utc, window.development_end_utc)
                validation = self._values(plan, window.validation_start_utc, window.validation_end_utc)
                state = self._contamination(plan, window, prior_holdout_uses)
                if self._contamination_rank(state) > self._contamination_rank(contamination):
                    contamination = state
                if not development or not validation:
                    self._evidence(plan_id, "WALK_FORWARD_WINDOW", EvidenceDirection.WEAKENING,
                                   window.window_id, "ROBUSTNESS_WINDOW_INSUFFICIENT", at)
                    continue
                dm, vm = self._mean(development), self._mean(validation)
                gap = self._q(vm - dm)
                rid = deterministic_id("window_result", window.window_id, dm, vm, gap, state.name)
                result = WindowResult(rid, window.window_id, dm, vm, gap, len(development),
                                      len(validation), state)
                self.window_results.setdefault(rid, result)
                results.append(result)
                validation_values.extend(validation)
                direction = EvidenceDirection.SUPPORTING if abs(gap) <= Decimal("0.25") else EvidenceDirection.WEAKENING
                self._evidence(plan_id, "WALK_FORWARD_WINDOW", direction, rid,
                               "ROBUSTNESS_WINDOW_STABLE" if direction is EvidenceDirection.SUPPORTING else "ROBUSTNESS_WINDOW_GAP", at)
            distribution = self.resample(plan_id, validation_values) if validation_values else None
            stress_stability = self._stress(plan, validation_values, at)
            parameter = self.parameter_robustness(plan.handoff.parameter_set_ids, validation_values)
            profile = self._profile(plan, results, distribution, stress_stability, parameter, contamination, at)
            replay = self.replay_fingerprint(plan_id, results, distribution, profile)
            result_id = deterministic_id("robustness_result", plan_id, profile.profile_id, replay)
            final = RobustnessValidationResult(result_id, plan_id, tuple(x.result_id for x in results),
                                               tuple(x.evidence_id for x in self.evidence.values() if x.plan_id == plan_id),
                                               profile.profile_id, distribution, replay, at)
            self.results.setdefault(result_id, final)
            for seal in applicable_seals:
                self.holdout_uses[seal.seal_id] += 1
            self._audit("robustness_classified", {"plan_id": plan_id, "classification": profile.classification.name})
            return self.results[result_id]

    def resample(self, plan_id, values):
        plan = self.plans[plan_id]
        values = tuple(Decimal(str(x)) for x in values)
        if len(values) < self.configuration.minimum_sample:
            return None
        rng = Random(plan.seed)
        means = []
        strata = defaultdict(list)
        if plan.resampling_method is ResamplingMethod.STRATIFIED:
            for index, value in enumerate(values):
                strata[index % 2].append(value)
        for _ in range(plan.resampling_iterations):
            if plan.resampling_method is ResamplingMethod.IID:
                sample = [values[rng.randrange(len(values))] for _ in values]
            elif plan.resampling_method is ResamplingMethod.BLOCK:
                sample = []
                while len(sample) < len(values):
                    start = rng.randrange(len(values))
                    sample.extend(values[(start + offset) % len(values)] for offset in range(plan.block_size))
                sample = sample[:len(values)]
            else:
                sample = []
                for key in sorted(strata):
                    group = strata[key]
                    sample.extend(group[rng.randrange(len(group))] for _ in group)
            means.append(self._mean(sample))
        return self._distribution(means)

    def stress(self, values, decrement):
        decrement = Decimal(str(decrement))
        if not decrement.is_finite() or decrement < ZERO:
            raise ValueError("ROBUSTNESS_STRESS_INVALID")
        return tuple(self._q(Decimal(str(value)) - decrement) for value in values)

    def parameter_robustness(self, parameter_ids, values):
        if not parameter_ids or not values:
            return ParameterRobustness("NONE", 0, ZERO, False, False, False)
        ordered = tuple(Decimal(str(x)) for x in values)
        span = self._q(max(ordered) - min(ordered))
        cliff = span > Decimal("1")
        plateau = span <= Decimal("0.25") and len(parameter_ids) >= 2
        isolated = len(parameter_ids) >= 3 and not plateau and cliff
        return ParameterRobustness(parameter_ids[0], len(parameter_ids), span, cliff, plateau, isolated)

    def reconcile(self, plan_id):
        if plan_id not in self.plans:
            return False, ("ROBUSTNESS_PLAN_MISSING",)
        windows = [x for x in self.windows.values() if x.plan_id == plan_id]
        if len({x.window_id for x in windows}) != len(windows):
            return False, ("ROBUSTNESS_DUPLICATE_WINDOW",)
        for item in windows:
            if item.development_end_utc > item.validation_start_utc:
                return False, ("ROBUSTNESS_WINDOW_OVERLAP",)
        if any(x.plan_id != plan_id for x in self.evidence.values() if x.evidence_id in {y for r in self.results.values() if r.plan_id == plan_id for y in r.evidence_ids}):
            return False, ("ROBUSTNESS_ORPHAN_EVIDENCE",)
        return True, ()

    def recovery_state(self, epoch):
        return RobustnessRecovery(SCHEMA, VERSION, self.configuration.configuration_snapshot_id, epoch,
                                  tuple(self.plans.values()), tuple(self.observations.values()),
                                  tuple(self.seals.values()), tuple(self.windows.values()),
                                  tuple(self.window_results.values()), tuple(self.evidence.values()),
                                  tuple(self.profiles.values()), tuple(self.results.values()))

    def restore(self, state, epoch):
        with self._lock:
            if (state.schema_version, state.engine_version, state.configuration_snapshot_id, state.recovery_epoch) != (
                    SCHEMA, VERSION, self.configuration.configuration_snapshot_id, epoch):
                self.recovery_restricted = True
                return False
            try:
                collections = ((x.plan_id for x in state.plans), (x.observation_id for x in state.observations),
                               (x.seal_id for x in state.seals), (x.window_id for x in state.windows),
                               (x.result_id for x in state.window_results), (x.evidence_id for x in state.evidence),
                               (x.profile_id for x in state.profiles), (x.result_id for x in state.results))
                if any(len(items := list(group)) != len(set(items)) for group in collections):
                    raise ValueError
                self.plans = OrderedDict((x.plan_id, x) for x in state.plans)
                self.observations = OrderedDict((x.observation_id, x) for x in state.observations)
                self.seals = OrderedDict((x.seal_id, x) for x in state.seals)
                self.windows = OrderedDict((x.window_id, x) for x in state.windows)
                self.window_results = OrderedDict((x.result_id, x) for x in state.window_results)
                self.evidence = OrderedDict((x.evidence_id, x) for x in state.evidence)
                self.profiles = OrderedDict((x.profile_id, x) for x in state.profiles)
                self.results = OrderedDict((x.result_id, x) for x in state.results)
                if any(not self.reconcile(plan_id)[0] for plan_id in self.plans):
                    raise ValueError
                self.recovery_restricted = False
                return True
            except Exception:
                self.recovery_restricted = True
                return False

    def replay_fingerprint(self, plan_id, results=None, distribution=None, profile=None):
        results = results if results is not None else [x for x in self.window_results.values() if self.windows[x.window_id].plan_id == plan_id]
        profile = profile or next((x for x in reversed(tuple(self.profiles.values())) if x.plan_id == plan_id), None)
        distribution = distribution or next((x.distribution for x in reversed(tuple(self.results.values())) if x.plan_id == plan_id), None)
        return deterministic_id("robustness_replay", plan_id, *[x.result_id for x in results],
                               repr(distribution), profile.profile_id if profile else "NONE")

    def trace(self, result_id, at):
        result = self.results[result_id]
        profile = self.profiles[result.profile_id]
        evaluation = DecisionEvaluation("NEUTRAL_ROBUSTNESS", DecisionStatus.PASSED,
                                        f"ROBUSTNESS_{profile.classification.name}",
                                        "Neutral offline robustness validation", result.evidence_ids)
        trace_id = deterministic_id("robustness_trace", result_id, profile.classification.name)
        return DecisionTrace(trace_id, result_id, result.completed_at_utc, (evaluation,),
                             DecisionOutcome.ACCEPTED if profile.classification not in (
                                 RobustnessClassification.INVALID, RobustnessClassification.CONTAMINATED)
                             else DecisionOutcome.NO_ACTION,
                             f"ROBUSTNESS_{profile.classification.name}", at, None)

    def _validate(self, plan, observations):
        reasons = []
        if plan.configuration_snapshot_id != self.configuration.configuration_snapshot_id:
            reasons.append("ROBUSTNESS_CONFIGURATION_MISMATCH")
        if not plan.handoff.experiment_id or not plan.handoff.replay_fingerprint or not plan.handoff.dataset_fingerprint:
            reasons.append("ROBUSTNESS_HANDOFF_INVALID")
        durations = (plan.development_duration, plan.validation_duration, plan.step)
        if plan.coverage_start_utc >= plan.coverage_end_utc or any(x <= timedelta(0) for x in durations) or plan.embargo < timedelta(0):
            reasons.append("ROBUSTNESS_WINDOW_POLICY_INVALID")
        if plan.resampling_iterations < 1 or plan.resampling_iterations > self.configuration.maximum_iterations:
            reasons.append("ROBUSTNESS_ITERATION_BOUND")
        if plan.block_size < 1 or any(not x.is_finite() or x < ZERO for x in plan.stress_decrements):
            reasons.append("ROBUSTNESS_POLICY_INVALID")
        if plan.mode is ValidationMode.PRE_REGISTERED and (plan.registered_at_utc is None or plan.registered_at_utc > plan.coverage_start_utc):
            reasons.append("ROBUSTNESS_PREREGISTRATION_INVALID")
        for item in observations:
            if (item.dataset_fingerprint != plan.handoff.dataset_fingerprint or not item.input_value.is_finite()
                    or item.observed_at_utc > item.known_at_utc or item.known_at_utc > plan.coverage_end_utc):
                reasons.append("ROBUSTNESS_OBSERVATION_INVALID")
                break
        return tuple(sorted(set(reasons)))

    def _values(self, plan, start, end):
        return [x.input_value for x in self.observations.values()
                if x.dataset_fingerprint == plan.handoff.dataset_fingerprint
                and start <= x.observed_at_utc < end and x.known_at_utc <= end]

    def _contamination(self, plan, window, prior_uses):
        matching = [x for x in self.seals.values() if x.plan_id == plan.plan_id
                    and x.start_utc <= window.validation_start_utc and x.end_utc >= window.validation_end_utc]
        if not matching:
            return ContaminationState.UNKNOWN
        seal = matching[0]
        if seal.sealed_at_utc > window.validation_start_utc:
            return ContaminationState.CONTAMINATED
        return ContaminationState.CLEAN if prior_uses.get(seal.seal_id, 0) == 0 else ContaminationState.POTENTIALLY_CONTAMINATED

    @staticmethod
    def _contamination_rank(state):
        return {ContaminationState.CLEAN: 0, ContaminationState.UNKNOWN: 1,
                ContaminationState.POTENTIALLY_CONTAMINATED: 2,
                ContaminationState.CONTAMINATED: 3}[state]

    def _distribution(self, values):
        ordered = sorted(values)
        count = len(ordered)
        mean_value = self._mean(ordered)
        variance = sum(((x - mean_value) ** 2 for x in ordered), ZERO) / Decimal(count)
        std = self._q(variance.sqrt())
        percentile = lambda p: ordered[min(count - 1, max(0, int((count - 1) * p)))]
        return DistributionSummary(count, ordered[0], ordered[-1], mean_value,
                                   self._q(Decimal(str(median(ordered)))), std,
                                   percentile(.05), percentile(.95))

    def _stress(self, plan, values, at):
        if not values:
            return None
        baseline = self._mean(values)
        stable = 0
        for decrement in plan.stress_decrements:
            stressed = self._mean(self.stress(values, decrement))
            if stressed <= baseline:
                stable += 1
            self._evidence(plan.plan_id, "QUALITY_STRESS", EvidenceDirection.NEUTRAL,
                           deterministic_id("stress", plan.plan_id, decrement), "ROBUSTNESS_STRESS_APPLIED", at)
        return self._q(Decimal(stable) / Decimal(len(plan.stress_decrements))) if plan.stress_decrements else Decimal("1")

    def _profile(self, plan, results, distribution, stress_stability, parameter, contamination, at):
        reasons = []
        if contamination is ContaminationState.CONTAMINATED:
            classification = RobustnessClassification.CONTAMINATED
            reasons.append("ROBUSTNESS_HOLDOUT_CONTAMINATED")
        elif len(results) < self.configuration.minimum_windows:
            classification = RobustnessClassification.INSUFFICIENT_EVIDENCE
            reasons.append("ROBUSTNESS_INSUFFICIENT_WINDOWS")
        elif parameter.cliff_detected:
            classification = RobustnessClassification.FRAGILE
            reasons.append("ROBUSTNESS_PARAMETER_CLIFF")
        else:
            stable = sum(1 for x in results if abs(x.generalization_gap) <= Decimal("0.25"))
            ratio = Decimal(stable) / Decimal(len(results))
            classification = (RobustnessClassification.ROBUST_EVIDENCE if ratio == Decimal("1")
                              else RobustnessClassification.MODERATE_EVIDENCE if ratio >= Decimal("0.5")
                              else RobustnessClassification.MIXED_EVIDENCE)
            reasons.append(f"ROBUSTNESS_{classification.name}")
        wf = self._q(Decimal(sum(1 for x in results if abs(x.generalization_gap) <= Decimal("0.25"))) / Decimal(len(results))) if results else None
        rs = self._q(Decimal("1") / (Decimal("1") + distribution.standard_deviation)) if distribution else None
        ps = self._q(Decimal("1") / (Decimal("1") + parameter.score_range)) if parameter.neighborhood_size else None
        pid = deterministic_id("robustness_profile", plan.plan_id, repr(wf), repr(rs), repr(stress_stability), repr(ps), contamination.name, classification.name, *reasons)
        profile = ResearchRobustnessProfile(pid, plan.plan_id, wf, rs, stress_stability, ps,
                                            contamination, classification, tuple(reasons), at)
        self.profiles.setdefault(pid, profile)
        return self.profiles[pid]

    def _evidence(self, plan_id, evidence_type, direction, reference_id, reason, at):
        eid = deterministic_id("robustness_evidence", plan_id, evidence_type, direction.name, reference_id, reason)
        self.evidence.setdefault(eid, RobustnessEvidenceRecord(eid, plan_id, evidence_type,
                                                               direction, reference_id, reason, at))
        while len(self.evidence) > self.configuration.maximum_evidence_records:
            self.evidence.popitem(last=False)

    def _mean(self, values):
        return self._q(sum(values, ZERO) / Decimal(len(values)))

    def _q(self, value):
        return Decimal(value).quantize(self.configuration.precision)

    def _audit(self, event, payload):
        if self.audit:
            self.audit.record(event, payload)
