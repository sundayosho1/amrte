# Configuration Reference

Configuration is immutable after activation and identified by fingerprint.
Required operational groups are paths, retention bounds, heartbeat/clock
tolerances, storage thresholds, recovery policy, health policy, diagnostics,
backup policy, and update compatibility.

Paths must be configurable and OS-neutral; no source-controlled secrets or
hard-coded user directories are permitted. Integer bounds must be positive.
Invalid or unknown mandatory values fail closed. Runtime changes create a new
configuration lineage and require validation; they never silently mutate the
active configuration.

