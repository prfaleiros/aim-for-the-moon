import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "lambdas" / "api"))

from core import orders  # noqa: E402
from test_api import LISTING, _days_ago, api  # noqa: E402,F401  (api is a fixture)

# The three AliExpress receipts of 2026-10-19: (lines, discount, shipping, tax, total paid)
RECEIPT_STRAP = ([{"description": "Curved End Leather Strap", "unit_price": 25.89, "category": "bracelet"}], 0.52, 0, 2.40, 27.77)
RECEIPT_CASE_BEZEL = ([{"description": "Silver Multifunctional 39.7mm Watch", "unit_price": 25.29, "category": "case"},
                       {"description": "38.5mm * 34mm Bezel Aluminum", "unit_price": 5.85, "category": "bezel_insert"}],
                      0.31, 0, 2.92, 33.75)
RECEIPT_BRACELET = ([{"description": "Waterproof Solid Stainless Steel Watch Strap", "unit_price": 19.59,
                      "category": "bracelet"}], 0.20, 0, 1.84, 21.23)


def _body(receipt, ref, vendor="Tannew Watch Accessories Store", **extra):
    lines, discount, shipping, tax, paid = receipt
    return {"vendor": vendor, "order_ref": ref, "order_date": _days_ago(0), "discount": discount,
            "shipping": shipping, "tax": tax, "total_paid": paid, "lines": lines, **extra}


# ── allocation maths ────────────────────────────────────────────────────────────

def test_allocate_sums_exactly_with_largest_remainder():
    assert orders.allocate([100, 100, 100], 100) == [34, 33, 33]  # 33.33 each: the extra cent goes to the first
    shares = orders.allocate([2529, 585], 3375)
    assert shares == [2741, 634] and sum(shares) == 3375
    with pytest.raises(ValueError):
        orders.allocate([0, 0], 100)


@pytest.mark.parametrize("receipt,expected", [(RECEIPT_STRAP, [27.77]), (RECEIPT_CASE_BEZEL, [27.41, 6.34]),
                                              (RECEIPT_BRACELET, [21.23])])
def test_real_receipts_add_up(receipt, expected):
    lines, discount, shipping, tax, paid = receipt
    res = orders.build(lines, discount, shipping, tax, paid)
    assert res["error"] is None
    assert [p["cost_usd"] for p in res["parts"]] == expected
    assert round(sum(p["cost_usd"] for p in res["parts"]), 2) == paid


def test_receipt_that_does_not_add_up_is_flagged():
    lines, discount, shipping, tax, _ = RECEIPT_CASE_BEZEL
    res = orders.build(lines, discount, shipping, tax, 35.00)
    assert "total paid is 35.00" in res["error"] and "33.75" in res["error"]


def test_quantity_makes_one_part_per_unit():
    res = orders.build([{"description": "Hands", "unit_price": 4, "qty": 3, "category": "hands"}], 0, 0, 1.20, 13.20)
    assert [p["cost_usd"] for p in res["parts"]] == [4.40, 4.40, 4.40]
    for bad in ({"description": "", "unit_price": 1}, {"description": "x", "unit_price": 1, "qty": 0},
                {"description": "x", "unit_price": 1, "qty": "two"}):
        with pytest.raises(ValueError):
            orders.build([bad], 0, 0, 0, 1)


# ── API ─────────────────────────────────────────────────────────────────────────

def test_preview_writes_nothing_and_reports_math(api):
    s, d = api("POST", "/orders/preview", _body(RECEIPT_CASE_BEZEL, "8214909601541700"))
    assert s == 200 and d["error"] is None and [p["cost_usd"] for p in d["parts"]] == [27.41, 6.34]
    bad = {**_body(RECEIPT_CASE_BEZEL, "8214909601541700"), "total_paid": 40}
    assert api("POST", "/orders/preview", bad)[1]["error"]
    assert api("GET", "/orders")[1] == []


def test_create_order_makes_parts_on_order(api):
    s, o = api("POST", "/orders", _body(RECEIPT_CASE_BEZEL, "8214909601541700"))
    assert s == 201 and len(o["parts"]) == 2
    assert {p["status"] for p in o["parts"]} == {"ordered"} and {p["order_id"] for p in o["parts"]} == {o["id"]}
    case = next(p for p in o["parts"] if p["category"] == "case")
    assert case["cost_usd"] == 27.41 and case["item_price"] == 25.29 and case["vendor"] == "Tannew Watch Accessories Store"
    row = api("GET", "/orders")[1][0]
    assert row["status"] == "on_order" and row["parts_total"] == 2 and row["parts_delivered"] == 0
    assert api("GET", "/stock")[1] == []  # on-order parts are not stock until they arrive


