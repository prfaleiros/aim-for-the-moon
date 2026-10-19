from decimal import Decimal, ROUND_HALF_UP


def safe_decimal(val, default="0") -> Decimal:
    """Defensive: an admin quick-patch can put arbitrary text in any field."""
    try:
        if val is None or (isinstance(val, str) and not val.strip()):
            return Decimal(default)
        return Decimal(str(val))
    except Exception:
        return Decimal(default)


def q(val: Decimal) -> float:
    return float(val.quantize(Decimal("0.01"), ROUND_HALF_UP))
