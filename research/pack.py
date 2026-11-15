"""Build a research pack for one or more tickers: every number a report needs, from source.

Usage:  python -m research.pack                 # tickers from research/queue.json
        python -m research.pack HRMY TSTL.L     # specific tickers

Writes research/packs/<TICKER>/pack.json (+ a default dcf.json via research.dcf).
Amounts are in the company's reporting currency, in units (not millions), unless a key says _usd.
"""
import json
import logging
import math
import os
import sys
import time
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

from screener.fetch import _df_to_dict
from screener.fx import FX
from screener import metrics as M

from . import config, dcf, macro

log = logging.getLogger("research.pack")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS = os.path.join(ROOT, "research", "packs")
BENCHMARK = {"US": ("^GSPC", "S&P 500"), "UK": ("^FTAS", "FTSE All-Share")}

INFO_KEYS = [
    "longName", "shortName", "symbol", "exchange", "fullExchangeName", "quoteType", "currency",
    "financialCurrency", "sector", "industry", "industryKey", "sectorKey", "country", "city",
    "website", "fullTimeEmployees", "longBusinessSummary", "beta", "sharesOutstanding",
    "impliedSharesOutstanding", "floatShares", "heldPercentInsiders", "heldPercentInstitutions",
    "marketCap", "enterpriseValue", "currentPrice", "regularMarketPrice", "fiftyTwoWeekHigh",
    "fiftyTwoWeekLow", "fiftyDayAverage", "twoHundredDayAverage", "trailingPE", "forwardPE",
    "priceToBook", "enterpriseToRevenue", "enterpriseToEbitda", "dividendYield", "payoutRatio",
    "returnOnEquity", "returnOnAssets", "grossMargins", "operatingMargins", "ebitdaMargins",
    "profitMargins", "revenueGrowth", "earningsGrowth", "totalRevenue", "ebitda", "totalDebt",
    "totalCash", "freeCashflow", "operatingCashflow", "recommendationKey", "numberOfAnalystOpinions",
    "targetMeanPrice", "targetMedianPrice", "targetHighPrice", "targetLowPrice",
    "auditRisk", "boardRisk", "compensationRisk", "shareHolderRightsRisk", "overallRisk",
    "lastFiscalYearEnd", "mostRecentQuarter", "earningsTimestamp", "exDividendDate",
]


# ---------------------------------------------------------------- helpers

def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (pd.Timestamp, datetime, date)):
        return x.isoformat()[:19]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        x = float(x)
        return None if math.isnan(x) or math.isinf(x) else x
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def _records(df, limit=None):
    if df is None or getattr(df, "empty", True):
        return []
    df = df.reset_index()
    if limit:
        df = df.head(limit)
    return _clean(df.to_dict(orient="records"))


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as e:
        log.debug("skip: %s", e)
        return default


def _nz(x):
    return 0.0 if x is None else x


# ---------------------------------------------------------------- derived financials

