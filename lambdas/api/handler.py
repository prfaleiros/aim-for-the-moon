"""Single Lambda behind an API Gateway {proxy+} route. Split by domain only if this outgrows one file."""
import json
import re
from collections import defaultdict
from datetime import date

import db
import repo
from config import load_config
from core import costs, fees, lifecycle, listing
from core.money import safe_decimal, q

BUILD_FIELDS = {"nickname", "family", "type", "target_price", "list_price", "notes", "thumbnail_key", "hours", "listing_url"}
PART_FIELDS = {"category", "description", "link", "color", "cost_usd", "included_with_case",
               "status", "order_id", "build_id"}
SALE_FIELDS = ("item_price", "shipping_charged", "sales_tax", "channel", "fee_usd", "label_cost",
               "payout", "net_profit", "roi", "payout_vs_estimate")
CATEGORIES = {"case", "bezel_insert", "bracelet", "movement", "hands", "dial", "other"}
PART_STATUSES = {"planned", "ordered", "delivered"}


class HttpError(Exception):
    def __init__(self, status, msg):
        self.status, self.msg = status, msg


def _pick(body: dict, allowed) -> dict:
    return {k: v for k, v in body.items() if k in allowed}


def _num(val):
    """Money/number fields are stored as numbers; blank clears."""
    return None if val in (None, "") else q(safe_decimal(val))


# ── builds ──────────────────────────────────────────────────────────────────────

def list_builds(_body, _q):
    out = []
    for b in db.query_gsi1("BUILDS"):
        parts = repo.parts_of(db, b["id"])
        b = repo.strip(b)
        b.update(cost=costs.build_cost(parts), parts_total=len(parts),
                 parts_delivered=sum(1 for p in parts if p.get("status") == "delivered"))
        out.append(b)
    return 200, out


def create_build(body, _q):
    if not (body.get("nickname") or "").strip():
        raise HttpError(400, "nickname required")
    b = _pick(body, BUILD_FIELDS)
    b.update(id=repo.new_id(), type=b.get("type") or "standard", status="designed",
             created_at=lifecycle.now_iso())
    for f in ("target_price", "list_price", "hours"):
        if f in b:
            b[f] = _num(b[f])
    db.put(repo.build_item(b))
    return 201, b


def _get_build(bid):
    b = db.get(f"BUILD#{bid}")
    if not b:
        raise HttpError(404, "build not found")
    return b


def get_build(_body, _q, bid):
    items = db.query_pk(f"BUILD#{bid}")
    meta = next((i for i in items if i["SK"] == "META"), None)
    if not meta:
        raise HttpError(404, "build not found")
    parts = repo.parts_of(db, bid)
    b = repo.strip(meta)
    b.update(parts=parts, cost=costs.build_cost(parts),
             price_log=[{"at": i["SK"][6:], "from": i.get("from"), "to": i.get("to")}
                        for i in items if i["SK"].startswith("PRICE#")])
    return 200, b


def _event_dates(b: dict, body: dict) -> dict:
    """Backdate/correct listed_date and sale_date after the fact. Only where the event happened."""
    out = {}
    try:
        if "listed_date" in body:
            if b["status"] not in ("listed", "sold"):
                raise ValueError("listing date only applies to a listed or sold build")
            out["listed_date"] = lifecycle.parse_day(body["listed_date"])
        if "sale_date" in body:
            if b["status"] != "sold":
                raise ValueError("sale date only applies to a sold build")
            out["sale_date"] = lifecycle.parse_day(body["sale_date"])
            if not out["sale_date"]:
                raise ValueError("a sold build needs a sale date")
        lifecycle.check_order(out.get("listed_date", b.get("listed_date")), out.get("sale_date", b.get("sale_date")))
    except ValueError as e:
        raise HttpError(400, str(e))
    return out


