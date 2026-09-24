import hashlib
import re

from .types import HealthStatus, InstrumentIdentity


_SAFE_ID = re.compile(r"[^A-Z0-9_]")


def normalize_instrument(provider_symbol: str, canonical: str | None = None) -> InstrumentIdentity:
    provider = provider_symbol.strip()
    name = _SAFE_ID.sub("_", (canonical or provider).strip().upper()).strip("_")
    status = HealthStatus.HEALTHY if provider and name else HealthStatus.UNHEALTHY
    return InstrumentIdentity(name, provider, metadata_status=status)


def deterministic_id(kind: str, *parts: object, length: int = 16) -> str:
    normalized = "|".join([kind.upper(), *(str(p).strip().upper() for p in parts)])
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:length].upper()
    prefix = _SAFE_ID.sub("_", kind.upper())[:12]
    return f"{prefix}-{digest}"

