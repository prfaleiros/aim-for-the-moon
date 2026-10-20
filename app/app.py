"""Entry point (Streamlit Cloud main file). Pages live in pages/; st.navigation gives them proper names."""
import streamlit as st

pg = st.navigation([
    st.Page("pages/1_Builds.py", title="Builds", icon="🌙", default=True),
    st.Page("pages/2_Build_Detail.py", title="Build detail", icon="🔧"),
    st.Page("pages/5_Orders.py", title="Parts orders", icon="🧾"),
    st.Page("pages/3_Stock.py", title="Stock", icon="📦"),
    st.Page("pages/4_Financials.py", title="Financials", icon="💵"),
])
pg.run()
