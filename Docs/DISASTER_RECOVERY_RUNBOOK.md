# Disaster Recovery Runbook

1. Stop the process and preserve the affected state read-only.
2. Verify release archive, backup manifest, checksums, versions, schemas, and
   configuration fingerprint.
3. Restore into an isolated versioned directory.
4. Run compilation, diagnostics, recovery, reconciliation, and replay checks.
5. Confirm restored permission is no more permissive than pre-failure state.
6. Start paused, inspect health and alerts, then use governed resume only when
   every mandatory gate passes.

If authoritative state cannot be reconstructed, remain `RECOVERY_PENDING`.
Recovery must never fabricate evidence or increase permission.

