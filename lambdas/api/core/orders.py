"""Vendor orders: check the receipt math and spread discount/shipping/tax over the parts.

Every unit becomes its own part (a line with qty 2 makes two parts). Each part's cost is its share of what was
actually paid, in whole cents that add up to exactly `total_paid` (largest-remainder rounding).
"""
from decimal import Decimal, ROUND_HALF_UP

from .money import safe_decimal

MAX_UNITS = 50
TOLERANCE_CENTS = 2  # receipts round tax per line; accept a couple of cents of drift


def cents(value) -> int:
    return int((safe_decimal(value) * 100).to_integral_value(ROUND_HALF_UP))


def to_usd(c: int) -> float:
    return float(Decimal(c) / 100)


def allocate(unit_cents: list, total_cents: int) -> list:
    """Split total_cents across units in proportion to their price; result sums to exactly total_cents."""
    weight = sum(unit_cents)
    if weight <= 0:
        raise ValueError("the order has no priced lines")
    base, rem = [], []
    for u in unit_cents:
        num = total_cents * u
        base.append(num // weight)
        rem.append(num % weight)
    leftover = total_cents - sum(base)
    for i in sorted(range(len(unit_cents)), key=lambda i: (-rem[i], -unit_cents[i], i))[:leftover]:
        base[i] += 1
    return base


def expand(lines: list) -> list:
    """One dict per physical part, with its item price in cents."""
    units = []
    for n, line in enumerate(lines, 1):
        desc = (line.get("description") or "").strip()
        if not desc:
            raise ValueError(f"line {n}: description is required")
        price = cents(line.get("unit_price"))
        if price < 0:
            raise ValueError(f"line {n}: price cannot be negative")
        raw_qty = line.get("qty")
        try:
            qty = 1 if raw_qty is None or str(raw_qty).strip() == "" else int(raw_qty)
        except (TypeError, ValueError):
            raise ValueError(f"line {n}: quantity must be a whole number")
        if qty < 1:
            raise ValueError(f"line {n}: quantity must be at least 1")
        units += [{**line, "description": desc, "item_cents": price} for _ in range(qty)]
        if len(units) > MAX_UNITS:
            raise ValueError(f"too many parts in one order (max {MAX_UNITS})")
    return units


def build(lines: list, discount, shipping, tax, total_paid) -> dict:
    """Allocation for an order. `error` is set (and the order must not be saved) if the receipt does not add up;
    the allocation is then spread over the computed total so the UI can still preview it."""
    units = expand(lines)
    subtotal = sum(u["item_cents"] for u in units)
    computed = subtotal - cents(discount) + cents(shipping) + cents(tax)
    paid = cents(total_paid)
    diff = paid - computed
    error = None
    if abs(diff) > TOLERANCE_CENTS:
        error = (f"lines {to_usd(subtotal):.2f} - discount {to_usd(cents(discount)):.2f} + shipping "
                 f"{to_usd(cents(shipping)):.2f} + tax {to_usd(cents(tax)):.2f} = {to_usd(computed):.2f}, "
                 f"but total paid is {to_usd(paid):.2f}")
    shares = allocate([u["item_cents"] for u in units], paid if error is None else computed)
    parts = [{**{k: v for k, v in u.items() if k != "item_cents"}, "item_price": to_usd(u["item_cents"]),
              "cost_usd": to_usd(s)} for u, s in zip(units, shares)]
    return {"parts": parts, "subtotal": to_usd(subtotal), "computed_total": to_usd(computed),
            "total_paid": to_usd(paid), "error": error}
