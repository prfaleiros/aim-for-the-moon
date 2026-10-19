import streamlit as st

STATUSES = ["designed", "awaiting_parts", "parts_ready", "listed", "sold"]
STATUS_LABEL = {"designed": "Designed", "awaiting_parts": "Awaiting parts", "parts_ready": "Parts ready",
                "listed": "Listed", "sold": "Sold"}
CATEGORIES = ["case", "bezel_insert", "bracelet", "movement", "hands", "dial", "other"]
PART_STATUSES = ["planned", "ordered", "delivered"]
# Mirrors lambdas/api/core/lifecycle.ALLOWED for the UI; the API is the real gate.
NEXT = {"designed": ["awaiting_parts", "parts_ready"], "awaiting_parts": ["designed", "parts_ready"],
        "parts_ready": ["awaiting_parts", "listed"], "listed": ["parts_ready"], "sold": []}


def usd(v) -> str:
    return "" if v in (None, "") else f"${float(v):,.2f}"


def esc(s: str) -> str:
    """st.markdown treats 2+ '$' as KaTeX."""
    return s.replace("$", "\$")


def page(title: str):
    st.set_page_config(page_title=f"Moonswitch - {title}", page_icon="🌙", layout="wide")
    st.title(title)
