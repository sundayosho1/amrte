from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from types import MappingProxyType
from typing import Iterable, Mapping

from amrte.core.identity import deterministic_id
from amrte.core.interfaces import IAuditSink, IClock
from .models import BarState, DataHealth, MarketDataSnapshot, NormalizedBar, SynchronizationStatus

STRUCTURE_ENGINE_VERSION = "1.0"


class StructureHealth(Enum):
    HEALTHY = auto(); DEGRADED = auto(); INSUFFICIENT_HISTORY = auto()
    UNCONFIRMED = auto(); INVALID_INPUT = auto(); UNSYNCHRONIZED = auto(); UNKNOWN = auto()


class SwingType(Enum): SWING_HIGH = auto(); SWING_LOW = auto()
class SwingStatus(Enum): SWING_CANDIDATE = auto(); CONFIRMED_SWING = auto()
class SwingClass(Enum):
    HIGHER_HIGH = auto(); HIGHER_LOW = auto(); LOWER_HIGH = auto(); LOWER_LOW = auto()
    EQUAL_HIGH = auto(); EQUAL_LOW = auto(); UNCLASSIFIED = auto(); UNKNOWN = auto()
class TiePolicy(Enum): FIRST = auto(); LAST = auto(); CLUSTER = auto(); REJECT_AMBIGUOUS = auto()
class StructuralDirection(Enum): BULLISH = auto(); BEARISH = auto(); SIDEWAYS = auto(); MIXED = auto(); UNKNOWN = auto()
class BreakDirection(Enum): BULLISH_BOS = auto(); BEARISH_BOS = auto()
class BreakConfirmation(Enum): WICK_BREAK = auto(); CLOSE_BREAK = auto(); MULTI_CLOSE_CONFIRMATION = auto()
class ShiftDirection(Enum): BULLISH_STRUCTURE_SHIFT = auto(); BEARISH_STRUCTURE_SHIFT = auto()
class ShiftStatus(Enum): PROVISIONAL_SHIFT = auto(); CONFIRMED_SHIFT = auto(); INVALIDATED_SHIFT = auto()
class ConsolidationState(Enum): CONSOLIDATING = auto(); NOT_CONSOLIDATING = auto(); UNKNOWN = auto()
class ZoneType(Enum): SUPPORT = auto(); RESISTANCE = auto(); DUAL_ROLE = auto(); UNKNOWN = auto()
class ZoneState(Enum): ACTIVE = auto(); TESTED = auto(); WEAKENED = auto(); BROKEN = auto(); ROLE_FLIPPED = auto(); EXPIRED = auto(); INVALID = auto(); UNKNOWN = auto()
class Alignment(Enum):
    FULL_BULLISH_ALIGNMENT = auto(); FULL_BEARISH_ALIGNMENT = auto()
    PARTIAL_BULLISH_ALIGNMENT = auto(); PARTIAL_BEARISH_ALIGNMENT = auto()
    CONFLICTING = auto(); NEUTRAL = auto(); UNKNOWN = auto()


@dataclass(frozen=True)
class StructureConfiguration:
    left_bars: int = 2
    right_bars: int = 2
    tie_policy: TiePolicy = TiePolicy.FIRST
    equality_tolerance: float = 0.001
    minimum_structural_evidence: int = 2
    direction_lookback: int = 6
    break_confirmation: BreakConfirmation = BreakConfirmation.CLOSE_BREAK
    minimum_penetration: float = 0.0
    break_confirmation_bars: int = 1
    consolidation_window: int = 8
    consolidation_entry_threshold: float = 0.03
    consolidation_exit_threshold: float = 0.05
    zone_width_percentage: float = 0.002
    zone_merge_threshold: float = 0.001
    zone_expiration_bars: int = 100
    maximum_active_zones: int = 20
    maximum_swings: int = 200
    alignment_weights: tuple[float, float, float] = (0.5, 0.3, 0.2)
    strict: bool = True

    def validate(self) -> tuple[str, ...]:
        errors = []
        if self.left_bars < 1: errors.append("left_bars must be >= 1")
        if self.right_bars < 1: errors.append("right_bars must be >= 1")
        if self.equality_tolerance < 0: errors.append("equality_tolerance must be non-negative")
        if self.minimum_structural_evidence < 1: errors.append("minimum evidence must be positive")
        if self.minimum_penetration < 0: errors.append("minimum penetration must be non-negative")
        if self.break_confirmation_bars < 1: errors.append("confirmation bars must be positive")
        if self.consolidation_window < 2: errors.append("consolidation window must be >= 2")
        if self.consolidation_entry_threshold < 0 or self.consolidation_exit_threshold < self.consolidation_entry_threshold:
            errors.append("consolidation hysteresis is invalid")
        if self.zone_width_percentage < 0 or self.zone_merge_threshold < 0: errors.append("zone distances must be non-negative")
        if self.maximum_active_zones < 1 or self.maximum_swings < 2: errors.append("history limits must be positive")
        if len(self.alignment_weights) != 3 or any(weight < 0 for weight in self.alignment_weights) or sum(self.alignment_weights) <= 0:
            errors.append("alignment weights are invalid")
        return tuple(errors)


