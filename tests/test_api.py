import json, os, pathlib, sys

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "lambdas" / "api"))


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", "t")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="t", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"} for n in ("PK", "SK", "GSI1PK", "GSI1SK")],
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            GlobalSecondaryIndexes=[{"IndexName": "GSI1", "Projection": {"ProjectionType": "ALL"},
                                     "KeySchema": [{"AttributeName": "GSI1PK", "KeyType": "HASH"},
                                                   {"AttributeName": "GSI1SK", "KeyType": "RANGE"}]}])
        import db, handler
        db._table = None

        def call(method, path, body=None):
            r = handler.handler({"httpMethod": method, "path": path, "body": json.dumps(body) if body else None}, None)
            return r["statusCode"], json.loads(r["body"])
        yield call


LISTING = {"aesthetics": "a silver dial", "case": "silver stainless steel", "bracelet": "silver stainless steel",
           "dial_color": "white", "bezel": "black tachymeter"}


def test_full_lifecycle(api):
    s, b = api("POST", "/builds", {"nickname": "Moonshine", "family": "Moon", "target_price": 250, "list_price": 250})
    bid = b["id"]
    s, case = api("POST", "/parts", {"category": "case", "cost_usd": 40, "build_id": bid, "status": "ordered"})
    assert s == 201
    api("POST", "/parts", {"category": "dial", "cost_usd": "12.5", "build_id": bid, "status": "delivered"})
    # cannot list or mark parts_ready while a part is outstanding
    assert api("POST", f"/builds/{bid}/transition", {"status": "listed", "listing": LISTING})[0] == 400
    api("POST", f"/builds/{bid}/transition", {"status": "awaiting_parts"})
    # delivering the last part flips awaiting_parts -> parts_ready automatically
    api("PATCH", f"/parts/{case['id']}", {"status": "delivered"})
    _, d = api("GET", f"/builds/{bid}")
    assert d["status"] == "parts_ready" and d["cost"] == 52.5
    s, d = api("POST", f"/builds/{bid}/transition", {"status": "listed", "listing": LISTING})
    assert s == 200 and d["listed_date"] and d["estimated_net_payout"] > 0
    s, d = api("POST", f"/builds/{bid}/close", {"item_price": 250, "shipping_charged": 30, "channel": "fb_checkout", "label_cost": 44})
    assert s == 200 and d["status"] == "sold" and d["fee_usd"] == 30.24 and d["net_profit"] == 105.76 - 52.5 + 100
    _, fin = api("GET", "/reports/financials")
    assert fin["monthly"][0]["sales"] == 1
    # refund -> parts_ready, sale voided
    s, d = api("POST", f"/builds/{bid}/transition", {"status": "parts_ready", "note": "returned"})
    assert s == 200 and d["status"] == "parts_ready" and "item_price" not in d and "sale_date" not in d
    assert api("GET", "/reports/financials")[1]["monthly"] == []


def test_stock_and_unassign(api):
    _, b = api("POST", "/builds", {"nickname": "x"})
    _, p = api("POST", "/parts", {"category": "bezel_insert", "status": "delivered"})
    assert [i["id"] for i in api("GET", "/stock")[1]] == [p["id"]]
    api("PATCH", f"/parts/{p['id']}", {"build_id": b["id"]})
    assert api("GET", "/stock")[1] == []
    api("PATCH", f"/parts/{p['id']}", {"build_id": ""})
    assert len(api("GET", "/stock")[1]) == 1


def test_price_log_and_validation(api):
    _, b = api("POST", "/builds", {"nickname": "x", "list_price": 200})
    api("PATCH", f"/builds/{b['id']}", {"list_price": 180})
    assert api("GET", f"/builds/{b['id']}")[1]["price_log"][0]["to"] == 180
    assert api("POST", "/parts", {"category": "nope"})[0] == 400
    assert api("POST", "/builds", {})[0] == 400


def test_calibration_ignores_sales_without_target(api):
    _, b = api("POST", "/builds", {"nickname": "x", "family": "Moon", "target_price": 200, "list_price": 150})
    api("POST", "/parts", {"category": "case", "build_id": b["id"], "status": "delivered", "cost_usd": 10})
    api("POST", f"/builds/{b['id']}/transition", {"status": "parts_ready"})
    api("POST", f"/builds/{b['id']}/transition", {"status": "listed", "listing": LISTING})
    api("POST", f"/builds/{b['id']}/close", {"item_price": 180, "channel": "direct"})
    # a history sale (imported from Sheet1) has no target; the API can no longer create one, so write it directly
    import db, repo
    db.put(repo.build_item({"id": "hist1", "nickname": "old", "family": "Moon", "type": "standard", "status": "sold",
                            "item_price": 100, "net_profit": 40, "sale_date": "2026-09-01"}))
    fam = api("GET", "/reports/financials")[1]["by_family"][0]
    assert fam["sales"] == 2 and fam["avg_target"] == 200 and fam["avg_sold_vs_target"] == 180


def _ready_build(api, **fields):
    _, b = api("POST", "/builds", {"nickname": "Moon steel silver", "family": "Moon", **fields})
    api("POST", "/parts", {"category": "case", "build_id": b["id"], "status": "delivered", "cost_usd": 40, "color": "silver"})
    api("POST", f"/builds/{b['id']}/transition", {"status": "parts_ready"})
    return b["id"]


def test_listing_requires_target_and_price(api):
    bid = _ready_build(api)
    s, d = api("POST", f"/builds/{bid}/transition", {"status": "listed", "listing": LISTING})
    assert s == 400 and "target price and list price" in d["error"]
    s, d = api("POST", f"/builds/{bid}/transition", {"status": "listed", "listing": LISTING, "target_price": 175})
    assert s == 400  # still no list price
    # target and list price are independent: listing below target is fine
    s, d = api("POST", f"/builds/{bid}/transition",
               {"status": "listed", "listing": LISTING, "target_price": 175, "list_price": 150})
    assert s == 200 and d["status"] == "listed" and d["target_price"] == 175 and d["list_price"] == 150
    assert d["listing"]["bezel"] == "black tachymeter"


def test_listing_blocked_by_missing_details(api):
    bid = _ready_build(api, target_price=175, list_price=175)
    s, d = api("POST", f"/builds/{bid}/transition", {"status": "listed", "listing": {"aesthetics": "x"}})
    assert s == 400 and "Dial color" in d["error"] and "Bezel" in d["error"]
    assert api("GET", f"/builds/{bid}")[1]["status"] == "parts_ready"


def test_listing_preview_and_get(api):
    bid = _ready_build(api, target_price=175)
    s, d = api("POST", f"/builds/{bid}/listing-preview", {"fields": LISTING, "list_price": 180})
    assert s == 200 and d["missing"] == []
    assert d["title"] == "Custom Moon steel silver Mecaquartz Chronograph – Moon inspired – $180"
    assert d["fields"]["case"] == "silver stainless steel"  # edit wins over the part color prefill
    assert {p["channel"] for p in d["payouts"]} == {"fb_checkout", "paypal", "direct"}
    direct = next(p for p in d["payouts"] if p["channel"] == "direct")
    assert direct["fee"] == 0 and direct["net_payout"] == 170 and direct["profit"] == 130  # 180 - 10 label - 40 parts
    # preview wrote nothing; GET prefills the case color from the part
    d = api("GET", f"/builds/{bid}/listing")[1]
    assert d["fields"]["case"] == "silver" and "case" not in d["missing"] and "dial_color" in d["missing"]
