#!/usr/bin/env python3
"""One-time load of data/moonswitch_control.xlsx into the Moonswitch table.

Dry-run by default: parses, reconciles against the sheet's own totals, prints what it would
write and every row it is unsure about. `--apply` writes (needs AWS_PROFILE=prfaleiros and
TABLE_NAME). Ids are deterministic (sheet + row), so a re-run overwrites rather than duplicates;
--apply refuses if the target ids already exist unless --force (the app is the source of truth
after the first load).

Row-specific facts that aren't in the sheet (e.g. the $250 item + $30 shipping split) live in the
gitignored data/import_overrides.csv, never in this file.
"""
import argparse
import csv
import json
import pathlib
import sys
from datetime import datetime

import openpyxl

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas" / "api"))

from core import costs, fees, lifecycle  # noqa: E402
from core.money import safe_decimal  # noqa: E402

XLSX = ROOT / "data" / "moonswitch_control.xlsx"
OVERRIDES = ROOT / "data" / "import_overrides.csv"
FAMILIES = ROOT / "config" / "families.csv"
CFG = {k: v for k, v in json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}

# (category, model col, color col, price col, status col) on tab 2026_08
GROUPS = [("case", 2, 3, 4, 5), ("bezel_insert", 6, 7, 8, 9), ("bracelet", 10, 11, 12, 13),
          ("movement", 14, None, 15, 16), ("hands", 17, None, 18, 19), ("dial", 20, None, 21, 22)]
C_NAME, C_TARGET, C_EST, C_STATUS, C_SALEDATE = 1, 25, 26, 28, 29
C_PRICE, C_TAX, C_FEERATE, C_LABEL, C_PAYOUT, C_NET, C_TOTAL = 31, 32, 34, 35, 36, 37, 23
PART_STATUS = {0: "planned", 1: "ordered", 2: "delivered"}
LIFECYCLE = {"sold": "sold", "listed": "listed", "parts ready": "parts_ready", "awaiting parts": "awaiting_parts",
             "designed": "designed"}
RATE_TO_CHANNEL = {0.1: "fb_checkout", 0.0299: "paypal", 0.0: "direct"}
TOL = 0.02


def f(v):
    d = safe_decimal(v)
    return float(d)


def num_or_none(v):
    try:
        return None if v is None or str(v).strip() == "" else float(v)
    except ValueError:
        return None


def load_families():
    with open(FAMILIES, newline="") as fh:
        return [(r["keyword"].lower(), r["family"]) for r in csv.DictReader(fh)]


def family_of(name, table):
    n = (name or "").lower()
    return next((fam for kw, fam in table if kw in n), None)


def load_overrides():
    if not OVERRIDES.exists():
        return {}
    with open(OVERRIDES, newline="") as fh:
        return {(r["sheet"], int(r["row"])): r for r in csv.DictReader(fh)}


