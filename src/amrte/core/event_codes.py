from types import MappingProxyType


EVENT_CODES = MappingProxyType({
    "SYS_INITIALIZATION_STARTED": "system initialization started",
    "SYS_INITIALIZATION_COMPLETED": "system initialization completed",
    "SYS_SHUTDOWN": "controlled shutdown",
    "CFG_LOADED": "configuration loaded",
    "CFG_ACTIVATED": "configuration activated",
    "CFG_VALIDATION_FAILED": "configuration validation failed",
    "CFG_ROLLBACK": "configuration rollback",
    "STATE_TRANSITION": "state transition completed",
    "STATE_TRANSITION_REJECTED": "state transition rejected",
    "HEALTH_CHANGED": "component health changed",
    "READINESS_CHANGED": "readiness changed",
    "PERSIST_CHECKPOINT_SAVED": "checkpoint saved",
    "PERSIST_WRITE_FAILED": "checkpoint write failed",
    "PERSIST_QUARANTINED": "state quarantined",
    "REC_STARTED": "recovery started",
    "REC_COMPLETED": "recovery completed",
    "REC_FAILED": "recovery failed",
    "REC_FALLBACK_USED": "fallback checkpoint used",
    "DEC_TRACE_COMPLETED": "decision trace completed",
    "DEC_NO_ACTION": "decision produced no action",
    "ERR_CAPTURED": "structured error captured",
    "ERR_ESCALATED": "error escalation triggered",
    "ERR_STORM": "error storm detected",
    "OBS_SINK_FAILED": "observability sink failed",
    "OBS_AUDIT_INTEGRITY_FAILED": "audit integrity verification failed",
    "OBS_BACKPRESSURE": "observability backpressure applied",
    "OBS_ROTATED": "structured log rotated",
    "OBS_RETENTION_APPLIED": "retention policy applied",
    "OBS_EXCEPTION_CAPTURED": "exception captured",
    "SEC_REDACTION_APPLIED": "sensitive fields redacted",
    "TEST_EVENT": "test event",
})

NO_ACTION_REASON_CODES = frozenset({
    "REJECTED_DATA", "REJECTED_REGIME", "REJECTED_SCORE", "REJECTED_SESSION",
    "REJECTED_NEWS", "REJECTED_RISK", "REJECTED_PORTFOLIO",
    "REJECTED_CORRELATION", "REJECTED_PROTECTION", "REJECTED_CONFIGURATION",
    "REJECTED_HEALTH", "REJECTED_CAPABILITY", "BLOCKED_SUSPENDED", "EXPIRED",
})


def validate_event_code(code: str) -> bool:
    return code in EVENT_CODES or code.startswith((
        "SYS_", "CFG_", "STATE_", "HEALTH_", "PERSIST_", "REC_", "OBS_",
        "DATA_", "STRAT_", "RISK_", "PORT_", "PROTECT_", "SIM_", "DEC_", "ERR_", "TEST_",
    ))
