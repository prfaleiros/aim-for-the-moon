from datetime import date, timedelta

import pandas as pd
import streamlit as st

import api_client as api
from common import CATEGORIES, esc, page, usd

page("Parts orders")
st.caption("Enter what you ordered once; discount, shipping and tax are spread over the parts so each part carries "
           "its real cost. Assign the parts to builds on the Stock page or from a build.")

TODAY = date.today()
LATEST = TODAY + timedelta(days=1)  # server clock is UTC; the API allows one day of slack

try:
    order_list = api.get("/orders")
except api.ApiError as e:
    st.error(str(e))
    st.stop()

n = st.session_state.setdefault("order_form_n", 0)  # bump to reset the entry form after saving
k = lambda name: f"ord_{name}_{n}"  # noqa: E731

# ── new order ───────────────────────────────────────────────────────────────────
with st.expander("New order", expanded=not order_list):
    vendors = sorted({o["vendor"] for o in order_list}, key=str.lower)
    c = st.columns([2, 2, 1])
    vendor = c[0].selectbox("Store", vendors, index=None, accept_new_options=True, key=k("vendor"),
                            placeholder="Pick a store you have used, or type a new one")
    ref = c[1].text_input("Order ID", key=k("ref"), help="The vendor's order number. Used to catch double entry.")
    odate = c[2].date_input("Order date", value=TODAY, max_value=LATEST, key=k("date"))

    st.markdown("**Items**")
    blank = pd.DataFrame({"description": pd.Series(dtype="str"), "variant": pd.Series(dtype="str"),
                          "category": pd.Series(dtype="str"), "unit_price": pd.Series(dtype="float"),
                          "qty": pd.Series(dtype="int"), "link": pd.Series(dtype="str")})
    items = st.data_editor(
        blank, num_rows="dynamic", hide_index=True, width="stretch", key=k("items"),
        column_config={
            "description": st.column_config.TextColumn("Item", required=True, width="large"),
            "variant": st.column_config.TextColumn("Variant", help="e.g. 'brown-silver, 20x18mm'"),
            "category": st.column_config.SelectboxColumn("Category", options=CATEGORIES, required=True),
            "unit_price": st.column_config.NumberColumn("Unit price $", min_value=0.0, format="%.2f", required=True),
            "qty": st.column_config.NumberColumn("Qty", min_value=1, step=1, default=1, format="%d"),
            "link": st.column_config.TextColumn("Link"),
        })

    st.markdown("**Receipt totals**")
    c = st.columns(4)
    discount = c[0].number_input("Discount $", min_value=0.0, step=0.01, format="%.2f", key=k("discount"))
    shipping = c[1].number_input("Shipping $", min_value=0.0, step=0.01, format="%.2f", key=k("shipping"))
    tax = c[2].number_input("Tax $", min_value=0.0, step=0.01, format="%.2f", key=k("tax"))
    paid = c[3].number_input("Total paid $", min_value=0.0, step=0.01, format="%.2f", key=k("paid"),
                             help="What you were charged, exactly as on the receipt.")
    notes = st.text_input("Notes (optional)", key=k("notes"))

    # live check + allocation
    lines = []
    for _, row in items.iterrows():
        if not str(row.get("description") or "").strip() or pd.isna(row.get("category")) or pd.isna(row.get("unit_price")):
            continue
        qty = row.get("qty")
        lines.append({"description": row["description"], "variant": row.get("variant") or None,
                      "category": row["category"], "unit_price": float(row["unit_price"]),
                      "qty": 1 if pd.isna(qty) else int(qty), "link": row.get("link") or None})
    header = {"vendor": vendor or "", "order_ref": ref, "order_date": odate.isoformat(), "discount": discount,
              "shipping": shipping, "tax": tax, "total_paid": paid, "notes": notes}
    problem, preview = None, None
    if not vendor:
        problem = "Pick or type the store."
    elif not lines:
        problem = "Add at least one item (item name, category and price)."
    else:
        try:
            preview = api.post("/orders/preview", {**header, "lines": lines})
            problem = preview["error"]
            if preview.get("duplicate"):
                problem = f"Order {ref} from {vendor} is already entered."
        except api.ApiError as e:
            problem = str(e)

    if preview:
        pdf = pd.DataFrame(preview["parts"])[["description", "category", "item_price", "cost_usd"]]
        st.dataframe(pdf, hide_index=True, width="stretch", column_config={
            "description": "Part", "category": "Category",
            "item_price": st.column_config.NumberColumn("Item price $", format="%.2f"),
            "cost_usd": st.column_config.NumberColumn("Cost with discount, shipping & tax $", format="%.2f")})
    if problem:
        st.warning(esc(problem))
    elif preview:
        st.success(esc(f"Adds up: {usd(preview['subtotal'])} of items, discount, shipping and tax = "
                       f"{usd(preview['total_paid'])} paid."))
    if st.button("Save order", type="primary", disabled=bool(problem) or not preview, key=k("save")):
        try:
            api.post("/orders", {**header, "lines": lines})
        except api.ApiError as e:
            st.error(str(e))
        else:
            st.session_state["order_form_n"] = n + 1
            st.toast("Order saved. Its parts are now on order.")
            st.rerun()