def update_build(body, _q, bid):
    b = _get_build(bid)
    upd = _pick(body, BUILD_FIELDS)
    for f in ("target_price", "list_price", "hours"):
        if f in upd:
            upd[f] = _num(upd[f])
    if "list_price" in upd and upd["list_price"] != b.get("list_price"):
        db.put({"PK": f"BUILD#{bid}", "SK": f"PRICE#{lifecycle.now_iso()}",
                "from": b.get("list_price"), "to": upd["list_price"]})
    upd.update(_event_dates(b, body))
    b.update(upd)
    if "listing" in body:
        b["listing"] = listing.clean_fields(body["listing"])
    db.put(repo.build_item(repo.strip(b)))
    return 200, repo.strip(b)


def transition_build(body, _q, bid):
    b = _get_build(bid)
    new = body.get("status")
    if new == "sold":
        raise HttpError(400, "use /close to record a sale")
    try:
        upd = lifecycle.transition(b, new, body.get("note"), on=body.get("date"))
    except ValueError as e:
        raise HttpError(400, str(e))
    old = b["status"]
    if new == "listed":
        cfg = load_config()
        prices = {f: _num(body[f]) for f in ("target_price", "list_price") if body.get(f) not in (None, "")}
        target = safe_decimal(prices.get("target_price", b.get("target_price")))
        price = safe_decimal(prices.get("list_price", b.get("list_price")))
        if target <= 0 or price <= 0:
            raise HttpError(400, "target price and list price must both be set (above $0) before listing")
        parts = repo.parts_of(db, bid)
        fields = listing.merge_fields(listing.prefill(cfg, b, parts), {**(b.get("listing") or {}), **(body.get("listing") or {})})
        missing = listing.render(cfg, fields, price)["missing"]
        if missing:
            raise HttpError(400, "listing details missing: " + ", ".join(listing.LABELS[m] for m in missing))
        if "list_price" in prices and prices["list_price"] != b.get("list_price"):
            db.put({"PK": f"BUILD#{bid}", "SK": f"PRICE#{lifecycle.now_iso()}",
                    "from": b.get("list_price"), "to": prices["list_price"]})
        upd.update(prices)
        upd["listing"] = listing.clean_fields(fields)
        upd["estimated_net_payout"] = fees.estimated_net_payout(cfg, price)
    if new == "parts_ready" and old != "sold":
        if any(p.get("status") != "delivered" for p in repo.parts_of(db, bid)):
            raise HttpError(400, "not all parts are delivered")
    b.update(upd)
    if old == "sold":  # refund: the sale is void, only refund_note remains
        for f in SALE_FIELDS:
            b.pop(f, None)
    b = {k: v for k, v in b.items() if v is not None}  # a refund clears sale_date
    db.put(repo.build_item(repo.strip(b)))
    return 200, repo.strip(b)


def delete_build(body, _q, bid):
    """Danger zone. Needs the build's nickname as confirmation (also enforced server-side); sold builds are
    part of the financials, so they must be refunded to parts_ready first."""
    b = _get_build(bid)
    if b["status"] == "sold":
        raise HttpError(400, "a sold build is part of your financials; refund it to parts ready first")
    if (body.get("confirm") or "").strip() != b["nickname"].strip():
        raise HttpError(400, "confirmation does not match the build name")
    mode = body.get("parts", "stock")
    if mode not in ("stock", "delete"):
        raise HttpError(400, "parts must be 'stock' or 'delete'")
    parts = repo.parts_of(db, bid)
    for p in parts:
        if mode == "delete":
            db.delete(f"PART#{p['id']}")
        else:
            p.pop("build_id", None)
            db.put(repo.part_item(p))
    for item in db.query_pk(f"BUILD#{bid}"):  # META + price log
        db.delete(item["PK"], item["SK"])
    return 200, {"deleted": bid, "parts": len(parts), "parts_mode": mode}


