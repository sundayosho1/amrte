# AMRTE Portfolio Risk Research

Version 0.22.0 provides deterministic aggregate accounting for fictional research exposure. It has no broker, account, margin, leverage, live-price, or execution capability.

## Accounting model

The registry stores immutable exposure versions and selects the latest version effective at each snapshot timestamp. Gross exposure is the sum of remaining exposure magnitudes. Net directional exposure is bullish minus bearish exposure; opposite directions never reduce gross limits automatically.

Committed current risk, reserved risk, and available global capacity are distinct. Reservations are included before admission, preventing two candidates from spending the same capacity observation. Commit converts a reservation to an active record without counting both; release and expiry are idempotent.

## Direct factor exposure

`DeterministicExposureDecomposer` consumes versioned offline instrument mappings. For a two-factor instrument, bullish exposure is positive on the base factor and negative on the quote factor; bearish exposure reverses those signs. This is direct decomposition only. No statistical correlation or diversification benefit is calculated.

## Admission

Every applicable implemented hard capacity is evaluated and the most restrictive exposure capacity binds. Policy either blocks insufficient capacity or conservatively floors a reduced exposure to the Prompt 17-compatible configured step. Approved exposure can never exceed the upstream proposal.

## Temporal integrity and reconciliation

Prompt 20 remaining exposure and Prompt 21 protective state are consumed without being rewritten. Reconciliation can only preserve or reduce exposure/risk. A future lifecycle change creates a new immutable exposure version and cannot alter a reconstructed earlier snapshot.

## Recovery

Recovery retains active records, immutable record versions, reservations, and ledger events. Duplicate logical records/reservations and incompatible engine/configuration lineage fail closed.

## Current limitations

Global risk, gross exposure, directional exposure, instrument exposure, factor gross exposure, strategy/family/variant exposure, and global concurrency are enforced. The configuration contracts also expose per-dimension risk, factor-net, imbalance, per-instrument concurrency, soft-threshold, and override concepts; full enforcement and diagnostics for that extended matrix remain a Prompt 22 hardening extension. Prompt 23 correlation and Prompt 24 dynamic allocation are deliberately absent.
