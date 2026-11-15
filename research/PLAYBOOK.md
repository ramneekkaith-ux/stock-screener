# Equity research report playbook

How Claude turns a research pack into an institutional-style initiation report.
Model: the TTI deck (executive summary → business → industry → competition → 3 theses →
comps → DCF → valuation summary → risks & catalysts → appendix).

## Ground rules
1. **Every number comes from `pack.json` / `dcf.json` or a cited source.** Never type a figure from
   memory. If a figure can't be sourced, leave it out or label it "estimate" with the basis.
2. **Every slide has a source line.** Pack data = "Yahoo Finance via research pack, <date>";
   web facts = publisher + URL (also listed in Appendix B).
3. **Currency discipline.** Prices in the trading currency (UK: pence, shown as "p"); financials in
   the reporting currency, in millions. Say which on every table.
4. **Theses must be falsifiable.** Each thesis states what the market is missing, the evidence, and
   what would prove it wrong.
5. **Balance.** Risks get as much rigour as the theses. Mention the bear case explicitly.
6. **Status.** Every report is stamped *DRAFT – for internal review* and carries the disclaimer
   until a qualified person at the firm signs it off.

## Step 1 — Triage (before writing)
For each ticker in `research/queue.json`, read the pack's `news`, `filings`, `events`, and run 2–3
web searches (`"<name>" results`, `"<name>" acquisition OR offer`, `"<name>" investigation OR fraud`).
Drop the name (record why in `research/coverage.json`) if: an offer/merger is pending, there are
accounting/fraud allegations, auditor resignation or going-concern language, delisting, or the
business has changed so much that history is meaningless. Pick the best remaining names.

## Step 2 — Research
- **Annual report / 10-K** (US: `filings` 10-K link; UK: company IR site): segments with revenue and
  margin, geography split, strategy, KPIs, management targets, capital allocation policy.
- **Latest results + guidance** (8-K / RNS / results presentation), last earnings call if available.
- **Industry:** market size and growth (cite the research house), structural tailwinds and headwinds,
  one driver chart if a public series exists (FRED, ONS, Census, trade bodies).
- **Competition:** who they compete with (peers in the pack + any named in the annual report),
  differentiation, Porter's five forces.
- **News (last 12 months):** events that moved the stock → `annotations.json` for the price chart.
- **Ownership and management:** major holders and insiders from the pack; founder/CEO background.

## Step 3 — Valuation
1. Start from `dcf_inputs` (defaults with rationale). Change assumptions **only** with a written
   reason grounded in research (guidance, consensus, segment mix, capacity plans). Write them to
   `assumptions.json` as `{"overrides": {...}, "override_reasons": {...}}` and re-run
   `python -m research.dcf <T>`; then `python -m research.charts <T>`.
2. Check `dcf.json` → `flags`. Explain or fix each one.
3. Review the peer set in `pack.peers`: remove any that aren't real comparables (say why), add
   obvious ones the annual report names, and re-run if changed.
4. Target price = `dcf.target` unless research justifies a different weighting (state it).
   Rating bands: Buy > +15% upside, Sell < −10%, else Hold.

## Step 4 — The deck (16:9)
| # | Slide | Content | Data |
|---|---|---|---|
| 1 | Executive summary | Headline thesis (title), sub-headline, 4–5 narrative bullets; valuation summary box (PV of FCF, PV of TV, EV, net debt, equity value, value/share, target, upside, rating); 3-year price chart with 2–4 annotated events | `dcf.gordon`, `dcf.target`, `charts/price_3y.png` |
| 2 | Business overview | What they do, segments (revenue/EBIT share & margin), ownership table, key financials (revenue, EBIT margin, FCF), EV bridge | annual report, `pack.holders`, `charts/financials.png`, `pack.capital` |
| 3 | Industry overview | Market size & growth, tailwinds vs headwinds, one driver chart | web sources |
| 4 | Competitive analysis | Positioning chart (ROE vs revenue), moat, Porter's five forces | `charts/peers_roe_revenue.png` |
| 5–7 | Investment theses 1–3 | One thesis per slide: claim, evidence (chart/table), what the market misses, risk to thesis | research + pack |
| 8 | Comparable companies | Table: name, ticker, price, % of 52w high, mkt cap, EV, LTM revenue, EBITDA, margin, EV/Rev, EV/EBITDA, P/E; high/mean/median/low | `pack.peers`, `dcf.comps` |
| 9 | DCF | Forecast table (revenue, growth, EBITDA, tax, capex, ΔNWC, UFCF, discount factor, PV), key assumptions commentary, 5×5 sensitivity (WACC × g) | `dcf.forecast`, `dcf.inputs.rationale`, `dcf.sensitivity` |
| 10 | Valuation summary | Football field with current price and target; one line per method | `charts/football_field.png`, `dcf.football_field` |
| 11 | Risks & catalysts | 3 risks with mitigants; events path (dated catalysts: results dates, AGM, product launches, policy) | research, `pack.events` |
| 12 | Quant scorecard | Screener pillar scores and the metrics behind them | `pack.screen` |
| A | WACC | rf, beta (raw/adjusted), ERP, size premium, cost of equity, cost of debt, tax, weights, WACC | `dcf.inputs` |
| B | References | Every source by section | — |
| C | Disclaimer | Firm disclaimer, disclosures, analyst certification placeholder | — |

## Step 5 — Review
A separate reviewer agent (fresh context) checks every number on every slide against `pack.json`,
`dcf.json` and the cited URLs, checks the arithmetic (EV bridge, upside, totals), and lists issues.
Fix them, then record the report in `research/coverage.json` with date, rating and target.

## Step 6 — Build and publish the deck
1. `python -m research.charts <T>` (after any assumption change).
2. Create a Claude Slides deck titled "<Name> (<T>) – Initiation", upload the four charts in
   `research/packs/<T>/charts/` to it, and save their `/_blob/...` links as
   `research/packs/<T>/assets.json` (`price_3y`, `financials`, `peers`, `football_field`).
3. Write `research/packs/<T>/report.json` (same keys as the existing ones, e.g. `ITRN`).
4. `python -m research.render_slides <T>` → publish every file under `research/decks/<T>/project/`.
5. Record it in `research/coverage.json` (date, rating, target, price, deck link) and commit.
