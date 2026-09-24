# Neutral Deterministic Experiment Validation

AMRTE v0.24.9 provides a generic experiment framework for validating software and research configurations against synthetic or approved offline, non-financial datasets.

## Workflow

An immutable `ExperimentDefinition` freezes dataset identity, subjects, categories, contexts, time bounds, configuration lineage, experiment mode, holdout subjects, and parameter dimensions. `OfflineDatasetManifest` and `NeutralObservation` provide deterministic provenance and point-in-time availability.

The engine validates and registers an experiment, expands a bounded Cartesian parameter grid, creates deterministic trials, evaluates eligible observations, checkpoints partial work, publishes a multi-metric `ValidationScorecard`, and generates an immutable result manifest and replay fingerprint.

## Safety and quality controls

- Future, malformed, non-finite, out-of-period, and lineage-incompatible observations are rejected.
- Exploratory, confirmatory, and pre-registered modes remain distinct.
- Holdout subjects are excluded from ordinary evaluation.
- No single score automatically promotes a configuration.
- Sample adequacy, trial variance, sensitivity ranges, and concentration warnings remain visible.
- Partial execution, cancellation, idempotent resume, concurrency protection, recovery, and non-mutating reconciliation are supported.

## Boundaries

This framework does not simulate markets, trades, positions, accounts, profit, financial risk, wagering, brokers, or execution. It does not select or deploy configurations automatically. Its scores are generic software/research measurements over neutral fixture data.

The original trading backtesting/optimization Prompt 33 is not implemented. Prompt 34 robustness simulation is not started.
