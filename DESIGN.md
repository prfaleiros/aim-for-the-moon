# Moonswitch — design (draft for approval, 2026-10-17)

Separate business from the JDM watches: sources parts (AliExpress/DHGate), assembles ("recases")
modded watches, flips them on Facebook Marketplace. Replaces the `2026_08` tab of the control
spreadsheet. Public repo → **no real figures, links or buyer data in the repo**; the Excel
import reads a local file.

## Isolation rules

- Own stack (`MoonswitchStack`), own DynamoDB table, own API + API key, own S3 buckets.
- Own Streamlit Cloud app: main file `moonswitch/app.py`, own `requirements.txt`, own URL and
  email allowlist.
- **Copy, don't import**, from the JDM code (db helpers, config loader, fee math, watch-picker
  pattern). A few dozen duplicated lines are cheaper than one business's change breaking the other.
- Own `moonswitch/CLAUDE.md`; the root `CLAUDE.md` stays JDM + a pointer.

```
moonswitch/
  CLAUDE.md  DESIGN.md
  cdk/        # MoonswitchStack
  lambdas/    # builds, parts, orders, sales, config, reports (+ shared/)
  app/        # Streamlit (app.py + pages/)
  config/config.json   # channels, fee rates, listing template, targets
  scripts/    # import_excel.py (local file, dry-run default)
```

## Data model (single table)

**BUILD** — the sellable unit (a MoonSwatch-style rep, or a one-off custom: `type` = standard | custom).
- `nickname`, `family` (Moon, Mercury, 1969…), `type`, `status`, `target_price`, `list_price`,
  `notes`, `thumbnail_key`, optional `hours` (profit/hour reported only when filled in).
- Status: `designed → awaiting_parts → parts_ready → listed → sold` (+ `shipped` if wanted).
  `awaiting_parts → parts_ready` is automatic once every assigned part is delivered.
- Dates stamped by transitions, not typed: `listed_date` (first listing), `sale_date`.
  List-price changes are logged on the build so we can see what price actually sells.
- Sale fields (below) live on the build, like JDM.

**PART** — every component is a part record: `category` (case, bezel_insert, bracelet, movement,
hands, dial, other), `description`, `link`, `color`, `cost_usd`, `included_with_case` (cost 0),
`status` (planned → ordered → delivered), `order_id`, `build_id` (null = **stock**).
- Build cost = sum of assigned parts. Stock = delivered parts with no build (your bezel inserts).
  Planning a build = assign from stock or add a planned part.
- Stems and spacers: not tracked (negligible). Optional flat per-build allowance in config, default 0.

**ORDER** — one AliExpress/DHGate order: vendor, date, lines, discount, fees, shipping, tax, total
paid. Allocation spreads order-level discounts/fees across its parts automatically (same pattern
as JDM shipments) — replaces the hand-distributed prices.

**Sale** (on the build): `item_price`, `shipping_charged` (what the buyer paid for shipping — e.g.
the $250 + $30 next-day sale), `sales_tax`, `channel`, `fee_usd` (calculated from channel,
overridable with the real figure), `label_cost`, `payout`, `net_profit`, `roi`,
`payout_vs_estimate`. Estimate = target payout snapshotted at listing time, for calibration.

**Channels** (config, like JDM `platforms`): `fb_checkout` 10% of (price + tax), `paypal` 2.99%,
`direct` (Zelle/Venmo/cash) 0%. Default buyer tax overridable per sale. Fee base includes
shipping charged. Adding a channel = config edit.

## Pages

Builds list (clickable picker, status filter, thumbnail) · Build detail (parts, photos,
transitions, close sale, listing text) · New Build · Stock (unassigned parts) · Orders (+ importer)
· Pricing (target price per channel; "price for same payout" — cash can be priced lower) ·
Financials (monthly summary replacing `Sheet2`; target-vs-actual calibration by family; margin by
case/movement combo; days listed→sold).

## Listing text

Facebook has no API → generate a copy/paste block + photos from the build's parts and a template
stored in config with `{placeholders}` (model, case, movement, bezel, bracelet, price…), so every
listing is worded the same. Optional Claude-written pitch line later, as in JDM.

## Order importer (phase 3)

Paste/upload an AliExpress/DHGate order (text or screenshot) → Claude extracts lines → you map
lines to parts → discounts/fees allocated. Built on the JDM Buyee-invoice parser pattern; expect
a few iterations on real orders.

## Build order

1. **Core:** stack, builds + parts + cost rollup, lifecycle with dates, close sale with channels,
   Financials (monthly + calibration), Excel import (28 builds in `2026_08`; the 5 sold rows in
   `Sheet1` as history with no dates; ambiguous rows listed for you to fix, like the JDM migration).
2. **Photos + listing text.**
3. **Orders + importer + allocation.**
4. **Designs/recipes** (create N builds from a template) and stock-aware planning.

## Not modelled (on purpose)

No-shows (no record) and old `Sheet1` statuses. A refund = move the build back to `listed`
with a note; if that becomes frequent, add a proper refund record.
