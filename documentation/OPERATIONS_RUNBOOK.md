# Operations Runbook

## Daily

- Verify application version and package fingerprint.
- Review overall health, unresolved critical alerts, storage headroom, latest
  heartbeat, last successful backup, and reconciliation status.

## Weekly

- Run diagnostics and self-tests, verify backup checksums, review bounded log
  retention, inspect configuration drift, and rehearse one non-destructive
  reconciliation.

## Monthly

- Perform a restore verification in an isolated location, review dependency and
  runtime support status, audit alert trends, and confirm the disaster-recovery
  contact/runbook remains current.

Never resume while health is restricted, recovery is pending, state lineage is
unknown, or reconciliation fails.

