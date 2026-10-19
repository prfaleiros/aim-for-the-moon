# Moonswitch — Project Context

Personal side-hustle app for Paulo: sources watch parts (AliExpress/DHGate), assembles
("recases") modded watches — mostly MoonSwatch-style builds, plus the occasional custom piece —
and flips them on Facebook Marketplace. Replaces a control spreadsheet. Paulo is making money
faster here than in his other business, so the goal is rigor and discipline: real cost
tracking, pricing by payment channel, calibration of target vs actual price, standardized
listings.

**This is a completely separate business and repo from `C:\dev\jdm-watch-business`** (JDM
watches bought on Buyee, sold on eBay/Chrono24). Do not import from, edit, or deploy anything
in that repo. Where the JDM code has a useful pattern (fee engine, clickable watch picker,
order/invoice importer, allocation of shared costs), **copy it into this repo and own it** — a
fix for one business must never ripple into the other. Read-only reference is fine.

**Start here:** read `DESIGN.md` (approved-pending data model, pages, build order). Phase 1 is
the next step; nothing is built yet.

## Working with Paulo

- Senior data/backend engineer by day (AWS, Lambda, Python, PostgreSQL). Weak spots: frontend,
  and CDK/IaC (new to him). Explain the "why", not the "what". Direct, no hand-holding.
- Windows, **Git Bash** — Unix shell syntax, forward slashes.
- Side hustle, not a startup: **don't over-engineer**; ask whether current volume justifies a
  new service/pattern before adding one. State a concern once, then defer to his call.
- **Don't raise the legal/LLC/sales-tax-permit angle** — he knows and is deferring it. (The
  replica-watch/Facebook-policy exposure was already flagged once and acknowledged; don't
  repeat it.)
- Never give him a command with a guessed/placeholder AWS resource name — look it up or give
  a lookup command.
- For data-extraction/lookup asks, give the leanest useful format (a table), not a polished doc.
- **`export AWS_PROFILE=prfaleiros`** before any CDK/AWS CLI command (default profile is stale).
- Human-edited config files default to CSV; machine config (fees, channels) is JSON.
- Before deploying (CDK) or writing to production data, show him the diff / dry-run first.

## Decisions already made

- Own AWS stack (`MoonswitchStack`), own DynamoDB table, own API + API key, own S3 buckets.
- Own Streamlit Community Cloud app (main file `app/app.py` — or as DESIGN.md says), own URL,
  viewer allowlist restricted to Paulo's email. Auto-redeploys on push to `main`.
- **Both repos are public on GitHub** (Paulo's call; can be flipped to private, Streamlit Cloud
  deploys either). No real sale figures, AliExpress links or buyer data in git: the original Excel
  and `data/import_overrides.csv` live in the gitignored `data/` folder; API URL/key only in
  Streamlit secrets.
- Fee model (confirmed): platform fee is charged on sale price **plus** buyer sales tax (and
  shipping charged), then deducted from the payout. Facebook checkout 10%, PayPal 2.99% (no
  flat fee), Zelle/Venmo/cash 0%. Not every sale goes through Facebook — each buyer pays
  differently, so the **payment channel is an explicit field**. Buyer tax default overridable.
- Parts are individual records; unassigned delivered parts are stock (e.g. spare bezel
  inserts). Stems/spacers are deliberately not tracked. Own time/hours: optional only.
- Listing text for Facebook is generated from a config template (`config/config.json` -> `listing`;
  no FB API). Listing a build requires **target price AND list price** (independent: either may be
  higher) plus all listing details (model, inspired-by, aesthetics, case, bracelet, dial, bezel).
  Dimensions in the template are Paulo's own measurements, never vendor-title specs. No water-
  resistance or battery lines (untested / redundant). Price stays in the text (negotiation starts
  from it); regenerate after a change. Direct payment (Zelle/Venmo/cash) is preferred but not discounted.
- No-shows aren't recorded; a refund = move the build back to `parts_ready` with a note (no refunds so far).

## About the source spreadsheet (`data/moonswitch_control.xlsx`)

- `2026_08` = the live tab (badly named; one long-running list, not monthly). `Sheet1` = old
  "rough notes" — only its 5 SOLD rows matter (history, no dates); its other rows were recycled
  into the new tab. `Sheet2` = monthly revenue/profit summary (a per-month report to replace).
- Header (row 2–3): Model; then component groups **Case, Bezel Insert, Bracelet** each with
  sub-columns model / color / price / status; **Movement, Hands, Dial** with model / price /
  status. Status codes 0=design, 1=ordered, 2=delivered. "Case → model" holds the AliExpress
  link; price is the link price or the final post-order price (discounts/fees were spread by
  hand). Many parts are "included with case" (cost 0).
- Then: TOTAL (sum of prices), calc price (unused), target price, estimated cuts (= target ×
  0.9 − $10: 10% fee + ~$10 shipping assumption), target est. profit, lifecycle status
  (designed / awaiting parts / parts ready / listed / sold), then the sales record: sale date,
  month-year, sale price, sales tax $, tax %, **platform fees (holds a RATE: 0.1, 0.0299, 0 —
  not dollars)**, shipping label cost, payout, NET PROFIT, profit/cost, and an unnamed
  column = payout − estimated payout (conditionally formatted as a beat/miss flag).
- "Sale price" = item price + shipping charged to buyer (e.g. one sale: item $250 + $30
  shipping charged, UPS Next Day label ~$44 — Paulo absorbed ~$15). The design splits these
  into `item_price` and `shipping_charged`; for that row, import 250 + 30.
- One build is a custom (non-MoonSwatch) watch → `type = custom`, same bucket.

## Conventions to carry over from the JDM app (learned the hard way)

- Streamlit: `st.markdown/caption` with 2+ `$` mangles into KaTeX — escape as `\$`.
- Programmatically-set widgets need a stable `key=` bound to `st.session_state`.
- `st.column_config.NumberColumn` format: put `$` in the label, keep `format="%.2f"`.
- Lambda config is cached in memory — config.json changes need a cold start/redeploy.
- Recalc/derived-cost functions must be defensive (`_safe_float`, no bare `float()`) because
  an admin "quick patch" can put arbitrary text in any field.
- Stamp business-event dates (`listed_date`, `sale_date`) from lifecycle transitions — never
  derive "time to sell" from record age.
- Pick-a-watch UIs: a filterable clickable table, never a dropdown (dozens of items).
- Migrations/imports: dry-run by default, `--apply` to write, and *list* ambiguous rows for
  Paulo to fix instead of guessing.
