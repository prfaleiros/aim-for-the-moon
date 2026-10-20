import pandas as pd
import streamlit as st

import api_client as api
from common import CATEGORIES, PART_STATUSES, STATUSES, STATUS_LABEL, esc, page

page("Stock")
st.caption("Parts not assigned to a build: ordered and still on the way, or delivered and waiting. "
           "Pick parts and a build, then assign.")

try:
    parts = api.get("/stock?include_ordered=1")
    builds = api.get("/builds")
except api.ApiError as e:
    st.error(str(e))
    st.stop()

if not parts:
    st.info("No unassigned parts.")
else:
    df = pd.DataFrame(parts).reindex(columns=["status", "category", "description", "variant", "vendor", "cost_usd"])
    df["status"] = df["status"].map({"ordered": "On order", "delivered": "In stock"}).fillna("")
    delivered = sum(float(p.get("cost_usd") or 0) for p in parts if p["status"] == "delivered")
    on_order = sum(float(p.get("cost_usd") or 0) for p in parts if p["status"] == "ordered")
    m = st.columns(2)
    m[0].metric("In stock", esc(f"${delivered:,.2f}"))
    m[1].metric("On order", esc(f"${on_order:,.2f}"))

    st.markdown("**1. Pick parts**")
    psel = st.dataframe(df.fillna(""), hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row",
                        key="stock_parts", column_config={
                            "status": "Status", "category": "Category", "description": "Part", "variant": "Variant",
                            "vendor": "Store", "cost_usd": st.column_config.NumberColumn("Cost $", format="%.2f")})

    st.markdown("**2. Pick the build**")
    open_builds = sorted((b for b in builds if b["status"] != "sold"),
                         key=lambda b: (STATUSES.index(b["status"]), b["nickname"].lower()))
    bdf = pd.DataFrame([{"Build": b["nickname"], "Family": b.get("family") or "", "Status": STATUS_LABEL[b["status"]],
                         "Parts": f"{b['parts_delivered']}/{b['parts_total']}"} for b in open_builds])
    bsel = st.dataframe(bdf, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                        key="stock_builds")

    picked = psel.selection.rows
    if picked and bsel.selection.rows:
        target = open_builds[bsel.selection.rows[0]]
        if st.button(f"Assign {len(picked)} part(s) to {target['nickname']}", type="primary"):
            if all(api.run(api.patch, f"/parts/{parts[i]['id']}", {"build_id": target["id"]}) for i in picked):
                st.toast(f"Assigned to {target['nickname']}")
                st.rerun()
    else:
        st.caption("Select at least one part and a build to assign.")

with st.expander("Add a part by hand"):
    st.caption("For one-offs. Orders from a store go on the Parts orders page so their discount and tax are spread.")
    with st.form("add_stock", clear_on_submit=True):
        c = st.columns(4)
        cat = c[0].selectbox("Category", CATEGORIES)
        desc = c[1].text_input("Description")
        color = c[2].text_input("Color")
        cost = c[3].number_input("Cost $", min_value=0.0, step=1.0, format="%.2f")
        link = st.text_input("Link")
        pstat = st.selectbox("Status", PART_STATUSES, index=2, help="Only delivered parts count as stock")
        if st.form_submit_button("Add"):
            if api.run(api.post, "/parts", {"category": cat, "description": desc, "color": color, "link": link,
                                            "cost_usd": cost, "status": pstat}, success="Added"):
                st.rerun()
