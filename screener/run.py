"""Daily run: universe -> fetch -> metrics -> exclusions -> scores -> valuation -> results/.

Usage:  python -m screener.run            (full run)
        SKIP_FETCH=1 python -m screener.run   (re-score from cache only)
"""
import csv
import json
import logging
import math
import os
import sys
from datetime import datetime, timezone

from . import config, fetch, metrics, scoring, universe, valuation
from .fx import FX

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache.json.gz")
RESULTS = os.path.join(ROOT, "results")

log = logging.getLogger("screener")

KEY_METRICS = [
    "revenue_ttm", "rev_cagr", "rev_growth_years", "rev_growth_periods", "rev_yoy_history",
    "recent_growth", "fcf_ttm", "fcf_margin", "fcf_conversion", "ocf_negative_years", "ocf_years",
    "ocf_cagr", "gross_margin", "gross_margin_std", "operating_margin", "op_margin_trend",
    "roic", "roic_avg", "roic_min", "roic_trend", "net_debt", "net_debt_ebitda",
    "interest_coverage", "altman_z2", "piotroski", "insider_pct", "insider_net_pct",
    "share_cagr", "returns_to_fcf", "years_of_data",
]


def clean(x):
    if isinstance(x, float):
        if math.isnan(x):
            return None
        if math.isinf(x):
            return 1e9 if x > 0 else -1e9
        return round(x, 4) if abs(x) < 1e6 else round(x)
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    return x


