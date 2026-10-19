import pandas as pd
import streamlit as st

import api_client as api
from common import CATEGORIES, PART_STATUSES, esc, page

page("Stock")
st.caption("Delivered parts not assigned to a build (spare bezel inserts, etc.). Assign them from a build's page.")

try:
    stock = api.get("/stock")
except api.ApiError as e:
    st.error(str(e))
    st.stop()

if stock:
    df = pd.DataFrame(stock).reindex(columns=["category", "description", "color", "cost_usd", "link"])
    st.dataframe(df.fillna(""), hide_index=True, use_container_width=True,
                 column_config={"cost_usd": st.column_config.NumberColumn("Cost $", format="%.2f")})
    st.metric("Stock value", esc(f"${df['cost_usd'].fillna(0).sum():,.2f}"))
else:
    st.info("No parts in stock.")

with st.expander("Add a stock part"):
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
