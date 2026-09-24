import math
from decimal import Decimal, ROUND_HALF_EVEN


def require_finite(value: float, *, non_negative: bool = False) -> float:
    if not math.isfinite(value):
        raise ValueError("value must be finite")
    if non_negative and value < 0:
        raise ValueError("value must be non-negative")
    return value


def bounded_percentage(value: float) -> float:
    require_finite(value)
    if not 0.0 <= value <= 100.0:
        raise ValueError("percentage must be between 0 and 100")
    return value


def safe_divide(numerator: float, denominator: float) -> float:
    require_finite(numerator)
    require_finite(denominator)
    if denominator == 0:
        raise ZeroDivisionError("denominator must not be zero")
    return numerator / denominator


def safe_round(value: float, places: int) -> Decimal:
    require_finite(value)
    if places < 0:
        raise ValueError("places must be non-negative")
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_EVEN)