class Report:
    def __init__(self):
        self.errors, self.notes, self.skipped = [], [], []

    def error(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def note(self, where, msg):
        self.notes.append(f"{where}: {msg}")

    def skip(self, where, msg):
        self.skipped.append(f"{where}: {msg}")


def parse_main(ws, families, overrides, rep):
    builds = []
    for r in range(5, ws.max_row + 1):
        name = ws.cell(r, C_NAME).value
        status_raw = ws.cell(r, C_STATUS).value
        if name is None or status_raw is None:  # blank row 30, totals rows 31-32
            continue
        where = f"2026_08 r{r} '{name}'"
        status = LIFECYCLE.get(str(status_raw).strip().lower())
        if not status:
            rep.error(where, f"unknown status '{status_raw}'")
            continue
        fam = family_of(name, families)
        if not fam:
            rep.error(where, "no family match in config/families.csv")

        parts, case_code = [], None
        for cat, mc, cc, pc, sc in GROUPS:
            model = ws.cell(r, mc).value
            text = str(model).strip() if model is not None else ""
            cost = f(ws.cell(r, pc).value)
            code = num_or_none(ws.cell(r, sc).value)
            if text.lower() == "n/a" or (not text and not cost):
                continue
            included = text.lower().startswith("included with case")
            if cat == "case":
                case_code = code
            if included:
                code, cost = case_code, 0.0  # an included part is delivered when the case is
            part = {"category": cat, "description": text or f"({cat}, no model name)", "cost_usd": round(cost, 2),
                    "included_with_case": included}
            if cc and ws.cell(r, cc).value:
                part["color"] = str(ws.cell(r, cc).value).strip()
            link = ws.cell(r, mc).hyperlink
            if link and link.target:
                part["link"] = link.target
            if not text:
                rep.note(where, f"{cat} has a price (${cost:.2f}) but no model name")
            if code is None:
                part["status"] = "delivered" if status == "sold" else "planned"
                rep.note(where, f"{cat} has no status code; set to {part['status']}")
            else:
                part["status"] = PART_STATUS.get(int(code), "planned")
            parts.append(part)

        undelivered = [p for p in parts if p["status"] != "delivered"]
        if status == "sold":
            for p in undelivered:
                rep.note(where, f"{p['category']} was '{p['status']}' on a SOLD build; set to delivered")
                p["status"] = "delivered"
        elif status in ("listed", "parts_ready") and undelivered:
            rep.note(where, f"is '{status}' but {', '.join(p['category'] + ':' + p['status'] for p in undelivered)}")
        cost = costs.build_cost(parts)
        sheet_total = ws.cell(r, C_TOTAL).value
        if sheet_total is not None and abs(cost - f(sheet_total)) > TOL:
            rep.error(where, f"parts total {cost:.2f} != sheet TOTAL {f(sheet_total):.2f}")

        target = num_or_none(ws.cell(r, C_TARGET).value)
        est = num_or_none(ws.cell(r, C_EST).value)
        b = {"id": f"s2026-r{r:02d}", "nickname": str(name).strip(), "family": fam, "type": "standard",
             "status": status, "target_price": target, "estimated_net_payout": est,
             "notes": "imported from spreadsheet tab 2026_08", "source": f"2026_08!r{r}",
             "created_at": lifecycle.now_iso()}
        if status == "listed":
            b["list_price"] = target  # the sheet only has one price; assumed to be the asking price
        if status == "sold":
            sale = parse_sale(ws, r, where, overrides, cost, est, rep)
            if sale is None:
                continue
            sd = ws.cell(r, C_SALEDATE).value
            if isinstance(sd, datetime):
                sale["sale_date"] = sd.date().isoformat()
            else:
                rep.error(where, "SOLD without a sale date")
            b.update(sale)
        builds.append({"build": b, "parts": parts, "cost": cost, "sheet_net": num_or_none(ws.cell(r, C_NET).value),
                       "sheet_payout": num_or_none(ws.cell(r, C_PAYOUT).value), "where": where})
    return builds


def parse_sale(ws, r, where, overrides, cost, est, rep):
    price = num_or_none(ws.cell(r, C_PRICE).value)
    if not price:
        rep.error(where, "SOLD without a sale price")
        return None
    ov = overrides.get(("2026_08", r))
    item, ship_charged = (float(ov["item_price"]), float(ov["shipping_charged"])) if ov else (price, 0.0)
    if ov and abs(item + ship_charged - price) > TOL:
        rep.error(where, f"override {item}+{ship_charged} != sheet sale price {price}")
        return None
    rate = num_or_none(ws.cell(r, C_FEERATE).value)
    channel = RATE_TO_CHANNEL.get(round(rate if rate is not None else -1, 4))
    if channel is None:
        rep.error(where, f"fee rate {rate!r} matches no channel in config.json")
        return None
    label = f(ws.cell(r, C_LABEL).value)
    sale = {"item_price": item, "shipping_charged": ship_charged, "channel": channel,
            "sales_tax": f(ws.cell(r, C_TAX).value), "label_cost": label}
    res = fees.sale_breakdown(CFG, sale, cost)
    sale.update(res)
    if est is not None:
        sale["payout_vs_estimate"] = round(res["payout"] - label - est, 2)
    sale["shipping_charged"] = ship_charged
    return sale


def parse_sheet1(ws, families, rep):
    out = []
    for r in range(3, ws.max_row + 1):
        status = ws.cell(r, 1).value
        if str(status).strip().upper() != "SOLD":
            continue
        name = str(ws.cell(r, 2).value).strip()
        where = f"Sheet1 r{r} '{name}'"
        sale_price = num_or_none(ws.cell(r, 9).value)
        if not sale_price:
            rep.skip(where, f"marked SOLD but sale = {sale_price}; pocket = {ws.cell(r, 10).value}. Not imported - fix or tell me")
            continue
        parts = []
        for cat, col, desc in (("movement", 3, "rep movement"), ("case", 4, "case"), ("bracelet", 5, "strap"),
                               ("other", 6, "others")):
            c = f(ws.cell(r, col).value)
            if c:
                parts.append({"category": cat, "description": desc, "cost_usd": round(c, 2),
                              "included_with_case": False, "status": "delivered"})
        cost = costs.build_cost(parts)
        invest = f(ws.cell(r, 7).value)
        if abs(cost - invest) > TOL:
            rep.error(where, f"parts total {cost:.2f} != sheet invest {invest:.2f}")
        label = f(ws.cell(r, 8).value)
        sale = {"item_price": sale_price, "shipping_charged": 0.0, "channel": "direct", "sales_tax": 0.0,
                "fee_usd": 0.0, "label_cost": label}
        res = fees.sale_breakdown(CFG, sale, cost)
        sale.update(res)
        rep.note(where, "no channel/fee/date in Sheet1: assumed direct, fee 0, no sale_date (shows as 'history')")
        fam = family_of(name, families)
        if not fam:
            rep.error(where, "no family match in config/families.csv")
        out.append({"build": {"id": f"s1-r{r:02d}", "nickname": name, "family": fam, "type": "standard",
                              "status": "sold", "notes": "history from Sheet1 (rough notes), no dates",
                              "source": f"Sheet1!r{r}", "created_at": lifecycle.now_iso(),
                              **sale},
                    "parts": parts, "cost": cost, "sheet_net": num_or_none(ws.cell(r, 10).value),
                    "sheet_payout": None, "where": where})
    return out


def reconcile(rows, wb, rep):
    for row in rows:
        b = row["build"]
        if b["status"] == "sold" and row["sheet_net"] is not None and abs(b["net_profit"] - row["sheet_net"]) > TOL:
            rep.error(row["where"], f"net profit {b['net_profit']:.2f} != sheet {row['sheet_net']:.2f}")
    # Sheet2: "revenue" = sum of payouts net of label, "profit" = sum of net profits, per sale month
    by_month = {}
    for row in rows:
        b = row["build"]
        if b["status"] == "sold" and b.get("sale_date") and row["build"]["source"].startswith("2026_08"):
            m = by_month.setdefault(b["sale_date"][:7], [0.0, 0.0])
            m[0] += b["payout"] - b["label_cost"]
            m[1] += b["net_profit"]
    lines = []
    for sr in wb["Sheet2"].iter_rows(min_row=2, values_only=True):
        if not isinstance(sr[0], datetime):
            continue
        key = sr[0].strftime("%Y-%m")
        mine = by_month.get(key, [0.0, 0.0])
        ok = abs(mine[0] - f(sr[2])) <= 0.5 and abs(mine[1] - f(sr[3])) <= 0.5
        lines.append(f"  {key}  revenue {mine[0]:9.2f} vs {f(sr[2]):9.2f}   profit {mine[1]:9.2f} vs {f(sr[3]):9.2f}   "
                     f"{'OK' if ok else 'MISMATCH'}")
        if not ok:
            rep.error(f"Sheet2 {key}", "monthly totals do not reconcile")
    return lines


def apply(rows, force):
    import db
    import repo
    existing = [r["build"]["id"] for r in rows if db.get(f"BUILD#{r['build']['id']}")]
    if existing and not force:
        sys.exit(f"{len(existing)} imported builds already exist (e.g. {existing[0]}); the app is the source of "
                 f"truth now. Re-run with --force to overwrite them.")
    n_parts = 0
    for row in rows:
        b = dict(row["build"])
        db.put(repo.build_item({k: v for k, v in b.items() if v is not None}))
        for i, p in enumerate(row["parts"]):
            part = {"id": f"{b['id']}-p{i}", "build_id": b["id"], **p}
            db.put(repo.part_item(part))
            n_parts += 1
    print(f"WROTE {len(rows)} builds, {n_parts} parts to {db.table().name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write to DynamoDB (default: dry run)")
    ap.add_argument("--force", action="store_true", help="overwrite builds that already exist")
    args = ap.parse_args()

    wb = openpyxl.load_workbook(XLSX, data_only=True)
    families, overrides, rep = load_families(), load_overrides(), Report()
    rows = parse_main(wb["2026_08"], families, overrides, rep) + parse_sheet1(wb["Sheet1"], families, rep)
    recon = reconcile(rows, wb, rep)

    print(f"{'id':<14}{'status':<14}{'family':<10}{'name':<26}{'parts':>5}{'cost':>9}{'target':>8}{'sold':>8}{'net':>9}")
    for r in rows:
        b = r["build"]
        print(f"{b['id']:<14}{b['status']:<14}{(b['family'] or '?'):<10}{b['nickname'][:25]:<26}{len(r['parts']):>5}"
              f"{r['cost']:>9.2f}{(b.get('target_price') or 0):>8.0f}"
              f"{(b.get('item_price', 0) + b.get('shipping_charged', 0)) or '':>8}{b.get('net_profit', ''):>9}")
    by_status = {}
    for r in rows:
        by_status[r["build"]["status"]] = by_status.get(r["build"]["status"], 0) + 1
    print(f"\n{len(rows)} builds, {sum(len(r['parts']) for r in rows)} parts  {by_status}")
    print("\nReconciliation vs Sheet2 (mine vs sheet):")
    print("\n".join(recon))
    for title, items in (("ERRORS (block --apply)", rep.errors), ("NOT IMPORTED", rep.skipped),
                         ("NOTES (imported, but check)", rep.notes)):
        print(f"\n{title}: {len(items)}")
        for i in items:
            print("  -", i)

    if not args.apply:
        print("\nDRY RUN - nothing written. Re-run with --apply to write.")
        return
    if rep.errors:
        sys.exit("\nRefusing to apply with errors above.")
    apply(rows, args.force)


if __name__ == "__main__":
    main()
