"""Build status machine. Event dates (listed_date, sale_date) come from lifecycle transitions: they default to
today but can be backdated (you may record a sale days later), and are never derived from record age."""
from datetime import date, datetime, timedelta, timezone

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


def parse_day(value) -> str | None:
    """Validate an ISO day (YYYY-MM-DD). Blank -> None. No future dates (1 day of slack for time zones)."""
    if value is None or str(value).strip() == "":
        return None
    try:
        d = date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValueError(f"'{value}' is not a valid date (use YYYY-MM-DD)")
    if d > datetime.now(timezone.utc).date() + timedelta(days=1):
        raise ValueError("date is in the future")
    return d.isoformat()


def check_order(listed_date: str | None, sale_date: str | None):
    if listed_date and sale_date and sale_date < listed_date:
        raise ValueError(f"sale date {sale_date} is before the listing date {listed_date}")


def auto_status(current: str, parts: list) -> str:
    """Flip awaiting_parts <-> parts_ready based on part delivery. Later stages are never touched."""
    if current not in ("awaiting_parts", "parts_ready") or not parts:
        return current
    all_delivered = all(p.get("status") == "delivered" for p in parts)
    return "parts_ready" if all_delivered else "awaiting_parts"


def transition(build: dict, new_status: str, note: str | None = None, on: str | None = None) -> dict:
    """Return the field updates for moving `build` to `new_status`. Raises ValueError if illegal.
    `on` backdates the event (listing or sale); a relist after a refund keeps the first listing date."""
    old = build.get("status")
    if new_status == old:
        return {}
    if new_status not in ALLOWED.get(old, set()):
        raise ValueError(f"cannot move build from {old} to {new_status}")
    ts = now_iso()
    day = parse_day(on) or ts[:10]
    upd = {"status": new_status, "status_changed_at": ts}
    if new_status == "listed" and not build.get("listed_date"):
        upd["listed_date"] = day  # first listing only
    if old == "sold" and new_status == "parts_ready":  # refund
        upd["refund_note"] = note or ""
        upd["sale_date"] = None
    if new_status == "sold":
        check_order(build.get("listed_date"), day)
        upd["sale_date"] = day
    return upd