def close_sale(body, _q, bid):
    b = _get_build(bid)
    if b["status"] != "listed":
        raise HttpError(400, "only a listed build can be sold")
    cfg = load_config()
    channel = body.get("channel") or cfg.get("default_channel")
    if channel not in cfg["channels"]:
        raise HttpError(400, f"unknown channel {channel}")
    sale = {**_pick(body, {"item_price", "shipping_charged", "sales_tax", "fee_usd", "label_cost"}),
            "channel": channel}
    if not safe_decimal(sale.get("item_price")):
        raise HttpError(400, "item_price required")
    try:
        sold = lifecycle.transition(b, "sold", on=body.get("sale_date"))
    except ValueError as e:
        raise HttpError(400, str(e))
    res = fees.sale_breakdown(cfg, sale, costs.build_cost(repo.parts_of(db, bid)))
    est = b.get("estimated_net_payout")
    if est is not None:
        res["payout_vs_estimate"] = q(safe_decimal(res["payout"]) - safe_decimal(sale.get("label_cost"))
                                      - safe_decimal(est))
    b.update({"item_price": _num(sale["item_price"]),
              "shipping_charged": _num(sale.get("shipping_charged")) or 0,
              "label_cost": _num(sale.get("label_cost")) or 0,
              **res, **sold})
    db.put(repo.build_item(repo.strip(b)))
    return 200, repo.strip(b)


# ── parts ───────────────────────────────────────────────────────────────────────

def _check_part(upd: dict):
    if "category" in upd and upd["category"] not in CATEGORIES:
        raise HttpError(400, f"category must be one of {sorted(CATEGORIES)}")
    if "status" in upd and upd["status"] not in PART_STATUSES:
        raise HttpError(400, f"status must be one of {sorted(PART_STATUSES)}")
    if "cost_usd" in upd:
        upd["cost_usd"] = _num(upd["cost_usd"])
    if upd.get("build_id"):
        _get_build(upd["build_id"])


def create_part(body, _q):
    p = _pick(body, PART_FIELDS)
    p.setdefault("status", "planned")
    p.setdefault("included_with_case", False)
    if "category" not in p:
        raise HttpError(400, "category required")
    _check_part(p)
    p["id"] = repo.new_id()
    db.put(repo.part_item(p))
    if p.get("build_id"):
        repo.refresh_auto_status(db, p["build_id"])
    return 201, p


def update_part(body, _q, pid):
    p = db.get(f"PART#{pid}")
    if not p:
        raise HttpError(404, "part not found")
    old_build = p.get("build_id")
    upd = _pick(body, PART_FIELDS)
    _check_part(upd)
    p.update(upd)
    if not p.get("build_id"):
        p.pop("build_id", None)  # unassign -> back to stock
    db.put(repo.part_item(repo.strip(p)))
    for bid in {old_build, p.get("build_id")} - {None}:
        repo.refresh_auto_status(db, bid)
    return 200, repo.strip(p)


def delete_part(_body, _q, pid):
    p = db.get(f"PART#{pid}")
    if p:
        db.delete(f"PART#{pid}")
        if p.get("build_id"):
            repo.refresh_auto_status(db, p["build_id"])
    return 200, {"deleted": pid}


def stock(_body, _q):
    return 200, [repo.strip(i) for i in db.query_gsi1("STOCK") if i.get("status") == "delivered"]


# ── reports / config ────────────────────────────────────────────────────────────

def _f(val) -> float:
    return float(safe_decimal(val))