@dataclass(frozen=True)
class ConfidenceResult:
    score: float
    components: Mapping[str, float]
    warnings: tuple[str, ...]
    evidence_count: int
    health_constraint: StructureHealth
    def __post_init__(self): object.__setattr__(self, "components", MappingProxyType(dict(self.components)))


@dataclass(frozen=True)
class StructuralSwing:
    swing_id: str; instrument_id: str; timeframe: str; swing_type: SwingType
    price: float; bar_id: str; bar_open_time: datetime; candidate_at: datetime
    confirmed_at: datetime | None; confirmation_bar_id: str | None
    relative_classification: SwingClass; status: SwingStatus; strength: float
    confidence: float; dataset_id: str; market_data_snapshot_id: str


@dataclass(frozen=True)
class StructuralBreak:
    break_id: str; instrument_id: str; timeframe: str; direction: BreakDirection
    reference_swing_id: str; reference_level: float; break_bar_id: str
    break_timestamp: datetime; break_price: float; penetration: float
    confirmation_type: BreakConfirmation; confirmation_status: bool
    displacement_measure: float; confidence: float; dataset_id: str
    market_data_snapshot_id: str


@dataclass(frozen=True)
class StructuralShift:
    shift_id: str; instrument_id: str; timeframe: str
    prior_direction: StructuralDirection; potential_new_direction: ShiftDirection
    trigger_break_id: str; status: ShiftStatus; detected_at: datetime
    confidence: float; evidence: tuple[str, ...]; dataset_id: str
    market_data_snapshot_id: str


@dataclass(frozen=True)
class ConsolidationResult:
    state: ConsolidationState; lower_boundary: float | None; upper_boundary: float | None
    width: float | None; created_at: datetime | None; last_updated_at: datetime | None
    confidence: float; evidence: tuple[str, ...]


@dataclass(frozen=True)
class StructuralZone:
    zone_id: str; instrument_id: str; timeframe: str; zone_type: ZoneType
    lower_bound: float; upper_bound: float; created_at: datetime; confirmed_at: datetime
    last_tested_at: datetime | None; test_count: int; state: ZoneState
    strength: float; confidence: float; source_swing_ids: tuple[str, ...]
    source_break_ids: tuple[str, ...]; dataset_id: str


@dataclass(frozen=True)
class TimeframeStructure:
    timeframe: str; as_of_timestamp: datetime; data_health: DataHealth
    structure_health: StructureHealth; direction: StructuralDirection
    swings: tuple[StructuralSwing, ...]; breaks: tuple[StructuralBreak, ...]
    shifts: tuple[StructuralShift, ...]; consolidation: ConsolidationResult
    zones: tuple[StructuralZone, ...]; confidence: ConfidenceResult
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class StructureSnapshot:
    structure_snapshot_id: str; created_at: datetime; as_of_timestamp: datetime
    experiment_id: str; dataset_id: str; dataset_fingerprint: str; instrument_id: str
    source_market_data_snapshot_id: str; context_structure: TimeframeStructure
    strategy_structure: TimeframeStructure; execution_structure: TimeframeStructure
    alignment: Alignment; alignment_confidence: float
    overall_structure_health: StructureHealth; overall_confidence: ConfidenceResult
    evidence: tuple[str, ...]; configuration_snapshot_id: str; recovery_epoch: int


def _equal(a: float, b: float, tolerance: float) -> bool:
    scale = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / scale <= tolerance


