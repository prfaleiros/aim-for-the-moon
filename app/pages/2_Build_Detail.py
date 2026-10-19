import pandas as pd
import streamlit as st

import api_client as api
from common import CATEGORIES, NEXT, PART_STATUSES, STATUS_LABEL, esc, page, usd

page("Build")

bid = st.session_state.get("build_id")
if not bid:
    st.info("Pick a build from the Builds page.")
    st.page_link("pages/1_Builds.py", label="Go to Builds")
    st.stop()
try:
    b = api.get(f"/builds/{bid}")
    cfg = api.config()
except api.ApiError as e:
    st.error(str(e))
    st.page_link("pages/1_Builds.py", label="Back to Builds")
    st.stop()

status = b["status"]
st.page_link("pages/1_Builds.py", label="← All builds")
st.subheader(f"{b['nickname']}  ·  {STATUS_LABEL[status]}")
st.caption(esc(f"{b.get('family') or 'no family'} · {b.get('type', 'standard')}"
               + (f" · listed {b['listed_date']}" if b.get("listed_date") else "")
               + (f" · sold {b['sale_date']}" if b.get("sale_date") else "")))

m = st.columns(4)
m[0].metric("Parts cost", usd(b["cost"]))
m[1].metric("Target price", usd(b.get("target_price")) or "-")
m[2].metric("List price", usd(b.get("list_price")) or "-")
m[3].metric("Est. net payout", usd(b.get("estimated_net_payout")) or "-",
            help="Snapshot at listing: list price minus channel fee and an assumed label. Used for calibration.")
if b.get("refund_note"):
    st.warning(f"Refunded: {b['refund_note']}")


# ── listing (price, details and generated Facebook text) ─────────────────────────
def listing_panel():
    """Edit prices + listing details, see the generated text and per-channel payout. Used to list a build
    (parts_ready) and to keep the text handy / regenerate it after listing."""
    try:
        base = api.get(f"/builds/{bid}/listing")
    except api.ApiError as e:
        st.error(str(e))
        return
    k = lambda name: f"lst_{bid}_{name}"  # noqa: E731
    defaults = {"target": float(b.get("target_price") or 0), "price": float(b.get("list_price") or 0),
                **{f: base["fields"].get(f, "") for f in base["labels"]}}
    for name, val in defaults.items():
        st.session_state.setdefault(k(name), val)

    c = st.columns(2)
    c[0].number_input("Target price $", min_value=0.0, step=5.0, format="%.2f", key=k("target"),
                      help="Your baseline for this kind of build. Independent of the list price.")
    c[1].number_input("List price $", min_value=0.0, step=5.0, format="%.2f", key=k("price"),
                      help="The asking price on the listing; the sale price is whatever you negotiate.")
    st.markdown("**Listing details**")
    fields = {}
    names = [f for f in base["labels"] if f != "extras"]
    for row in (names[:3], names[3:]):
        cols = st.columns(len(row))
        for col, f in zip(cols, row):
            fields[f] = col.text_input(base["labels"][f], key=k(f))
    fields["extras"] = st.text_area(base["labels"]["extras"], key=k("extras"), height=80,
                                    help="Optional bullets added to the feature list, e.g. an extra strap.")

    price = st.session_state[k("price")]
    try:
        view = api.post(f"/builds/{bid}/listing-preview", {"fields": fields, "list_price": price})
    except api.ApiError as e:
        st.error(str(e))
        return
    if view["missing"]:
        st.warning("Still needed: " + ", ".join(base["labels"][m] for m in view["missing"]))

    st.markdown("**Title**")
    st.code(view["title"], language=None)
    st.caption(f"{len(view['title'])} characters")
    st.markdown("**Description**")
    st.code(view["description"], language=None)

    st.markdown("**Estimated payout at this list price**")
    st.caption("After the channel fee (default buyer tax) and an assumed shipping label; profit also subtracts parts cost.")
    st.dataframe(pd.DataFrame(view["payouts"])[["label", "fee", "net_payout", "profit"]], hide_index=True,
                 use_container_width=True, column_config={
                     "label": "Channel", "fee": st.column_config.NumberColumn("Fee $", format="%.2f"),
                     "net_payout": st.column_config.NumberColumn("Net payout $", format="%.2f"),
                     "profit": st.column_config.NumberColumn("Profit $", format="%.2f")})

    target = st.session_state[k("target")]
    body = {"target_price": target or "", "list_price": price or "", "listing": fields}
    if status == "parts_ready":
        blocked = not target or not price or bool(view["missing"])
        if st.button("Mark as listed", type="primary", disabled=blocked, key=k("go"),
                     help="Needs a target price, a list price and all listing details."):
            if api.run(api.post, f"/builds/{bid}/transition", {"status": "listed", **body}, success="Listed"):
                st.rerun()
    elif st.button("Save listing details", key=k("save")):
        if api.run(api.patch, f"/builds/{bid}", body, success="Saved"):
            st.rerun()


