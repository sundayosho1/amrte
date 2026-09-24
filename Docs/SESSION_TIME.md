# Session, Calendar, and Market-Time Intelligence

Prompt 9 centralizes temporal interpretation in `TimeZoneService` and
`SessionEngine`. UTC-aware instants are canonical. Data-source, reference,
session-local, and research-clock representations remain explicit and are
never silently interchanged.

## Timezone and DST policy

Named IANA timezone identifiers are resolved with Python `zoneinfo`. Historical
DST rules therefore come from the installed timezone database rather than
hard-coded annual dates. Naive local input is round-tripped through both fold
values: duplicated fall-back times return `AMBIGUOUS`, skipped spring-forward
times return `NONEXISTENT_LOCAL_TIME`, and neither is guessed in strict mode.
Fixed offsets remain ordinary `datetime.timezone` values and are not presented
as named zones with DST support.

Windows deployments require an available IANA timezone database. Python may use
the system database or the cross-platform `tzdata` package. The engine does not
read `/usr/share/zoneinfo`, depend on host-local timezone settings, parse dates
using locale, or require a GUI.

## Sessions and boundaries

Session definitions contain a unique ID, type, IANA timezone, local open and
close, weekdays, priority, enabled state, and tags. Windows use `[open, close)`
semantics. Cross-midnight sessions are anchored to their opening weekday.
Every snapshot retains all active session IDs. London/New York overlap is
derived from simultaneous activity, while deterministic priority supports a
single primary context without discarding the full truth.

Trading-day and trading-week IDs derive from configured timezone-aware local
boundaries. Friday restrictions, expected weekend closures, Monday reopening,
and rollover windows can only narrow temporal eligibility. They never create a
signal or authorization.

## Calendar and Prompt 5 boundary

`IMarketCalendar` accepts versioned offline calendar decisions for closures,
shortened sessions, delayed opens, and unknown dates. No holiday is fabricated.
`WeekdayFallbackCalendar` is available only as an explicit configuration
policy. Calendar provenance is copied into each snapshot.

`ExpectedAvailabilityContext.expected_closure` is the narrow Prompt 5
integration contract. Prompt 5 remains the owner of data quality and staleness;
Prompt 9 merely supplies whether a gap crosses an expected closure.

## Reproducibility and safety

The engine reuses Prompt 1 `IClock`, accepts the Prompt 5 as-of timestamp,
records deterministic IDs and minimal recovery state, bounds timezone caching,
and detects backward or excessive forward clock jumps. `SessionSnapshot` is
immutable, eligibility is advisory metadata, and its DecisionTrace always ends
with `NO_ACTION`. Prompt 9 contains no network, broker, account, or order code.
