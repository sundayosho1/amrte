# Windows VPS Deployment Guide

Status: **static portability verified; native Windows qualification not performed**.

1. Install a supported 64-bit Python 3.11+ runtime from the organization's
   approved software source.
2. Copy the verified release archive to an application-owned directory.
3. Verify the supplied SHA-256 before extraction.
4. Extract with UTF-8 filename support into a versioned release directory.
5. Create separate relative-data locations for configuration, state, logs,
   reports, backups, datasets, and temporary files.
6. Install dependencies from the versioned project manifest in an isolated
   environment.
7. Run compilation and the packaged self-tests.
8. Validate configuration and state fingerprints.
9. Perform recovery and reconciliation before enabling processing.
10. Configure an approved Windows service/process manager for unattended start,
    graceful shutdown, bounded restart, and single-instance protection.

The package does not install or alter Windows services automatically. Service
identity, permissions, firewall rules, backup schedule, retention, monitoring,
and patch policy remain host-administrator responsibilities.

Startup gate: configuration → state validation → recovery → reconciliation →
health registry → neutral processing. Any failure leaves processing restricted.

