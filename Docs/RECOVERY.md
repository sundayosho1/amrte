# Prompt 3 Persistence and Recovery

## Authority

`LocalCheckpointRepository` is the approved persistent implementation of the
Prompt 1 state-repository contract. `RecoveryEngine` validates its evidence
against Prompt 2's active configuration and an explicitly supplied fictional
dataset fingerprint. Persisted derived state never overrides either source.

## Crash-consistent write

1. Construct a complete versioned checkpoint in memory.
2. Canonically serialize and hash the payload and manifest.
3. Write to a temporary file, flush it, and request filesystem durability.
4. Read and validate the temporary checkpoint.
5. Preserve the current generation as previous.
6. Atomically promote the validated temporary file to current.
7. Request directory-entry durability.

At least current and previous generations are retained. A corrupt current
generation is quarantined and the previous generation is considered only after
full validation.

## Recovery gate

Automatic recovery requires compatible state schema, matching configuration
hash, matching dataset identity and fingerprint, matching experiment identity
when required, valid sequence/chain evidence, valid event state, unique
idempotency keys, no orphans or ghosts, healthy storage, and intact hard-safety
boundaries. Ambiguity produces manual review rather than automatic continuation.

`READY` remains distinct from `RUNNING`; recovery never starts processing.
Recovered `DEFENSIVE`, `PROTECT`, `SUSPENDED`, or `ERROR` state remains
restrictive across restart.

## Safety boundary

The checkpoint schema contains no broker, account, order, fill, leverage,
margin, or realistic market-position mechanics. Recursive field validation
rejects credentials, broker/account fields, and execution-enabling values before
serialization. The repository uses no network dependency.

## Determinism

Checkpoints preserve configuration/dataset fingerprints, committed cursor,
seed and random sequence position, experiment ID, recovery epoch, and checkpoint
chain. `ReplayDescriptor` exposes the minimum verified material future generic
replay infrastructure needs without implementing a market simulator.

