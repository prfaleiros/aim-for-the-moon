"""Channel fee math + sale breakdown.

Assumptions (verify against real sheet rows via the importer dry-run):
- Fee base = item price + shipping charged to buyer + buyer sales tax (when fee_on_tax).
- Buyer tax is a pass-through (platform collects/remits it), so payout = item + shipping - fee.
- Net profit = payout - shipping label cost - build cost.
"""
from decimal import Decimal

from .money import safe_decimal, q

ONE = Decimal("1")


def _channel(cfg: dict, channel_id: str) -> dict:
    raw = cfg["channels"][channel_id]
    fee_on_tax = raw.get("fee_on_tax", True)
    if isinstance(fee_on_tax, str):
        fee_on_tax = fee_on_tax.strip().lower() in ("1", "true", "yes")
    return {
        "rate": safe_decimal(raw.get("fee_rate")),
        "flat": safe_decimal(raw.get("fee_flat_usd")),
        "fee_on_tax": bool(fee_on_tax),
    }


def default_tax_rate(cfg: dict) -> Decimal:
    return safe_decimal(cfg.get("default_sales_tax_pct"), "0") / Decimal("100")


def fee_for(cfg: dict, channel_id: str, base: Decimal, tax: Decimal) -> Decimal:
    ch = _channel(cfg, channel_id)
    return ch["rate"] * (base + (tax if ch["fee_on_tax"] else Decimal("0"))) + ch["flat"]


def sale_breakdown(cfg: dict, sale: dict, build_cost) -> dict:
    """sale: item_price, shipping_charged, channel, sales_tax (opt override),
    fee_usd (opt override), label_cost."""
    item = safe_decimal(sale.get("item_price"))
    ship = safe_decimal(sale.get("shipping_charged"))
    base = item + ship
    channel = sale.get("channel") or cfg.get("default_channel", "direct")

    tax_override = sale.get("sales_tax")
    tax = safe_decimal(tax_override) if tax_override not in (None, "") else base * default_tax_rate(cfg)
    fee_override = sale.get("fee_usd")
    fee = safe_decimal(fee_override) if fee_override not in (None, "") else fee_for(cfg, channel, base, tax)

    label = safe_decimal(sale.get("label_cost"))
    cost = safe_decimal(build_cost)
    payout = base - fee
    net = payout - label - cost
    return {
        "channel": channel,
        "sales_tax": q(tax),
        "fee_usd": q(fee),
        "payout": q(payout),
        "net_profit": q(net),
        "roi": q(net / cost * 100) if cost else None,
    }


def estimated_net_payout(cfg: dict, list_price, channel_id: str | None = None) -> float:
    """What we expect to keep after fees and an assumed label, at list time (calibration snapshot)."""
    channel_id = channel_id or cfg.get("default_channel", "direct")
    price = safe_decimal(list_price)
    tax = price * default_tax_rate(cfg)
    fee = fee_for(cfg, channel_id, price, tax)
    return q(price - fee - safe_decimal(cfg.get("est_label_cost_usd")))


def price_for_net(cfg: dict, net_needed, channel_id: str) -> float:
    """List price (no shipping charged) leaving `net_needed` after fee and assumed label.
    Solves price - rate*(price*(1+tax) if fee_on_tax) - flat - label = net."""
    ch = _channel(cfg, channel_id)
    tax = default_tax_rate(cfg)
    var = ch["rate"] * ((ONE + tax) if ch["fee_on_tax"] else ONE)
    need = safe_decimal(net_needed) + ch["flat"] + safe_decimal(cfg.get("est_label_cost_usd"))
    return q(need / (ONE - var))
