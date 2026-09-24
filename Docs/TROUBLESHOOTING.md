# Troubleshooting

| Symptom | Likely cause | Evidence | Safe action |
|---|---|---|---|
| Startup blocked | Invalid configuration/state | Startup reason code | Correct configuration; rerun validation |
| Recovery pending | Epoch/schema/fingerprint mismatch | Recovery trace | Restore compatible backup or rebuild derived state |
| Restricted health | Dependency or storage failure | Health root-cause chain | Repair root component; reconcile before resume |
| Duplicate alerts | Persistent unresolved fault | Alert occurrence count | Fix cause; resolve only after verification |
| Update blocked | Checksum/backup/schema mismatch | Update reasons | Do not bypass; correct manifest or package |
| Clock restriction | Rollback or excessive jump | Heartbeat/clock evidence | Correct host time; validate chronology |
| Diagnostic unknown | Check raised an exception | Diagnostic reason code | Inspect check dependency and rerun |

Support bundles contain hashes and redacted metadata. Never add secrets or
private raw datasets to a support bundle.