def test_stock_include_ordered_flag(api):
    api("POST", "/orders", _body(RECEIPT_STRAP, "1"))
    import handler
    status, rows = handler.stock({}, {"include_ordered": "1"})
    assert status == 200 and len(rows) == 1 and rows[0]["status"] == "ordered"
    assert handler.stock({}, {})[1] == []


def test_order_validation_and_duplicates(api):
    assert api("POST", "/orders", {**_body(RECEIPT_STRAP, "1"), "total_paid": 99})[0] == 400  # does not add up
    assert api("POST", "/orders", {**_body(RECEIPT_STRAP, "1"), "vendor": ""})[0] == 400
    assert api("POST", "/orders", {**_body(RECEIPT_STRAP, "1"), "order_date": "2999-01-01"})[0] == 400
    bad_cat = _body(RECEIPT_STRAP, "1")
    bad_cat["lines"] = [{**bad_cat["lines"][0], "category": "nope"}]
    assert api("POST", "/orders", bad_cat)[0] == 400
    assert api("POST", "/orders", {**_body(RECEIPT_STRAP, "1"), "lines": []})[0] == 400
    assert api("POST", "/orders", _body(RECEIPT_STRAP, "1"))[0] == 201
    s, d = api("POST", "/orders", _body(RECEIPT_STRAP, "1"))  # same store + order id again
    assert s == 409 and "already entered" in d["error"]
    assert api("POST", "/orders", _body(RECEIPT_STRAP, "2"))[0] == 201  # different id is fine
    assert api("GET", "/builds")[1] == []  # nothing else was touched


def test_deliver_flips_parts_and_completes_builds(api):
    _, b = api("POST", "/builds", {"nickname": "Moon 7", "family": "Moon"})
    body = _body(RECEIPT_CASE_BEZEL, "42")
    body["lines"] = [{**body["lines"][0], "build_id": b["id"]}, {**body["lines"][1], "build_id": b["id"]}]
    _, o = api("POST", "/orders", body)
    api("POST", f"/builds/{b['id']}/transition", {"status": "awaiting_parts"})
    assert api("POST", f"/orders/{o['id']}/deliver", {"date": _days_ago(30)})[0] == 400  # before the order date
    s, d = api("POST", f"/orders/{o['id']}/deliver", {})
    assert s == 200 and d["status"] == "delivered" and d["delivered_date"] == _days_ago(0)
    assert api("GET", f"/builds/{b['id']}")[1]["status"] == "parts_ready"  # every part arrived
    assert api("GET", "/orders")[1][0]["parts_delivered"] == 2


def test_backdated_order_and_delivery(api):
    s, o = api("POST", "/orders", {**_body(RECEIPT_STRAP, "7"), "order_date": _days_ago(10)})
    assert s == 201
    s, d = api("POST", f"/orders/{o['id']}/deliver", {"date": _days_ago(4)})
    assert s == 200 and d["delivered_date"] == _days_ago(4)


def test_edit_amounts_reallocates_costs(api):
    _, o = api("POST", "/orders", _body(RECEIPT_CASE_BEZEL, "9"))
    assert api("PATCH", f"/orders/{o['id']}", {"tax": 5})[0] == 400  # no longer adds up to the total paid
    s, d = api("PATCH", f"/orders/{o['id']}", {"tax": 3.92, "total_paid": 34.75})
    assert s == 200 and round(sum(p["cost_usd"] for p in d["parts"]), 2) == 34.75
    s, d = api("PATCH", f"/orders/{o['id']}", {"vendor": "Mechanics Quartz Store", "notes": "split shipment"})
    assert d["vendor"] == "Mechanics Quartz Store" and {p["vendor"] for p in d["parts"]} == {"Mechanics Quartz Store"}
    api("POST", "/orders", _body(RECEIPT_STRAP, "10", vendor="Mechanics Quartz Store"))
    assert api("PATCH", f"/orders/{o['id']}", {"order_ref": "10"})[0] == 409  # would collide with the other order


def test_delete_order_keep_or_delete_parts(api):
    _, o = api("POST", "/orders", _body(RECEIPT_CASE_BEZEL, "11"))
    assert api("DELETE", f"/orders/{o['id']}", {"confirm": "wrong"})[0] == 400
    assert api("DELETE", f"/orders/{o['id']}", {"confirm": "11", "parts": "bogus"})[0] == 400
    s, d = api("DELETE", f"/orders/{o['id']}", {"confirm": "11", "parts": "keep"})
    assert s == 200 and d["parts"] == 2 and api("GET", "/orders")[1] == []
    import handler
    assert len(handler.stock({}, {"include_ordered": "1"})[1]) == 2  # kept as plain, unassigned parts
    _, o2 = api("POST", "/orders", _body(RECEIPT_STRAP, "12"))
    api("DELETE", f"/orders/{o2['id']}", {"confirm": "12"})  # default deletes the parts too
    assert len(handler.stock({}, {"include_ordered": "1"})[1]) == 2