def derived_annual(rec):
    """Year-by-year table of the lines a report shows, from the statements."""
    items = ["revenue", "gross_profit", "operating_income", "ebit", "ebitda", "net_income",
             "interest", "pretax", "tax", "diluted_shares", "ocf", "capex", "buybacks", "dividends",
             "debt", "cash", "equity", "total_assets", "current_assets", "current_liabilities",
             "shares", "long_term_debt"]
    extra = {
        "da": ["Reconciled Depreciation", "Depreciation And Amortization",
               "Depreciation Amortization Depletion"],
        "eps_diluted": ["Diluted EPS"],
        "minority": ["Minority Interest"],
        "preferred": ["Preferred Stock"],
        "current_debt": ["Current Debt And Capital Lease Obligation", "Current Debt"],
        "receivables": ["Accounts Receivable", "Receivables"],
        "inventory": ["Inventory"],
        "payables": ["Accounts Payable", "Payables"],
        "sbc": ["Stock Based Compensation"],
        "rnd": ["Research And Development"],
    }
    where = {"da": ["cashflow", "income"], "eps_diluted": ["income"], "minority": ["balance"],
             "preferred": ["balance"], "current_debt": ["balance"], "receivables": ["balance"],
             "inventory": ["balance"], "payables": ["balance"], "sbc": ["cashflow"], "rnd": ["income"]}
    years = {}
    for it in items:
        for d, v in M._annual(rec, it):
            years.setdefault(d[:10], {})[it] = v
    for key, rows in extra.items():
        for stmt in where[key]:
            st = {k.replace(" ", ""): v for k, v in rec["annual"].get(stmt, {}).items()}
            hit = next((st[r.replace(" ", "")] for r in rows if st.get(r.replace(" ", ""))), None)
            if hit:
                for d, v in hit.items():
                    if v == v:
                        years.setdefault(d[:10], {}).setdefault(key, v)
                break
    out = []
    for d in sorted(years):
        y = years[d]
        if "revenue" not in y:
            continue
        rev = y["revenue"]
        row = {"period_end": d, **y}
        row["fcf"] = (y["ocf"] + y.get("capex", 0)) if "ocf" in y else None
        if "ebitda" not in y and "ebit" in y and "da" in y:
            row["ebitda"] = y["ebit"] + y["da"]
        for k, src in [("gross_margin", "gross_profit"), ("ebit_margin", "ebit"),
                       ("ebitda_margin", "ebitda"), ("net_margin", "net_income"), ("fcf_margin", "fcf"),
                       ("capex_pct", "capex"), ("da_pct", "da"), ("rnd_pct", "rnd")]:
            v = row.get(src)
            row[k] = (abs(v) if k == "capex_pct" else v) / rev if v is not None and rev else None
        nwc = None
        if all(k in y for k in ("current_assets", "current_liabilities")):
            nwc = (y["current_assets"] - y.get("cash", 0)) - (y["current_liabilities"] - y.get("current_debt", 0))
        row["nwc"] = nwc
        row["nwc_pct"] = nwc / rev if nwc is not None and rev else None
        eq = y.get("equity")
        row["roe"] = y["net_income"] / eq if "net_income" in y and eq and eq > 0 else None
        out.append(row)
    for prev, cur in zip(out, out[1:]):
        cur["revenue_growth"] = cur["revenue"] / prev["revenue"] - 1 if prev["revenue"] else None
    if out:
        out[0]["revenue_growth"] = None
    return out


def ttm(rec):
    t = {k: M._ttm(rec, k) for k in ["revenue", "ebit", "ebitda", "net_income", "ocf", "capex", "operating_income"]}
    t["fcf"] = (t["ocf"] + t["capex"]) if t["ocf"] is not None and t["capex"] is not None else None
    return t


# ---------------------------------------------------------------- peers

def _peer_candidates(info, symbol, market):
    cands = {}
    key = info.get("industryKey")
    if key:
        top = _safe(lambda: yf.Industry(key).top_companies)
        if top is not None and not top.empty:
            for i, (sym, r) in enumerate(top.iterrows()):
                cands[sym] = {"source": "Yahoo industry leaders", "leader_rank": i}
    res = os.path.join(ROOT, "results", "latest.json")
    if os.path.exists(res):
        with open(res) as f:
            for s in json.load(f)["stocks"]:
                if s.get("industry") == info.get("industry"):
                    cands.setdefault(s["symbol"], {"source": "Screener universe (same industry)"})
    if market == "UK" and info.get("industry"):
        ind = info["industry"].replace(" - ", "—")
        q = _safe(lambda: yf.EquityQuery("and", [yf.EquityQuery("eq", ["industry", ind]),
                                                 yf.EquityQuery("is-in", ["exchange", "LSE"])]))
        resp = _safe(lambda: yf.screen(q, size=50, sortField="intradaymarketcap", sortAsc=False), {}) if q else {}
        for qq in (resp or {}).get("quotes", []):
            if not qq["symbol"].startswith("0"):
                cands.setdefault(qq["symbol"], {"source": "LSE same industry"})
    cands.pop(symbol, None)
    return cands