# ── orders list + detail ────────────────────────────────────────────────────────
st.markdown("#### Orders")
if not order_list:
    st.info("No orders yet.")
    st.stop()

odf = pd.DataFrame([{"Date": o["order_date"], "Store": o["vendor"], "Order ID": o.get("order_ref") or "",
                     "Paid $": o["total_paid"], "Parts": f"{o['parts_delivered']}/{o['parts_total']}",
                     "Status": "Delivered" if o["status"] == "delivered" else "On order"} for o in order_list])
sel = st.dataframe(odf, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                   key="orders_table", column_config={"Paid $": st.column_config.NumberColumn("Paid $", format="%.2f")})
st.caption("Click an order to see its parts, mark it delivered, or fix it.")
if not sel.selection.rows:
    st.stop()

head = order_list[sel.selection.rows[0]]
oid = head["id"]
try:
    o = api.get(f"/orders/{oid}")
except api.ApiError as e:
    st.error(str(e))
    st.stop()

st.subheader(f"{o['vendor']}  ·  {o.get('order_ref') or 'no order id'}")
st.caption(esc(f"Ordered {o['order_date']} · paid {usd(o['total_paid'])} (discount {usd(o['discount'])}, shipping "
               f"{usd(o['shipping'])}, tax {usd(o['tax'])})"
               + (f" · delivered {o['delivered_date']}" if o.get("delivered_date") else "")
               + (f" · {o['notes']}" if o.get("notes") else "")))
pdf = pd.DataFrame(o["parts"]).reindex(columns=["category", "description", "variant", "item_price", "cost_usd", "status",
                                                "build_id"]).fillna("")
pdf["build_id"] = pdf["build_id"].map(lambda b: "assigned" if b else "")
st.dataframe(pdf, hide_index=True, width="stretch", column_config={
    "category": "Category", "description": "Part", "variant": "Variant", "status": "Status", "build_id": "Build",
    "item_price": st.column_config.NumberColumn("Item price $", format="%.2f"),
    "cost_usd": st.column_config.NumberColumn("Cost $", format="%.2f")})

if o["status"] != "delivered":
    c = st.columns([1, 1, 3])
    arrived = c[0].date_input("Arrived on", value=TODAY, min_value=date.fromisoformat(o["order_date"]), max_value=LATEST,
                              key=f"arr_{oid}", help="Defaults to today; pick the real day if you are recording it late.")
    c[1].write("")
    if c[1].button("Mark all delivered", type="primary", key=f"deliver_{oid}"):
        if api.run(api.post, f"/orders/{oid}/deliver", {"date": arrived.isoformat()}, success="Delivered"):
            st.rerun()
    st.caption("Builds whose parts are all delivered move to Parts ready automatically. For a split shipment, "
               "mark single parts delivered from the build page instead.")

with st.expander("Fix this order"):
    st.caption("Changing the amounts re-spreads discount, shipping and tax over the parts. The total must still add up.")
    with st.form(f"edit_{oid}"):
        c = st.columns(3)
        e_vendor = c[0].text_input("Store", o["vendor"])
        e_ref = c[1].text_input("Order ID", o.get("order_ref") or "")
        e_date = c[2].date_input("Order date", value=date.fromisoformat(o["order_date"]), max_value=LATEST)
        c = st.columns(4)
        e_disc = c[0].number_input("Discount $", min_value=0.0, step=0.01, format="%.2f", value=float(o["discount"]))
        e_ship = c[1].number_input("Shipping $", min_value=0.0, step=0.01, format="%.2f", value=float(o["shipping"]))
        e_tax = c[2].number_input("Tax $", min_value=0.0, step=0.01, format="%.2f", value=float(o["tax"]))
        e_paid = c[3].number_input("Total paid $", min_value=0.0, step=0.01, format="%.2f", value=float(o["total_paid"]))
        e_notes = st.text_input("Notes", o.get("notes") or "")
        if st.form_submit_button("Save changes"):
            if api.run(api.patch, f"/orders/{oid}", {"vendor": e_vendor, "order_ref": e_ref, "order_date": e_date.isoformat(),
                                                     "discount": e_disc, "shipping": e_ship, "tax": e_tax,
                                                     "total_paid": e_paid, "notes": e_notes}, success="Saved"):
                st.rerun()

st.divider()
with st.expander("Danger zone"):
    key_text = o.get("order_ref") or o["vendor"]
    st.markdown(f"**Delete this order.** This can't be undone. It has {len(o['parts'])} part(s).")
    mode = st.radio("Its parts", ["delete", "keep"], horizontal=True, key=f"od_mode_{oid}",
                    format_func={"delete": "Delete them too", "keep": "Keep them as plain parts"}.get,
                    help="Parts already assigned to a build change that build's cost when deleted.")
    confirm = st.text_input(f"Type {key_text} to confirm", key=f"od_confirm_{oid}")
    if st.button("Delete order", type="primary", disabled=confirm.strip() != key_text, key=f"od_go_{oid}"):
        if api.run(api.delete, f"/orders/{oid}", {"confirm": confirm, "parts": mode}, success="Order deleted"):
            st.rerun()
