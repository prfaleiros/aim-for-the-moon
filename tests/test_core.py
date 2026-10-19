import sys, json, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "lambdas" / "api"))

import pytest
from core import fees, costs, lifecycle

CFG = json.loads((pathlib.Path(__file__).parent.parent / "config" / "config.json").read_text())


def test_fb_fee_on_price_plus_shipping_plus_tax():
    # $250 item + $30 shipping, 8% tax on 280 = 22.40; fee 10% of 302.40 = 30.24
    b = fees.sale_breakdown(CFG, {"item_price": 250, "shipping_charged": 30, "channel": "fb_checkout", "label_cost": 44}, 100)
    assert b["sales_tax"] == 22.40
    assert b["fee_usd"] == 30.24
    assert b["payout"] == 249.76
    assert b["net_profit"] == 105.76  # 249.76 - 44 - 100


def test_paypal_no_flat_fee():
    b = fees.sale_breakdown(CFG, {"item_price": 100, "channel": "paypal", "sales_tax": 0}, 0)
    assert b["fee_usd"] == 2.99


def test_direct_zero_fee_and_overrides():
    assert fees.sale_breakdown(CFG, {"item_price": 100, "channel": "direct"}, 40)["fee_usd"] == 0
    b = fees.sale_breakdown(CFG, {"item_price": 100, "channel": "fb_checkout", "sales_tax": 5, "fee_usd": 9.99}, 40)
    assert b["fee_usd"] == 9.99 and b["sales_tax"] == 5


def test_garbage_fields_do_not_crash():
    b = fees.sale_breakdown(CFG, {"item_price": "abc", "label_cost": "??", "channel": "direct"}, "n/a")
    assert b["net_profit"] == 0 and b["roi"] is None


def test_price_for_net_round_trips():
    p = fees.price_for_net(CFG, 100, "fb_checkout")
    assert fees.estimated_net_payout(CFG, p, "fb_checkout") == pytest.approx(100, abs=0.02)
    assert fees.price_for_net(CFG, 100, "direct") < p  # cash can be priced lower


def test_build_cost_skips_included_parts():
    parts = [{"cost_usd": 40}, {"cost_usd": "12.5"}, {"cost_usd": 99, "included_with_case": True}, {"cost_usd": "bad"}]
    assert costs.build_cost(parts) == 52.5


def test_auto_status():
    done = [{"status": "delivered"}, {"status": "delivered"}]
    part = done + [{"status": "ordered"}]
    assert lifecycle.auto_status("awaiting_parts", done) == "parts_ready"
    assert lifecycle.auto_status("parts_ready", part) == "awaiting_parts"
    assert lifecycle.auto_status("listed", part) == "listed"


def test_transitions_stamp_dates_and_refund():
    b = {"status": "parts_ready"}
    up = lifecycle.transition(b, "listed")
    assert up["listed_date"]
    b.update(up)
    assert "listed_date" not in lifecycle.transition({**b, "status": "parts_ready"}, "listed")  # first listing only
    sold = lifecycle.transition(b, "sold")
    assert sold["sale_date"]
    refund = lifecycle.transition({**b, **sold}, "parts_ready", note="buyer returned")
    assert refund["status"] == "parts_ready" and refund["refund_note"] == "buyer returned"
    with pytest.raises(ValueError):
        lifecycle.transition({"status": "designed"}, "sold")
