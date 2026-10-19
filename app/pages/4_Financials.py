import pandas as pd
import streamlit as st

import api_client as api
from common import page

page("Financials")

try:
    fin = api.get("/reports/financials")
except api.ApiError as e:
    st.error(str(e))
    st.stop()


def money(label):
    return st.column_config.NumberColumn(label, format="%.2f")


st.markdown("#### By month")
st.caption("Revenue = item + shipping charged. Payout = what lands after fees and label (your Sheet2 'revenue'). "
           "'history' = old Sheet1 sales with no date.")
if fin["monthly"]:
    mdf = pd.DataFrame(fin["monthly"])
    st.dataframe(mdf, hide_index=True, width="stretch", column_config={
        "month": "Month", "sales": st.column_config.NumberColumn("Sales", format="%d"),
        "revenue": money("Revenue $"), "fees": money("Fees $"), "labels": money("Labels $"),
        "payout": money("Payout $"), "net_profit": money("Net profit $")})
    dated = mdf[mdf["month"] != "history"]
    if not dated.empty:
        st.bar_chart(dated.set_index("month")["net_profit"], y_label="Net profit $")
else:
    st.info("No sales yet.")

st.markdown("#### Target vs. actual, by family")
st.caption("Only sales that had a target price. Negative gap = sold below target; negative 'payout vs est.' = "
           "received less than the estimate made at listing time.")
if fin["by_family"]:
    fdf = pd.DataFrame(fin["by_family"])
    fdf["gap"] = fdf["avg_sold_vs_target"] - fdf["avg_target"]
    st.dataframe(fdf[["family", "sales", "avg_target", "avg_sold_vs_target", "gap", "avg_vs_estimate", "avg_net_profit"]],
                 hide_index=True, width="stretch", column_config={
                     "family": "Family", "sales": st.column_config.NumberColumn("Sales", format="%d"),
                     "avg_target": money("Avg target $"), "avg_sold_vs_target": money("Avg item price $"),
                     "gap": money("Price gap $"), "avg_vs_estimate": money("Payout vs est. $"),
                     "avg_net_profit": money("Avg net profit $")})

d = fin.get("avg_days_listed_to_sold")
st.metric("Avg days listed → sold", d if d is not None else "n/a",
          help="Needs a listed date, which the spreadsheet never recorded. Fills in for builds listed from now on.")
