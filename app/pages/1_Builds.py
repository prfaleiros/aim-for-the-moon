import pandas as pd
import streamlit as st

import api_client as api
from common import STATUSES, STATUS_LABEL, page, usd

page("Builds")

try:
    builds = api.get("/builds")
except api.ApiError as e:
    st.error(f"Could not load builds: {e}")
    st.stop()

# ── summary strip ───────────────────────────────────────────────────────────────
counts = {s: sum(1 for b in builds if b["status"] == s) for s in STATUSES}
cols = st.columns(len(STATUSES))
for col, s in zip(cols, STATUSES):
    col.metric(STATUS_LABEL[s], counts[s])

# ── filter + clickable table (never a dropdown: dozens of builds) ──────────────
chosen = st.pills("Status", STATUSES, selection_mode="multi", default=[s for s in STATUSES if s != "sold"],
                  format_func=STATUS_LABEL.get, key="builds_status_filter")
rows = [b for b in builds if b["status"] in (chosen or STATUSES)]
rows.sort(key=lambda b: (STATUSES.index(b["status"]), b.get("nickname", "")))

df = pd.DataFrame([{
    "Build": b["nickname"], "Family": b.get("family") or "", "Status": STATUS_LABEL[b["status"]],
    "Parts": f"{b['parts_delivered']}/{b['parts_total']}", "Cost $": b["cost"],
    "Target $": b.get("target_price"), "List $": b.get("list_price"),
    "Sold $": (b.get("item_price") or 0) + (b.get("shipping_charged") or 0) or None,
    "Net $": b.get("net_profit"),
} for b in rows])

for c in ("Target $", "List $", "Sold $", "Net $"):
    df[c] = pd.to_numeric(df[c], errors="coerce")  # None in an object column renders as the text "None"

if df.empty:
    st.info("No builds match this filter.")
else:
    money = {c: st.column_config.NumberColumn(c, format="%.2f") for c in ("Cost $", "Target $", "List $", "Sold $", "Net $")}
    sel = st.dataframe(df, hide_index=True, use_container_width=True, on_select="rerun",
                       selection_mode="single-row", column_config=money, key="builds_table")
    st.caption("Click a row to open the build.")
    if sel.selection.rows:
        st.session_state["build_id"] = rows[sel.selection.rows[0]]["id"]
        st.switch_page("pages/2_Build_Detail.py")

# ── new build ───────────────────────────────────────────────────────────────────
with st.expander("New build"):
    with st.form("new_build", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        nickname = c1.text_input("Nickname")
        family = c2.text_input("Family (Moon, Mercury, 1969...)")
        typ = c3.selectbox("Type", ["standard", "custom"])
        target = st.number_input("Target price $", min_value=0.0, step=5.0, format="%.2f")
        notes = st.text_area("Notes")
        if st.form_submit_button("Create"):
            try:
                b = api.post("/builds", {"nickname": nickname, "family": family or None, "type": typ,
                                         "target_price": target or None, "notes": notes or None})
                st.session_state["build_id"] = b["id"]
                st.switch_page("pages/2_Build_Detail.py")
            except api.ApiError as e:
                st.error(str(e))
