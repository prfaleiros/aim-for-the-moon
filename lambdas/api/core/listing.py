"""Facebook listing text from a config template. No FB API: we produce a copy/paste block."""
from . import fees
from .money import safe_decimal, q

FIELDS = ["model", "inspired", "aesthetics", "case", "bracelet", "dial_color", "bezel", "extras"]
REQUIRED = ["model", "inspired", "aesthetics", "case", "bracelet", "dial_color", "bezel"]  # extras is optional
LABELS = {"model": "Model name", "inspired": "Inspired by (one word)", "aesthetics": "Aesthetics",
          "case": "Case material + color", "bracelet": "Bracelet material + color", "dial_color": "Dial color",
          "bezel": "Bezel insert (color + type)", "extras": "Extras (one per line)"}


def fmt_price(price) -> str:
    d = safe_decimal(price)
    return str(int(d)) if d == d.to_integral_value() else f"{d:.2f}"


def prefill(cfg: dict, build: dict, parts: list) -> dict:
    """Starting values from the build and its parts; the user edits before listing."""
    color = {}
    for p in parts:
        if p.get("color") and p.get("category") not in color:
            color[p["category"]] = p["color"]
    fam = build.get("family") or ""
    return {
        "model": build.get("nickname", ""),
        "inspired": fam,
        "aesthetics": cfg.get("listing", {}).get("family_blurbs", {}).get(fam, ""),
        "case": color.get("case", ""),
        "bracelet": color.get("bracelet", ""),
        "dial_color": color.get("dial", ""),
        "bezel": color.get("bezel_insert", ""),
        "extras": "",
    }


def merge_fields(prefilled: dict, saved: dict | None) -> dict:
    """Saved (user-edited) values win; blanks fall back to the prefill."""
    out = dict(prefilled)
    for k, v in (saved or {}).items():
        if k in FIELDS and str(v or "").strip():
            out[k] = v
    return out


def clean_fields(fields: dict | None) -> dict:
    return {k: str(v).strip() for k, v in (fields or {}).items() if k in FIELDS and v is not None}


def render(cfg: dict, fields: dict, price) -> dict:
    lc = cfg["listing"]
    vals = {k: (fields.get(k) or "").strip() for k in FIELDS}
    missing = [k for k in REQUIRED if not vals[k]]
    shown = {k: (vals[k] or f"<{k}>") for k in REQUIRED}
    shown["price"] = fmt_price(price)
    extras = [e.strip().lstrip("*").strip() for e in vals["extras"].splitlines() if e.strip().lstrip("*").strip()]
    lines = []
    for line in lc["description_lines"]:
        if line == "{extras}":
            lines += [f"* {e}" for e in extras]
        else:
            lines.append(line.format(**shown))
    return {"title": lc["title"].format(**shown), "description": "\n".join(lines), "missing": missing}


def payouts(cfg: dict, price, build_cost) -> list:
    """What each payment channel leaves at this price (assumed label, default buyer tax), and the profit."""
    price_d, cost = safe_decimal(price), safe_decimal(build_cost)
    out = []
    for cid, ch in cfg["channels"].items():
        tax = price_d * fees.default_tax_rate(cfg)
        fee = fees.fee_for(cfg, cid, price_d, tax)
        net = price_d - fee - safe_decimal(cfg.get("est_label_cost_usd"))
        out.append({"channel": cid, "label": ch.get("label", cid), "fee": q(fee), "net_payout": q(net),
                    "profit": q(net - cost)})
    return out