def statement_currency(u, info):
    cur = info.get("financialCurrency") or u.get("financial_currency") or u.get("currency") or "USD"
    return "GBP" if cur in ("GBp", "GBX") else cur


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    started = datetime.now(timezone.utc)
    fx = FX()

    uni, uni_rejected = universe.build(fx)
    cache = fetch.load_cache(CACHE)
    if os.environ.get("SKIP_FETCH"):
        fetch_stats = {"skipped": True}
    else:
        fetch_stats = fetch.refresh(sorted(uni), cache, CACHE)

    scored, excluded, insufficient, not_fetched = [], [], [], 0
    for sym, u in uni.items():
        rec = cache.get(sym)
        if not rec:
            not_fetched += 1
            continue
        info = rec.get("info", {})
        if info.get("industry") in config.EXCLUDED_INDUSTRIES:
            continue
        m = metrics.compute(rec, fx.rate(statement_currency(u, info)))
        row = {**u, "sector": info.get("sector"), "industry": info.get("industry"),
               "country": info.get("country"), "website": info.get("website"),
               "summary": info.get("longBusinessSummary"), "data_as_of": rec.get("fetched"),
               "metrics": m}
        if m["years_of_data"] < config.MIN_YEARS_OF_DATA:
            insufficient.append(row)
        elif m["exclusions"]:
            excluded.append(row)
        else:
            scored.append(row)

    scoring.add_sector_ranks(scored)
    for r in scored:
        r.update(scoring.score(r["metrics"]))
        r["valuation"] = valuation.compute(r["market_cap_usd"], r["metrics"])
    valuation.add_tags(scored)

    listed = [r for r in scored if r["tier"] in ("Pass", "Watch")]
    listed.sort(key=lambda r: -r["score"])

    # ---- compare with the previous run
    prev_path = os.path.join(RESULTS, "latest.json")
    prev = {}
    if os.path.exists(prev_path):
        with open(prev_path) as f:
            prev = {s["symbol"]: s for s in json.load(f).get("stocks", [])}
    now_syms = {r["symbol"] for r in listed}
    for r in listed:
        p = prev.get(r["symbol"])
        r["is_new"] = bool(prev) and p is None
        r["prev_tier"] = p["tier"] if p else None
        r["prev_score"] = p["score"] if p else None
        r["first_seen"] = p.get("first_seen", p.get("date")) if p else started.date().isoformat()

    by_sym = {r["symbol"]: r for r in scored + excluded + insufficient}
    dropouts = []
    for sym, p in prev.items():
        if sym in now_syms:
            continue
        r = by_sym.get(sym)
        if r is None:
            reason = "Left the universe (market cap / liquidity) or data unavailable today"
        elif r.get("metrics", {}).get("exclusions"):
            reason = "Red flag: " + "; ".join(r["metrics"]["exclusions"])
        elif "score" in r:
            reason = f"Score fell to {r['score']}"
        else:
            reason = "Insufficient data"
        dropouts.append({"symbol": sym, "name": p.get("name"), "prev_tier": p.get("tier"),
                         "prev_score": p.get("score"), "reason": reason,
                         "red_flag": reason.startswith("Red flag")})

    exclusion_counts = {}
    for r in excluded:
        for reason in r["metrics"]["exclusions"]:
            k = reason.split(" ")[0] if reason[0].isalpha() else reason
            key = ("Altman Z''" if reason.startswith("Altman") else
                   "Net debt" if reason.startswith("Net debt") else
                   "Dilution" if reason.startswith("Share count") else
                   "Negative op. cash flow" if reason.startswith("Negative") else
                   "Revenue < $10M" if reason.startswith("Revenue") else k)
            exclusion_counts[key] = exclusion_counts.get(key, 0) + 1

    def out_row(r):
        return clean({
            "symbol": r["symbol"], "name": r["name"], "market": r["market"],
            "exchange": r["exchange"], "sector": r["sector"], "industry": r["industry"],
            "country": r["country"], "website": r["website"], "summary": r["summary"],
            "price": r["price"], "currency": r["currency"], "data_as_of": r["data_as_of"],
            "tier": r["tier"], "score": r["score"], "pillars": r["pillars"],
            "coverage": r["coverage"], "low_coverage": r["low_coverage"],
            "pillar_floor_hit": r["pillar_floor_hit"],
            "points": {k: (None if d["missing"] else d["points"]) for k, d in r["detail"].items()},
            "metrics": {k: r["metrics"].get(k) for k in KEY_METRICS},
            "valuation": r["valuation"],
            "is_new": r["is_new"], "prev_tier": r["prev_tier"], "prev_score": r["prev_score"],
            "first_seen": r["first_seen"], "date": started.date().isoformat(),
        })

    counts = {
        "universe": len(uni), "not_fetched_yet": not_fetched,
        "insufficient_data": len(insufficient), "excluded": len(excluded),
        "scored": len(scored), "pass": sum(r["tier"] == "Pass" for r in listed),
        "watch": sum(r["tier"] == "Watch" for r in listed),
        "below": sum(r["tier"] == "Below" for r in scored),
        "new_today": sum(r["is_new"] for r in listed), "dropouts": len(dropouts),
    }
    out = {
        "generated_at": started.isoformat(timespec="seconds"),
        "counts": counts, "universe_rejected": uni_rejected, "exclusion_counts": exclusion_counts,
        "fetch": fetch_stats, "fx": clean(fx.snapshot()),
        "settings": {"pass_score": config.PASS_SCORE, "watch_score": config.WATCH_SCORE,
                     "pillar_floor": config.PILLAR_FLOOR, "weights": config.PILLAR_WEIGHTS,
                     "market_cap_usd": [config.MIN_MARKET_CAP_USD, config.MAX_MARKET_CAP_USD]},
        "metric_labels": {k: {"label": v[1], "pillar": v[0]} for k, v in scoring.METRICS.items()},
        "stocks": [out_row(r) for r in listed],
        "dropouts": clean(dropouts),
    }
    os.makedirs(os.path.join(RESULTS, "history"), exist_ok=True)
    with open(prev_path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    with open(os.path.join(RESULTS, "history", f"{started.date().isoformat()}.json"), "w") as f:
        json.dump({"counts": counts, "stocks": [[r["symbol"], r["tier"], r["score"]] for r in listed]},
                  f, separators=(",", ":"))
    with open(os.path.join(RESULTS, "latest.csv"), "w", newline="") as f:
        w = csv.writer(f)
        cols = ["symbol", "name", "market", "sector", "tier", "score", "growth", "cashflow",
                "quality", "management", "market_cap_usd", "ev_ebit", "fcf_yield", "pe",
                "implied_growth", "tag", "rev_cagr", "fcf_margin", "roic_avg", "insider_pct"]
        w.writerow(cols)
        for r in listed:
            v, m, p = r["valuation"], r["metrics"], r["pillars"]
            w.writerow(clean([r["symbol"], r["name"], r["market"], r["sector"], r["tier"],
                              r["score"], p["growth"], p["cashflow"], p["quality"], p["management"],
                              v["market_cap_usd"], v["ev_ebit"], v["fcf_yield"], v["pe"],
                              v["implied_growth"], v["tag"], m.get("rev_cagr"),
                              m.get("fcf_margin"), m.get("roic_avg"), m.get("insider_pct")]))
    log.info("Done: %s", counts)


if __name__ == "__main__":
    main()