class MarketStructureEngine:
    def __init__(self, clock: IClock, audit: IAuditSink,
                 configuration: StructureConfiguration = StructureConfiguration()):
        errors = configuration.validate()
        if errors: raise ValueError("; ".join(errors))
        self.clock = clock; self.audit = audit; self.configuration = configuration
        self._cache: dict[tuple[str, str, str], StructureSnapshot] = {}
        self._last_processed: dict[tuple[str, str], str] = {}
        self._emitted_breaks: set[str] = set()

    def swing_candidates(self, bars: tuple[NormalizedBar, ...], *, dataset_id: str,
                         snapshot_id: str) -> tuple[StructuralSwing, ...]:
        cfg = self.configuration; results = []
        for index in range(cfg.left_bars, len(bars)):
            center = bars[index]; left = bars[index-cfg.left_bars:index]
            right = bars[index+1:index+1+cfg.right_bars]
            high = all(center.high >= item.high for item in left) and all(center.high >= item.high for item in right)
            low = all(center.low <= item.low for item in left) and all(center.low <= item.low for item in right)
            if not high and not low: continue
            if high and low and cfg.tie_policy is TiePolicy.REJECT_AMBIGUOUS: continue
            types = (SwingType.SWING_HIGH, SwingType.SWING_LOW) if high and low else ((SwingType.SWING_HIGH,) if high else (SwingType.SWING_LOW,))
            confirmed = len(right) == cfg.right_bars
            confirmation = right[-1] if confirmed else None
            for kind in types:
                price = center.high if kind is SwingType.SWING_HIGH else center.low
                identity = deterministic_id("swing", dataset_id, center.instrument_id,
                                            center.timeframe, center.bar_id, kind.name)
                results.append(StructuralSwing(identity, center.instrument_id, center.timeframe,
                    kind, price, center.bar_id, center.open_time, center.close_time or center.open_time,
                    confirmation.close_time if confirmation else None,
                    confirmation.bar_id if confirmation else None, SwingClass.UNCLASSIFIED,
                    SwingStatus.CONFIRMED_SWING if confirmed else SwingStatus.SWING_CANDIDATE,
                    1.0, 100.0 if confirmed else 40.0, dataset_id, snapshot_id))
        # Resolve same-price plateaus explicitly so input iteration order is not
        # an accidental tie policy. CLUSTER retains deterministic endpoint
        # lineage; FIRST/LAST select exactly one representative.
        grouped: list[list[StructuralSwing]] = []
        for item in results:
            if grouped and grouped[-1][-1].swing_type is item.swing_type and _equal(grouped[-1][-1].price, item.price, cfg.equality_tolerance):
                grouped[-1].append(item)
            else: grouped.append([item])
        resolved: list[StructuralSwing] = []
        for group in grouped:
            if len(group) == 1 or cfg.tie_policy is TiePolicy.CLUSTER: resolved.extend(group)
            elif cfg.tie_policy is TiePolicy.FIRST: resolved.append(group[0])
            elif cfg.tie_policy is TiePolicy.LAST: resolved.append(group[-1])
            # REJECT_AMBIGUOUS intentionally contributes nothing.
        return tuple(resolved[-cfg.maximum_swings:])

    def classify_swings(self, swings: Iterable[StructuralSwing]) -> tuple[StructuralSwing, ...]:
        result = []; previous: dict[SwingType, StructuralSwing] = {}
        from dataclasses import replace
        for swing in swings:
            classification = SwingClass.UNCLASSIFIED
            prior = previous.get(swing.swing_type)
            if prior is not None:
                if _equal(swing.price, prior.price, self.configuration.equality_tolerance):
                    classification = SwingClass.EQUAL_HIGH if swing.swing_type is SwingType.SWING_HIGH else SwingClass.EQUAL_LOW
                elif swing.swing_type is SwingType.SWING_HIGH:
                    classification = SwingClass.HIGHER_HIGH if swing.price > prior.price else SwingClass.LOWER_HIGH
                else:
                    classification = SwingClass.HIGHER_LOW if swing.price > prior.price else SwingClass.LOWER_LOW
            updated = replace(swing, relative_classification=classification)
            result.append(updated)
            if swing.status is SwingStatus.CONFIRMED_SWING: previous[swing.swing_type] = updated
        return tuple(result)

    def direction(self, swings: tuple[StructuralSwing, ...]) -> tuple[StructuralDirection, tuple[str, ...]]:
        confirmed = [item for item in swings if item.status is SwingStatus.CONFIRMED_SWING][-self.configuration.direction_lookback:]
        bullish = sum(item.relative_classification in (SwingClass.HIGHER_HIGH, SwingClass.HIGHER_LOW) for item in confirmed)
        bearish = sum(item.relative_classification in (SwingClass.LOWER_HIGH, SwingClass.LOWER_LOW) for item in confirmed)
        equal = sum(item.relative_classification in (SwingClass.EQUAL_HIGH, SwingClass.EQUAL_LOW) for item in confirmed)
        minimum = self.configuration.minimum_structural_evidence
        if bullish >= minimum and bearish == 0: return StructuralDirection.BULLISH, ("BULLISH_SWING_SEQUENCE",)
        if bearish >= minimum and bullish == 0: return StructuralDirection.BEARISH, ("BEARISH_SWING_SEQUENCE",)
        if bullish and bearish: return StructuralDirection.MIXED, ("CONFLICTING_SWING_SEQUENCE",)
        if equal >= minimum: return StructuralDirection.SIDEWAYS, ("REPEATED_EQUAL_STRUCTURE",)
        return StructuralDirection.UNKNOWN, ("INSUFFICIENT_SWINGS",)

    def breaks(self, bars: tuple[NormalizedBar, ...], swings: tuple[StructuralSwing, ...],
               snapshot: MarketDataSnapshot) -> tuple[StructuralBreak, ...]:
        results = []
        confirmed = [item for item in swings if item.status is SwingStatus.CONFIRMED_SWING]
        for reference in confirmed:
            start = next((i for i, bar in enumerate(bars) if bar.open_time >= (reference.confirmed_at or reference.bar_open_time)), len(bars))
            consecutive = 0
            for bar in bars[start:]:
                observed = bar.high if (reference.swing_type is SwingType.SWING_HIGH and self.configuration.break_confirmation is BreakConfirmation.WICK_BREAK) else (bar.low if self.configuration.break_confirmation is BreakConfirmation.WICK_BREAK else bar.close)
                penetration = observed - reference.price if reference.swing_type is SwingType.SWING_HIGH else reference.price - observed
                if penetration > self.configuration.minimum_penetration:
                    consecutive += 1
                    if consecutive < (self.configuration.break_confirmation_bars if self.configuration.break_confirmation is BreakConfirmation.MULTI_CLOSE_CONFIRMATION else 1): continue
                    direction = BreakDirection.BULLISH_BOS if reference.swing_type is SwingType.SWING_HIGH else BreakDirection.BEARISH_BOS
                    identity = deterministic_id("bos", snapshot.dataset_id, reference.swing_id, bar.bar_id,
                                                self.configuration.break_confirmation.name)
                    results.append(StructuralBreak(identity, bar.instrument_id, bar.timeframe, direction,
                        reference.swing_id, reference.price, bar.bar_id, bar.close_time or bar.open_time,
                        observed, penetration, self.configuration.break_confirmation, True,
                        penetration / max(reference.price, 1e-12), 80.0, snapshot.dataset_id, snapshot.snapshot_id))
                    break
                consecutive = 0
        unique = {item.break_id: item for item in results}
        return tuple(unique.values())

    def shifts(self, direction: StructuralDirection, breaks: tuple[StructuralBreak, ...],
               snapshot: MarketDataSnapshot) -> tuple[StructuralShift, ...]:
        results = []
        for event in breaks:
            opposing = ((direction is StructuralDirection.BEARISH and event.direction is BreakDirection.BULLISH_BOS) or
                        (direction is StructuralDirection.BULLISH and event.direction is BreakDirection.BEARISH_BOS))
            if not opposing: continue
            new = ShiftDirection.BULLISH_STRUCTURE_SHIFT if event.direction is BreakDirection.BULLISH_BOS else ShiftDirection.BEARISH_STRUCTURE_SHIFT
            identity = deterministic_id("shift", event.break_id, direction.name, new.name)
            results.append(StructuralShift(identity, event.instrument_id, event.timeframe, direction, new,
                event.break_id, ShiftStatus.CONFIRMED_SHIFT, event.break_timestamp, event.confidence,
                ("OPPOSING_CONFIRMED_BOS",), snapshot.dataset_id, snapshot.snapshot_id))
        return tuple(results)

    def consolidation(self, bars: tuple[NormalizedBar, ...]) -> ConsolidationResult:
        window = bars[-self.configuration.consolidation_window:]
        if len(window) < self.configuration.consolidation_window:
            return ConsolidationResult(ConsolidationState.UNKNOWN, None, None, None, None, None, 0.0, ("INSUFFICIENT_BARS",))
        upper = max(item.high for item in window); lower = min(item.low for item in window)
        width = (upper - lower) / max(lower, 1e-12)
        previously_consolidating = False
        if len(bars) > self.configuration.consolidation_window:
            prior = bars[-self.configuration.consolidation_window-1:-1]
            prior_upper = max(item.high for item in prior); prior_lower = min(item.low for item in prior)
            prior_width = (prior_upper-prior_lower)/max(prior_lower, 1e-12)
            previously_consolidating = prior_width <= self.configuration.consolidation_entry_threshold
        threshold = (self.configuration.consolidation_exit_threshold if previously_consolidating
                     else self.configuration.consolidation_entry_threshold)
        state = ConsolidationState.CONSOLIDATING if width <= threshold else ConsolidationState.NOT_CONSOLIDATING
        confidence = max(0.0, min(100.0, (1 - width / max(self.configuration.consolidation_exit_threshold, 1e-12)) * 100)) if state is ConsolidationState.CONSOLIDATING else 100.0
        return ConsolidationResult(state, lower, upper, upper-lower, window[0].open_time,
                                   window[-1].close_time or window[-1].open_time, confidence,
                                   ("BOUNDED_BAR_WINDOW",))

    def zones(self, swings: tuple[StructuralSwing, ...], bars: tuple[NormalizedBar, ...],
              dataset_id: str) -> tuple[StructuralZone, ...]:
        zones = []
        confirmed = [item for item in swings if item.status is SwingStatus.CONFIRMED_SWING]
        for swing in confirmed:
            width = swing.price * self.configuration.zone_width_percentage
            zone_type = ZoneType.RESISTANCE if swing.swing_type is SwingType.SWING_HIGH else ZoneType.SUPPORT
            lower, upper = swing.price-width, swing.price+width
            later = [bar for bar in bars if bar.open_time > swing.bar_open_time]
            tests = [bar for bar in later if bar.high >= lower and bar.low <= upper]
            broken = any((bar.close > upper if zone_type is ZoneType.RESISTANCE else bar.close < lower) for bar in later)
            state = ZoneState.BROKEN if broken else (ZoneState.TESTED if tests else ZoneState.ACTIVE)
            if broken:
                break_index = next((index for index, bar in enumerate(later)
                    if (bar.close > upper if zone_type is ZoneType.RESISTANCE else bar.close < lower)), None)
                after_break = later[break_index+1:] if break_index is not None else []
                retested = any(bar.high >= lower and bar.low <= upper for bar in after_break)
                if retested:
                    state = ZoneState.ROLE_FLIPPED
                    zone_type = ZoneType.SUPPORT if zone_type is ZoneType.RESISTANCE else ZoneType.RESISTANCE
            if later and len(later) > self.configuration.zone_expiration_bars: state = ZoneState.EXPIRED
            identity = deterministic_id("zone", dataset_id, swing.instrument_id, swing.timeframe,
                                        swing.swing_id, lower, upper)
            zones.append(StructuralZone(identity, swing.instrument_id, swing.timeframe, zone_type,
                lower, upper, swing.confirmed_at or swing.candidate_at, swing.confirmed_at or swing.candidate_at,
                (tests[-1].close_time or tests[-1].open_time) if tests else None, len(tests), state,
                min(100.0, 50.0 + len(tests)*10), min(100.0, swing.confidence), (swing.swing_id,), (), dataset_id))
        merged: list[StructuralZone] = []
        from dataclasses import replace
        for zone in zones:
            match = next((old for old in merged if old.zone_type is zone.zone_type and
                         zone.lower_bound <= old.upper_bound*(1+self.configuration.zone_merge_threshold) and
                         zone.upper_bound >= old.lower_bound*(1-self.configuration.zone_merge_threshold)), None)
            if match is None: merged.append(zone); continue
            merged.remove(match)
            sources = tuple(sorted(set(match.source_swing_ids + zone.source_swing_ids)))
            merged_id = deterministic_id("zone", dataset_id, zone.instrument_id, zone.timeframe, *sources)
            merged.append(replace(match, zone_id=merged_id, lower_bound=min(match.lower_bound, zone.lower_bound),
                                  upper_bound=max(match.upper_bound, zone.upper_bound),
                                  test_count=match.test_count+zone.test_count,
                                  source_swing_ids=sources, strength=max(match.strength, zone.strength)))
        active = [zone for zone in merged if zone.state not in (ZoneState.EXPIRED, ZoneState.INVALID)]
        return tuple(active[-self.configuration.maximum_active_zones:])

    def timeframe_structure(self, bars: tuple[NormalizedBar, ...], snapshot: MarketDataSnapshot) -> TimeframeStructure:
        if not bars:
            return self._invalid_timeframe("UNKNOWN", snapshot, StructureHealth.INSUFFICIENT_HISTORY)
        candidates = self.swing_candidates(bars, dataset_id=snapshot.dataset_id, snapshot_id=snapshot.snapshot_id)
        swings = self.classify_swings(candidates); direction, evidence = self.direction(swings)
        breaks = self.breaks(bars, swings, snapshot); shifts = self.shifts(direction, breaks, snapshot)
        consolidation = self.consolidation(bars); zones = self.zones(swings, bars, snapshot.dataset_id)
        confirmed = sum(item.status is SwingStatus.CONFIRMED_SWING for item in swings)
        health = StructureHealth.HEALTHY if confirmed >= self.configuration.minimum_structural_evidence else StructureHealth.INSUFFICIENT_HISTORY
        components = {"swing_sequence": min(100.0, confirmed*20.0),
                      "break_confirmation": min(100.0, len(breaks)*25.0),
                      "zone_evidence": min(100.0, len(zones)*10.0)}
        score = sum(components.values()) / len(components) if health is StructureHealth.HEALTHY else 0.0
        confidence = ConfidenceResult(score, components, () if health is StructureHealth.HEALTHY else ("HEALTH_CONSTRAINED",), confirmed, health)
        return TimeframeStructure(bars[0].timeframe, snapshot.as_of_timestamp, snapshot.data_health,
            health, direction, swings, breaks, shifts, consolidation, zones, confidence,
            tuple(evidence) + tuple(f"CONFIRMED_{item.relative_classification.name}" for item in swings
                                    if item.relative_classification not in (SwingClass.UNCLASSIFIED, SwingClass.UNKNOWN)))

    def alignment(self, structures: tuple[TimeframeStructure, TimeframeStructure, TimeframeStructure]) -> tuple[Alignment, float]:
        if any(item.structure_health not in (StructureHealth.HEALTHY, StructureHealth.DEGRADED) for item in structures): return Alignment.UNKNOWN, 0.0
        directions = tuple(item.direction for item in structures)
        if StructuralDirection.UNKNOWN in directions: return Alignment.UNKNOWN, 0.0
        bulls = sum(item is StructuralDirection.BULLISH for item in directions)
        bears = sum(item is StructuralDirection.BEARISH for item in directions)
        if bulls == 3: state = Alignment.FULL_BULLISH_ALIGNMENT
        elif bears == 3: state = Alignment.FULL_BEARISH_ALIGNMENT
        elif bulls >= 2 and bears == 0: state = Alignment.PARTIAL_BULLISH_ALIGNMENT
        elif bears >= 2 and bulls == 0: state = Alignment.PARTIAL_BEARISH_ALIGNMENT
        elif bulls and bears: state = Alignment.CONFLICTING
        else: state = Alignment.NEUTRAL
        weights = self.configuration.alignment_weights; total = sum(weights)
        confidence = sum(item.confidence.score*weight for item, weight in zip(structures, weights))/total
        return state, confidence

    def analyze(self, snapshot: MarketDataSnapshot, *, configuration_hash: str = "") -> StructureSnapshot | None:
        self.audit.record("structure_analysis_started", {"source_snapshot_id": snapshot.snapshot_id})
        if snapshot.data_health is not DataHealth.HEALTHY:
            self.audit.record("structure_snapshot_rejected", {"reason": "INVALID_STRUCTURE_INPUT"}); return None
        if snapshot.synchronization_status is not SynchronizationStatus.SYNCHRONIZED:
            self.audit.record("structure_snapshot_rejected", {"reason": "UNSYNCHRONIZED"}); return None
        key = (snapshot.snapshot_id, configuration_hash, STRUCTURE_ENGINE_VERSION)
        cached = self._cache.get(key)
        if cached is not None: return cached
        structures = (self.timeframe_structure(snapshot.context_bars, snapshot),
                      self.timeframe_structure(snapshot.strategy_bars, snapshot),
                      self.timeframe_structure(snapshot.execution_bars, snapshot))
        alignment, alignment_confidence = self.alignment(structures)
        health = StructureHealth.HEALTHY if all(item.structure_health is StructureHealth.HEALTHY for item in structures) else StructureHealth.INSUFFICIENT_HISTORY
        components = {"timeframe_agreement": alignment_confidence,
                      "context": structures[0].confidence.score,
                      "strategy": structures[1].confidence.score,
                      "execution": structures[2].confidence.score}
        score = sum(components.values())/len(components) if health is StructureHealth.HEALTHY else 0.0
        confidence = ConfidenceResult(score, components, () if health is StructureHealth.HEALTHY else ("MANDATORY_TIMEFRAME_CONSTRAINT",),
                                      sum(item.confidence.evidence_count for item in structures), health)
        identity = deterministic_id("structure", snapshot.snapshot_id, snapshot.configuration_snapshot_id,
                                    STRUCTURE_ENGINE_VERSION, snapshot.as_of_timestamp.isoformat(), configuration_hash)
        result = StructureSnapshot(identity, self.clock.now(), snapshot.as_of_timestamp,
            snapshot.experiment_id, snapshot.dataset_id, snapshot.dataset_fingerprint,
            snapshot.instrument_id, snapshot.snapshot_id, *structures, alignment,
            alignment_confidence, health, confidence,
            tuple(sorted(set(sum((item.evidence for item in structures), ())))),
            snapshot.configuration_snapshot_id, snapshot.recovery_epoch)
        self._cache[key] = result
        for structure in structures:
            if structure.swings: self._last_processed[(snapshot.instrument_id, structure.timeframe)] = structure.swings[-1].bar_id
            self._emitted_breaks.update(item.break_id for item in structure.breaks)
        self.audit.record("structure_snapshot_created", {"structure_snapshot_id": identity,
                          "source_snapshot_id": snapshot.snapshot_id, "health": health.name})
        return result

    def rebuild(self, snapshot: MarketDataSnapshot, *, configuration_hash: str = "") -> StructureSnapshot | None:
        self.audit.record("structure_rebuild_started", {"source_snapshot_id": snapshot.snapshot_id})
        self._cache.clear(); result = self.analyze(snapshot, configuration_hash=configuration_hash)
        self.audit.record("structure_rebuild_completed", {"success": result is not None})
        return result

    def invalidate_cache(self) -> int:
        count = len(self._cache); self._cache.clear(); return count

    def recovery_state(self) -> Mapping[str, object]:
        return {"structure_schema_version": STRUCTURE_ENGINE_VERSION,
                "last_processed_bar_ids": {f"{key[0]}|{key[1]}": value for key, value in self._last_processed.items()},
                "emitted_break_ids": tuple(sorted(self._emitted_breaks))}

    def readiness(self, snapshot: StructureSnapshot | None) -> tuple[bool, tuple[str, ...]]:
        if snapshot is None: return False, ("structure:NOT_AVAILABLE",)
        if snapshot.overall_structure_health is not StructureHealth.HEALTHY:
            return False, (f"structure:{snapshot.overall_structure_health.name}",)
        return True, ()

    def _invalid_timeframe(self, timeframe: str, snapshot: MarketDataSnapshot,
                           health: StructureHealth) -> TimeframeStructure:
        confidence = ConfidenceResult(0.0, {}, (health.name,), 0, health)
        consolidation = ConsolidationResult(ConsolidationState.UNKNOWN, None, None, None, None, None, 0.0, (health.name,))
        return TimeframeStructure(timeframe, snapshot.as_of_timestamp, snapshot.data_health, health,
                                  StructuralDirection.UNKNOWN, (), (), (), consolidation, (), confidence, (health.name,))