def financials(_body, _q):
    months = defaultdict(lambda: defaultdict(float))
    families = defaultdict(lambda: defaultdict(float))
    days = []
    for b in db.query_gsi1("BUILDS"):
        if b["status"] != "sold":
            continue
        m = months[(b.get("sale_date") or "history")[:7]]
        m["sales"] += 1
        m["revenue"] += _f(b.get("item_price")) + _f(b.get("shipping_charged"))
        m["fees"] += _f(b.get("fee_usd"))
        m["labels"] += _f(b.get("label_cost"))
        m["payout"] += _f(b.get("payout")) - _f(b.get("label_cost"))  # what lands after fees and label
        m["net_profit"] += _f(b.get("net_profit"))
        f = families[b.get("family") or "?"]
        f["sales"] += 1
        f["net_profit"] += _f(b.get("net_profit"))
        if _f(b.get("target_price")):  # calibration only where a target existed (Sheet1 history has none)
            f["cal_n"] += 1
            f["target"] += _f(b["target_price"])
            f["sold"] += _f(b.get("item_price"))
        if b.get("payout_vs_estimate") is not None:
            f["vs_estimate"] += _f(b["payout_vs_estimate"])
            f["vs_estimate_n"] += 1
        if b.get("listed_date") and b.get("sale_date"):
            days.append((date.fromisoformat(b["sale_date"]) - date.fromisoformat(b["listed_date"])).days)
    return 200, {
        "monthly": [{"month": k, **{a: round(v, 2) for a, v in m.items()}} for k, m in sorted(months.items())],
        "by_family": [{"family": k, "sales": int(f["sales"]),
                       "avg_target": round(f["target"] / f["cal_n"], 2) if f["cal_n"] else None,
                       "avg_sold_vs_target": round(f["sold"] / f["cal_n"], 2) if f["cal_n"] else None,
                       "avg_net_profit": round(f["net_profit"] / f["sales"], 2),
                       "avg_vs_estimate": round(f["vs_estimate"] / f["vs_estimate_n"], 2)
                       if f["vs_estimate_n"] else None}
                      for k, f in sorted(families.items())],
        "avg_days_listed_to_sold": round(sum(days) / len(days), 1) if days else None,
    }


def get_config(_body, _q):
    return 200, load_config()


def _listing_view(b, parts, fields, price):
    cfg = load_config()
    out = listing.render(cfg, fields, price)
    out.update(fields=fields, payouts=listing.payouts(cfg, price, costs.build_cost(parts)),
               labels=listing.LABELS, required=listing.REQUIRED)
    return out


def get_listing(_body, _q, bid):
    b = _get_build(bid)
    parts = repo.parts_of(db, bid)
    fields = listing.merge_fields(listing.prefill(load_config(), b, parts), b.get("listing"))
    return 200, _listing_view(b, parts, fields, b.get("list_price"))


def preview_listing(body, _q, bid):
    """Render with unsaved edits and a candidate price; nothing is written."""
    b = _get_build(bid)
    parts = repo.parts_of(db, bid)
    fields = listing.merge_fields(listing.prefill(load_config(), b, parts), body.get("fields"))
    price = body.get("list_price") if body.get("list_price") not in (None, "") else b.get("list_price")
    return 200, _listing_view(b, parts, fields, price)


ROUTES = [
    ("GET", r"/builds", list_builds),
    ("POST", r"/builds", create_build),
    ("GET", r"/builds/(?P<bid>[^/]+)", get_build),
    ("PATCH", r"/builds/(?P<bid>[^/]+)", update_build),
    ("DELETE", r"/builds/(?P<bid>[^/]+)", delete_build),
    ("POST", r"/builds/(?P<bid>[^/]+)/transition", transition_build),
    ("POST", r"/builds/(?P<bid>[^/]+)/close", close_sale),
    ("GET", r"/builds/(?P<bid>[^/]+)/listing", get_listing),
    ("POST", r"/builds/(?P<bid>[^/]+)/listing-preview", preview_listing),
    ("POST", r"/parts", create_part),
    ("PATCH", r"/parts/(?P<pid>[^/]+)", update_part),
    ("DELETE", r"/parts/(?P<pid>[^/]+)", delete_part),
    ("GET", r"/stock", stock),
    ("GET", r"/reports/financials", financials),
    ("GET", r"/config", get_config),
]


def handler(event, _ctx):
    method, path = event["httpMethod"], event["path"].rstrip("/") or "/"
    try:
        body = json.loads(event["body"]) if event.get("body") else {}
        for m, pattern, fn in ROUTES:
            hit = re.fullmatch(pattern, path)
            if m == method and hit:
                status, payload = fn(body, event.get("queryStringParameters") or {}, **hit.groupdict())
                return db.response(status, payload)
        return db.response(404, {"error": f"no route {method} {path}"})
    except HttpError as e:
        return db.response(e.status, {"error": e.msg})
    except json.JSONDecodeError:
        return db.response(400, {"error": "invalid JSON"})
