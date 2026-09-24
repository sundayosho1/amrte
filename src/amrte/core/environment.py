import os

from .types import RuntimeEnvironment


def detect_environment(value: str | None = None) -> RuntimeEnvironment:
    raw = (value if value is not None else os.getenv("AMRTE_ENV", "")).strip().upper()
    try:
        return RuntimeEnvironment[raw]
    except KeyError:
        return RuntimeEnvironment.UNKNOWN

