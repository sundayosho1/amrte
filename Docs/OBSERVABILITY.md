# Prompt 4 Observability

## Event pipeline

All existing audit hooks flow through one `ObservabilityService`:

emit → validate code → classify → enrich → redact → sequence → hash → retain → route

The legacy in-memory audit sink remains only as a compatibility adapter and
forwards every record to the authoritative service.

## Event identity and relationships

Every stored event has a deterministic unique ID, monotonic sequence, recovery
epoch, correlation ID, optional causation ID, configuration references,
category, classifications, severity, code, concise context, and integrity hash.
Correlation groups a workflow; causation points to the direct preceding event.

## Severities

- `DEBUG`: development diagnostics.
- `INFO`: normal material lifecycle events.
- `WARNING`: unexpected but currently recoverable condition.
- `ERROR`: failed operation or unhealthy subsystem.
- `CRITICAL`: integrity, safety, or recoverability is threatened.

## Event codes

Stable codes are centralized in `event_codes.py`. Namespaces include `SYS_`,
`CFG_`, `STATE_`, `HEALTH_`, `PERSIST_`, `REC_`, `OBS_`, `DATA_`, `STRAT_`,
`RISK_`, `PORT_`, `PROTECT_`, `SIM_`, `DEC_`, `ERR_`, and `TEST_`.

New modules must reuse an existing semantic code or add one centrally. They
must not introduce scattered free-form codes.

## Redaction and context limits

Sensitive-looking keys and strings are replaced before routing. Nested objects
are inspected recursively. Depth, item count, and string length are bounded to
prevent dataset, configuration, checkpoint, or stack dumps.

## Destinations

- Canonical JSON Lines with rotation, retention, and total-size limits.
- Human-readable console output.
- In-memory test sink.
- Bounded emergency fallback sink.
- Selected summary-only CSV export.

No network telemetry or external notification transport exists.

## Integrity

Each event includes the preceding event hash and its own SHA-256 hash over a
canonical representation. `verify_chain` detects broken links or modified
records and marks health `CORRUPTED`. This is integrity evidence, not a digital
signature or guarantee against a hostile actor.

## Failure behavior

An optional sink failure degrades observability. An authoritative sink failure
makes observability unavailable and writes a minimal bounded fallback record.
A recursion guard prevents logger-failure loops. Engine readiness now requires
a healthy registered observability service.

## Queries

Events can be filtered by time, severity, category, code, correlation,
configuration hash, and recovery epoch. `incident_timeline` returns events in
sequence order for a correlation ID. Audit replay remains separate from Prompt
3 state replay.

## Decision and error contracts

`DecisionTraceBuilder` records gate evaluations and the exact short-circuit
point for accepted, rejected, blocked, expired, and no-action results. It does
not implement any market decision logic.

`ErrorManager` normalizes classifications, counts occurrences, maintains
rolling windows, detects error storms, escalates critical conditions, and
applies bounded idempotent retries through Prompt 3's ledger.