def peers(info, symbol, market, target_mcap_usd, fx):
    override = os.path.join(PACKS, symbol, "peers.json")
    curated = None
    if os.path.exists(override):
        with open(override) as f:
            curated = json.load(f)          # {"peers": ["SYM", ...], "reason": "..."}
        cands = {s: {"source": "Curated by analyst"} for s in curated["peers"]}
    else:
        cands = _peer_candidates(info, symbol, market)
    rows = []
    for sym, meta in list(cands.items())[:40]:
        pi = _safe(lambda: yf.Ticker(sym).get_info(), {}) or {}
        if pi.get("quoteType") not in (None, "EQUITY") or not pi.get("marketCap"):
            continue
        cur = pi.get("currency") or "USD"
        r_px = fx.rate(cur) or 0
        mcap_usd = pi["marketCap"] * (fx.rate("GBP") if cur == "GBp" else r_px)
        rev_usd = (pi.get("totalRevenue") or 0) * (fx.rate(pi.get("financialCurrency") or cur) or 0)
        ev_rev = pi.get("enterpriseToRevenue")
        om = pi.get("operatingMargins")
        rows.append(_clean({
            "symbol": sym, "name": pi.get("longName") or pi.get("shortName"), "source": meta["source"],
            "leader_rank": meta.get("leader_rank"), "country": pi.get("country"),
            "exchange": pi.get("fullExchangeName"), "price": pi.get("currentPrice") or pi.get("regularMarketPrice"),
            "currency": cur, "pct_of_52w_high": (pi.get("currentPrice") or 0) / pi["fiftyTwoWeekHigh"]
            if pi.get("fiftyTwoWeekHigh") and pi.get("currentPrice") else None,
            "market_cap_usd": mcap_usd, "revenue_usd": rev_usd or None,
            "ev_revenue": ev_rev, "ev_ebitda": pi.get("enterpriseToEbitda"),
            "ev_ebit": ev_rev / om if ev_rev and om and om > 0 else None,
            "pe": pi.get("trailingPE"), "forward_pe": pi.get("forwardPE"),
            "ebitda_margin": pi.get("ebitdaMargins"), "operating_margin": om,
            "gross_margin": pi.get("grossMargins"), "roe": pi.get("returnOnEquity"),
            "revenue_growth": pi.get("revenueGrowth"),
        }))
        time.sleep(0.3)
    if not rows:
        return []
    if curated:
        for r in rows:
            r["role"] = "Curated peer"
        return rows
    for r in rows:
        r["size_distance"] = abs(math.log(max(r["market_cap_usd"], 1) / max(target_mcap_usd, 1)))
    leaders = sorted([r for r in rows if r.get("leader_rank") is not None], key=lambda r: r["leader_rank"])[:2]
    rest = sorted([r for r in rows if r not in leaders], key=lambda r: r["size_distance"])
    chosen = (leaders + rest)[:config.MAX_PEERS]
    for r in chosen:
        r["role"] = "Industry leader" if r in leaders else "Size-matched peer"
    return chosen


# ---------------------------------------------------------------- pack