# ── lifecycle ───────────────────────────────────────────────────────────────────
st.markdown("#### Status")
if status == "listed":
    st.caption("Listed. Record the sale below, or take it back to parts ready.")
for nxt in NEXT[status]:
    if nxt == "listed":
        continue
    if st.button(f"→ {STATUS_LABEL[nxt]}", key=f"to_{nxt}"):
        if api.run(api.post, f"/builds/{bid}/transition", {"status": nxt}):
            st.rerun()

if status in ("parts_ready", "listed"):
    with st.expander("List it" if status == "parts_ready" else "Listing text", expanded=status == "parts_ready"):
        listing_panel()

if status == "listed":
    with st.form("close_sale"):
        st.markdown("**Close sale**")
        c = st.columns(3)
        item = c[0].number_input("Item price $", min_value=0.0, step=5.0, format="%.2f", value=float(b.get("list_price") or 0))
        ship = c[1].number_input("Shipping charged to buyer $", min_value=0.0, step=1.0, format="%.2f")
        label = c[2].number_input("Shipping label cost $", min_value=0.0, step=1.0, format="%.2f")
        channels = cfg["channels"]
        channel = st.radio("Payment channel", list(channels), format_func=lambda k: channels[k]["label"],
                           index=list(channels).index(cfg["default_channel"]), horizontal=True)
        o = st.columns(2)
        tax = o[0].number_input("Buyer sales tax $ (blank = default rate)", min_value=0.0, step=1.0, format="%.2f", value=None)
        fee = o[1].number_input("Platform fee $ (blank = calculated)", min_value=0.0, step=1.0, format="%.2f", value=None)
        if st.form_submit_button("Mark sold", type="primary"):
            body = {"item_price": item, "shipping_charged": ship, "label_cost": label, "channel": channel}
            if tax is not None:
                body["sales_tax"] = tax
            if fee is not None:
                body["fee_usd"] = fee
            if api.run(api.post, f"/builds/{bid}/close", body, success="Sale recorded"):
                st.rerun()

if status == "sold":
    ch = cfg["channels"].get(b.get("channel"), {}).get("label", b.get("channel"))
    s = st.columns(5)
    s[0].metric("Sold for", usd((b.get("item_price") or 0) + (b.get("shipping_charged") or 0)), help="Item + shipping charged")
    s[1].metric("Fee", usd(b.get("fee_usd")), help=f"Channel: {ch}")
    s[2].metric("Label", usd(b.get("label_cost")))
    s[3].metric("Net profit", usd(b.get("net_profit")))
    s[4].metric("ROI", f"{b['roi']:.0f}%" if b.get("roi") is not None else "-")
    if b.get("payout_vs_estimate") is not None:
        st.caption(f"Payout vs. estimate: {esc(usd(b['payout_vs_estimate']))}")
    with st.expander("Refund"):
        note = st.text_input("Note", key="refund_note")
        if st.button("Refund → parts ready"):
            if api.run(api.post, f"/builds/{bid}/transition", {"status": "parts_ready", "note": note}, success="Refunded"):
                st.rerun()

# ── details ─────────────────────────────────────────────────────────────────────
with st.expander("Details"):
    with st.form("details"):
        c = st.columns(3)
        nickname = c[0].text_input("Nickname", b["nickname"])
        family = c[1].text_input("Family", b.get("family") or "")
        types = ["standard", "custom"]
        typ = c[2].selectbox("Type", types, index=types.index(b.get("type", "standard")))
        c = st.columns(3)
        target = c[0].number_input("Target price $", min_value=0.0, step=5.0, format="%.2f", value=float(b.get("target_price") or 0))
        listp = c[1].number_input("List price $", min_value=0.0, step=5.0, format="%.2f", value=float(b.get("list_price") or 0))
        hours = c[2].number_input("Hours (optional)", min_value=0.0, step=0.5, value=float(b.get("hours") or 0))
        notes = st.text_area("Notes", b.get("notes") or "")
        if st.form_submit_button("Save"):
            if api.run(api.patch, f"/builds/{bid}", {"nickname": nickname, "family": family, "type": typ,
                                                     "target_price": target or "", "list_price": listp or "",
                                                     "hours": hours or "", "notes": notes}, success="Saved"):
                st.rerun()
    if b.get("price_log"):
        st.markdown("**List price changes**")
        st.dataframe(pd.DataFrame(b["price_log"]).rename(columns={"at": "When", "from": "From $", "to": "To $"}),
                     hide_index=True, use_container_width=True)

