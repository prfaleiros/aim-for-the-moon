from .money import safe_decimal, q


def part_cost(part: dict):
    if part.get("included_with_case"):
        return safe_decimal(0)
    return safe_decimal(part.get("cost_usd"))


def build_cost(parts: list) -> float:
    return q(sum((part_cost(p) for p in parts), safe_decimal(0)))