def build(symbol, fx, screen_row=None):
    log.info("Building pack for %s", symbol)
    t = yf.Ticker(symbol)
    info_full = t.get_info() or {}
    info = {k: info_full.get(k) for k in INFO_KEYS if info_full.get(k) is not None}
    officers = [{"name": o.get("name"), "title": o.get("title"), "age": o.get("age"),
                 "total_pay": o.get("totalPay")} for o in info_full.get("companyOfficers", [])[:8]]
    rec = {
        "info": info,
        "annual": {"income": _df_to_dict(t.get_income_stmt(freq="yearly", pretty=True)),
                   "balance": _df_to_dict(t.get_balance_sheet(freq="yearly", pretty=True)),
                   "cashflow": _df_to_dict(t.get_cashflow(freq="yearly", pretty=True))},
        "quarterly": {"income": _df_to_dict(t.get_income_stmt(freq="quarterly", pretty=True)),
                      "balance": _df_to_dict(t.get_balance_sheet(freq="quarterly", pretty=True)),
                      "cashflow": _df_to_dict(t.get_cashflow(freq="quarterly", pretty=True))},
    }
    market = "UK" if symbol.endswith(".L") else "US"
    px_cur = info.get("currency") or "USD"
    fin_cur = info.get("financialCurrency") or ("GBP" if px_cur == "GBp" else px_cur)
    # price-currency units -> reporting-currency units (handles GBp pence and ADRs)
    px_to_fin = (fx.rate(px_cur) or 0) / (fx.rate(fin_cur) or 1)
    fin_to_usd = fx.rate(fin_cur) or 0

    hist = _safe(lambda: t.history(period="5y", interval="1d", auto_adjust=False))
    prices = []
    if hist is not None and not hist.empty:
        prices = [[d.strftime("%Y-%m-%d"), round(float(c), 4)] for d, c in hist["Close"].items() if c == c]
    bsym, bname = BENCHMARK[market]
    bh = _safe(lambda: yf.Ticker(bsym).history(period="5y", interval="1d"))
    bench = [[d.strftime("%Y-%m-%d"), round(float(c), 2)] for d, c in bh["Close"].items()] if bh is not None and not bh.empty else []

    price = info.get("currentPrice") or info.get("regularMarketPrice") or (prices[-1][1] if prices else None)
    # Yahoo's marketCap covers all share classes (sharesOutstanding can be one class only);
    # for LSE it is in GBP while the price is in pence.
    px_unit = 0.01 if px_cur == "GBp" else 1.0
    if info.get("marketCap") and price:
        shares = info["marketCap"] / (price * px_unit)
        shares_src = "Yahoo market cap ÷ price (all share classes)"
    else:
        shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        shares_src = "Yahoo shares outstanding"
    annual = derived_annual(rec)
    last = annual[-1] if annual else {}
    mcap_fin = price * shares * px_to_fin if price and shares else None
    debt = _nz(last.get("debt"))
    cash = _nz(last.get("cash"))
    minority = _nz(last.get("minority"))
    preferred = _nz(last.get("preferred"))
    ev_fin = mcap_fin + debt + minority + preferred - cash if mcap_fin is not None else None

    # beta: Yahoo's 5y monthly, else weekly regression vs benchmark
    beta_raw, beta_src = info.get("beta"), "Yahoo Finance (5y monthly)"
    if beta_raw is None and prices and bench:
        s = pd.Series({d: c for d, c in prices}).pipe(lambda x: x.set_axis(pd.to_datetime(x.index)))
        b = pd.Series({d: c for d, c in bench}).pipe(lambda x: x.set_axis(pd.to_datetime(x.index)))
        df = pd.concat([s, b], axis=1).dropna().resample("W").last().pct_change().dropna().tail(156)
        if len(df) > 52:
            beta_raw = float(np.cov(df.iloc[:, 0], df.iloc[:, 1])[0, 1] / np.var(df.iloc[:, 1]))
            beta_src = f"Regression of weekly returns vs {bname}, 3y"

    pack = {
        "symbol": symbol, "market": market,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "currency": {"price": px_cur, "reporting": fin_cur, "price_to_reporting": px_to_fin,
                     "reporting_to_usd": fin_to_usd,
                     "note": "Amounts in reporting currency units unless suffixed _usd. "
                             "GBp prices are pence: divide by 100 for GBP."},
        "info": info, "officers": officers,
        "screen": screen_row,
        "statements": rec,
        "annual": annual,
        "ttm": ttm(rec),
        "price": {"last": price, "currency": px_cur, "high_52w": info.get("fiftyTwoWeekHigh"),
                  "low_52w": info.get("fiftyTwoWeekLow"), "history_5y": prices,
                  "benchmark": {"symbol": bsym, "name": bname, "history_5y": bench}},
        "capital": {"shares": shares, "shares_source": shares_src, "market_cap": mcap_fin, "debt": debt, "cash": cash,
                    "minority": minority, "preferred": preferred, "enterprise_value": ev_fin,
                    "market_cap_usd": mcap_fin * fin_to_usd if mcap_fin else None,
                    "as_of_balance_sheet": last.get("period_end")},
        "beta": {"raw": beta_raw, "source": beta_src},
        "risk_free": macro.risk_free(fin_cur),
        "estimates": {
            "revenue": _records(_safe(t.get_revenue_estimate)),
            "eps": _records(_safe(t.get_earnings_estimate)),
            "growth": _records(_safe(t.get_growth_estimates)),
            "eps_trend": _records(_safe(t.get_eps_trend)),
            "price_targets": _clean(_safe(t.get_analyst_price_targets, {}) or {}),
            "recommendations": _records(_safe(t.get_recommendations_summary)),
            "rating_changes": _records(_safe(t.get_upgrades_downgrades), limit=15),
        },
        "holders": {
            "major": _records(_safe(t.get_major_holders)),
            "institutions": _records(_safe(t.get_institutional_holders), limit=10),
            "funds": _records(_safe(t.get_mutualfund_holders), limit=10),
            "insiders": _records(_safe(t.get_insider_roster_holders), limit=12),
            "insider_transactions": _records(_safe(t.get_insider_transactions), limit=25),
        },
        "events": {
            "earnings_dates": _records(_safe(lambda: t.get_earnings_dates(limit=12))),
            "calendar": _clean(_safe(t.get_calendar, {}) or {}),
            "dividends": _records(_safe(t.get_dividends), limit=None)[-12:],
        },
        "news": [],
        "filings": [],
    }
    for n in _safe(lambda: t.get_news(count=30, tab="all"), []) or []:
        c = n.get("content", n)
        pack["news"].append(_clean({
            "date": (c.get("pubDate") or "")[:10], "title": c.get("title"), "summary": c.get("summary"),
            "publisher": (c.get("provider") or {}).get("displayName"),
            "url": (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url"),
        }))
    if market == "US":
        for f in (_safe(t.get_sec_filings, []) or [])[:25]:
            pack["filings"].append(_clean({"date": str(f.get("date"))[:10], "type": f.get("type"),
                                           "title": f.get("title"), "url": f.get("edgarUrl")}))

    pack["peers"] = peers(info_full, symbol, market, pack["capital"]["market_cap_usd"] or 0, fx)
    pack["dcf_inputs"] = dcf.default_inputs(pack)
    pack["checks"] = checks(pack)
    return pack


def checks(p):
    out = []
    c = p["capital"]
    if c["market_cap"] and c["enterprise_value"] is not None:
        ev = c["market_cap"] + c["debt"] + c["minority"] + c["preferred"] - c["cash"]
        out.append({"check": "EV bridge adds up", "ok": abs(ev - c["enterprise_value"]) < 1})
    yshares = p["capital"]["shares"]
    bs = (p["annual"][-1].get("shares") if p["annual"] else None)
    if yshares and bs:
        diff = abs(yshares / bs - 1)
        out.append({"check": "Share count: quote vs latest balance sheet within 10%", "ok": diff < 0.10,
                    "detail": f"{yshares:,.0f} vs {bs:,.0f} ({diff:.1%})"})
    out.append({"check": "At least 3 years of annual statements", "ok": len(p["annual"]) >= 3,
                "detail": f"{len(p['annual'])} years"})
    out.append({"check": "Peers found (>= 4)", "ok": len(p["peers"]) >= 4, "detail": f"{len(p['peers'])}"})
    out.append({"check": "Price history (>= 2 years)", "ok": len(p["price"]["history_5y"]) > 500})
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    tickers = sys.argv[1:]
    screen = {}
    res = os.path.join(ROOT, "results", "latest.json")
    if os.path.exists(res):
        with open(res) as f:
            screen = {s["symbol"]: s for s in json.load(f)["stocks"]}
    if not tickers:
        with open(os.path.join(ROOT, "research", "queue.json")) as f:
            tickers = [q["symbol"] for q in json.load(f)["queue"]]
    fx = FX()
    built = []
    for sym in tickers:
        try:
            p = build(sym, fx, screen.get(sym))
        except Exception as e:
            log.exception("Pack failed for %s: %s", sym, e)
            continue
        d = os.path.join(PACKS, sym.replace("/", "_"))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "pack.json"), "w") as f:
            json.dump(_clean(p), f, separators=(",", ":"), default=str)
        model = dcf.run(p, p["dcf_inputs"])
        with open(os.path.join(d, "dcf.json"), "w") as f:
            json.dump(_clean(model), f, indent=1, default=str)
        built.append(sym)
        log.info("%s: EV %.0f, DCF value/share %s, checks %s", sym, p["capital"]["enterprise_value"] or 0,
                 model["per_share"]["value_price_ccy"], [c["ok"] for c in p["checks"]])
    log.info("Built %d packs: %s", len(built), built)


if __name__ == "__main__":
    main()