# ── parts ───────────────────────────────────────────────────────────────────────
st.markdown("#### Parts")
ACTIONS = ["keep", "return to stock", "delete"]
parts = b["parts"]
if parts:
    orig = pd.DataFrame(parts)
    for col in ("description", "color", "link"):
        if col not in orig:
            orig[col] = ""
    orig = orig.fillna({"description": "", "color": "", "link": ""})
    view = orig[["category", "description", "cost_usd", "status", "included_with_case", "color", "link"]].copy()
    view["action"] = "keep"
    edited = st.data_editor(
        view, hide_index=True, use_container_width=True, key=f"parts_{bid}",
        column_config={
            "category": st.column_config.SelectboxColumn("Category", options=CATEGORIES, required=True),
            "description": st.column_config.TextColumn("Description", width="large"), "color": "Color", "link": "Link",
            "cost_usd": st.column_config.NumberColumn("Cost $", format="%.2f", min_value=0.0),
            "included_with_case": st.column_config.CheckboxColumn("Included w/ case", help="Counts as $0"),
            "status": st.column_config.SelectboxColumn("Status", options=PART_STATUSES, required=True),
            "action": st.column_config.SelectboxColumn("Action", options=ACTIONS, required=True),
        })
    if st.button("Save part changes"):
        ok = True
        for i, part in enumerate(parts):
            row = edited.iloc[i]
            if row["action"] == "delete":
                ok &= api.run(api.delete, f"/parts/{part['id']}")
            elif row["action"] == "return to stock":
                ok &= api.run(api.patch, f"/parts/{part['id']}", {"build_id": ""})
            else:
                changes = {}
                for col in ("category", "description", "color", "link", "status"):
                    if (row[col] or "") != (orig.iloc[i][col] or ""):
                        changes[col] = row[col]
                if float(row["cost_usd"] or 0) != float(orig.iloc[i]["cost_usd"] or 0):
                    changes["cost_usd"] = float(row["cost_usd"] or 0)
                if bool(row["included_with_case"]) != bool(orig.iloc[i]["included_with_case"]):
                    changes["included_with_case"] = bool(row["included_with_case"])
                if changes:
                    ok &= api.run(api.patch, f"/parts/{part['id']}", changes)
        if ok:
            st.toast("Parts saved")
            st.rerun()
else:
    st.info("No parts yet.")

with st.expander("Add a new part"):
    with st.form("add_part", clear_on_submit=True):
        c = st.columns(4)
        cat = c[0].selectbox("Category", CATEGORIES)
        desc = c[1].text_input("Description")
        color = c[2].text_input("Color")
        cost = c[3].number_input("Cost $", min_value=0.0, step=1.0, format="%.2f")
        c = st.columns(3)
        link = c[0].text_input("Link")
        pstat = c[1].selectbox("Status", PART_STATUSES)
        inc = c[2].checkbox("Included with case ($0)")
        if st.form_submit_button("Add part"):
            if api.run(api.post, "/parts", {"category": cat, "description": desc, "color": color, "link": link,
                                            "cost_usd": 0 if inc else cost, "included_with_case": inc,
                                            "status": pstat, "build_id": bid}, success="Part added"):
                st.rerun()

with st.expander("Assign from stock"):
    try:
        stock = api.get("/stock")
    except api.ApiError as e:
        stock = []
        st.error(str(e))
    if not stock:
        st.caption("No delivered, unassigned parts in stock.")
    else:
        sdf = pd.DataFrame(stock).reindex(columns=["category", "description", "color", "cost_usd"]).fillna("")
        sel = st.dataframe(sdf, hide_index=True, use_container_width=True, on_select="rerun",
                           selection_mode="multi-row", key=f"stock_pick_{bid}",
                           column_config={"cost_usd": st.column_config.NumberColumn("Cost $", format="%.2f")})
        if sel.selection.rows and st.button(f"Assign {len(sel.selection.rows)} selected"):
            if all(api.run(api.patch, f"/parts/{stock[i]['id']}", {"build_id": bid}) for i in sel.selection.rows):
                st.rerun()
