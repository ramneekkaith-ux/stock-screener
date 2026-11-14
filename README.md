# Stock screener — US & UK small-cap fundamentals

A daily **fundamental** (not trading) screen of US and UK small caps using Yahoo Finance data.
It is a broad first pass: keep rubbish out, don't miss good businesses. It produces a shortlist
for research, not buy signals.

Runs every weekday morning on GitHub Actions; results land in `results/latest.json` (and `latest.csv`).
All thresholds live in [`screener/config.py`](screener/config.py).

## Methodology

### 1. Universe
- US (Nasdaq, NYSE, NYSE American) and UK (LSE Main Market + AIM) equities
- Market cap **$100M – $2B** (UK converted from pence → GBP → USD)
- 3-month average daily traded value ≥ **$50k**; listed ≥ **3 years**
- Excludes banks, insurers, REITs, investment trusts/asset managers, SPACs
  (kept from those sectors: capital markets, financial data & exchanges, insurance brokers, real-estate services)

### 2. Hard exclusions — clear rubbish only
| Rule | Out if |
|---|---|
| Operating cash flow | negative in 3+ of last 4 years |
| Revenue (TTM) | < $10M |
| Altman Z'' | < 1.1 (distress zone) |
| Dilution | share count growing > 15%/yr |
| Leverage | net debt / EBITDA > 4x, or net debt with negative EBITDA |

Missing data never excludes. Companies with < 2 years of statements are set aside as "insufficient data".

### 3. Score (0–100, absolute bands)
Each metric scores 0–10 against fixed bands; a missing metric scores a neutral 5 and the stock is
flagged "low data coverage" if < 70% of metrics exist.

| Pillar | Weight | Metrics |
|---|---|---|
| Growth consistency | 30% | 3-yr revenue CAGR · years with growth · steadiness (low volatility of growth) · latest YoY |
| Cash flow | 30% | FCF margin · FCF / net income · years of positive op. cash flow · op. cash flow growth |
| Business quality & resilience | 25% | avg & worst-year ROIC · gross margin **vs sector** · gross-margin stability · operating-margin trend · net debt/EBITDA · interest cover · Piotroski F · Altman Z'' |
| Management & ownership | 15% | insider ownership · insider net buying (6m) · share-count change · payouts funded by FCF · ROIC trend |

- **Pass**: score ≥ 55 and no pillar below 2/10
- **Watch**: score 45–55 (or ≥ 55 but one pillar below the floor)

### 4. Valuation — shown, never scored
EV/EBIT, FCF yield, P/E, EV/Sales, and a simple reverse DCF (10-yr, 10% discount, 2.5% terminal)
giving the **FCF growth the price implies**, compared with actual revenue growth. Tagged
*cheap / fair / rich* vs the sector median EV/EBIT (< 0.75x / > 1.33x).

### 5. Daily output
Ranked Pass + Watch lists with pillar scores and metric detail, **new entries**, and **dropouts**
with the reason (red flags = a hard exclusion newly triggered).

## Known limits of Yahoo data
- ~4 years of annual statements and ~5 quarters, so growth consistency is judged over 3 years.
- Many UK companies report half-yearly; "latest YoY" falls back to the last annual change.
- UK insider-transaction data is sparse (scored neutral when missing).
- Moat, management integrity and governance can't be screened — that's the research step.

## How it runs
- `.github/workflows/screen.yml` runs at 05:20 UTC Tue–Sat (after each trading day).
- Statements are cached on the `cache` branch and refreshed weekly per company (or right after a
  results date), so daily runs stay quick and polite to Yahoo. The first run fetches everything.
- Run manually: **Actions → Daily screen → Run workflow**.
- Locally: `pip install -r requirements.txt && python -m screener.run`; tests: `python -m pytest tests -q`.
