"""Build/part persistence. Keys:
BUILD  PK=BUILD#id SK=META   GSI1PK=BUILDS            GSI1SK=<status>#<id>
PRICE  PK=BUILD#id SK=PRICE#<ts>
PART   PK=PART#id  SK=META   GSI1PK=BUILD#<id>|STOCK  GSI1SK=PART#<id>   (order_id -> its ORDER)
ORDER  PK=ORDER#id SK=META   GSI1PK=ORDERS           GSI1SK=<order_date>#<id>
"""
import os
import time

from core import costs, lifecycle


def new_id() -> str:
    # time-sortable (ms since epoch, base-16) + random suffix
    return f"{int(time.time() * 1000):012x}{os.urandom(3).hex()}"


def build_item(b: dict) -> dict:
    b = dict(b)
    b["PK"], b["SK"] = f"BUILD#{b['id']}", "META"
    b["GSI1PK"], b["GSI1SK"] = "BUILDS", f"{b['status']}#{b['id']}"
    return b


def order_item(o: dict) -> dict:
    o = dict(o)
    o["PK"], o["SK"] = f"ORDER#{o['id']}", "META"
    o["GSI1PK"], o["GSI1SK"] = "ORDERS", f"{o['order_date']}#{o['id']}"
    return o


def part_item(p: dict) -> dict:
    p = dict(p)
    p["PK"], p["SK"] = f"PART#{p['id']}", "META"
    p["GSI1PK"] = f"BUILD#{p['build_id']}" if p.get("build_id") else "STOCK"
    p["GSI1SK"] = f"PART#{p['id']}"
    return p


def strip(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in ("PK", "SK", "GSI1PK", "GSI1SK")}


def parts_of(db, build_id: str) -> list:
    return [strip(i) for i in db.query_gsi1(f"BUILD#{build_id}")]


def refresh_auto_status(db, build_id: str):
    """Re-run awaiting_parts <-> parts_ready after any part change."""
    b = db.get(f"BUILD#{build_id}")
    if not b:
        return
    new = lifecycle.auto_status(b["status"], parts_of(db, build_id))
    if new != b["status"]:
        b.update(status=new, status_changed_at=lifecycle.now_iso())
        db.put(build_item(strip(b)))
