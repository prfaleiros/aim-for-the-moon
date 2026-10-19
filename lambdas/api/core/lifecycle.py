"""Build status machine. Dates are stamped from transitions, never typed or derived from record age."""
from datetime import datetime, timezone

STATUSES = ["designed", "awaiting_parts", "parts_ready", "listed", "sold"]

# Allowed manual moves. awaiting_parts <-> parts_ready is automatic (see auto_status).
ALLOWED = {
    "designed": {"awaiting_parts", "parts_ready"},
    "awaiting_parts": {"designed", "parts_ready"},
    "parts_ready": {"awaiting_parts", "listed"},
    "listed": {"parts_ready", "sold"},
    "sold": {"parts_ready"},  # refund: back to parts_ready with a note
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def auto_status(current: str, parts: list) -> str:
    """Flip awaiting_parts <-> parts_ready based on part delivery. Later stages are never touched."""
    if current not in ("awaiting_parts", "parts_ready") or not parts:
        return current
    all_delivered = all(p.get("status") == "delivered" for p in parts)
    return "parts_ready" if all_delivered else "awaiting_parts"


def transition(build: dict, new_status: str, note: str | None = None) -> dict:
    """Return the field updates for moving `build` to `new_status`. Raises ValueError if illegal."""
    old = build.get("status")
    if new_status == old:
        return {}
    if new_status not in ALLOWED.get(old, set()):
        raise ValueError(f"cannot move build from {old} to {new_status}")
    ts = now_iso()
    upd = {"status": new_status, "status_changed_at": ts}
    if new_status == "listed" and not build.get("listed_date"):
        upd["listed_date"] = ts[:10]  # first listing only
    if old == "sold" and new_status == "parts_ready":  # refund
        upd["refund_note"] = note or ""
        upd["sale_date"] = None
    if new_status == "sold":
        upd["sale_date"] = ts[:10]
    return upd
