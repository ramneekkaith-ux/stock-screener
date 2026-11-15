"""Pick which screened companies get a research pack.

conviction = 70% screener score + 30% value score (FCF yield, growth gap, cheap/fair/rich tag),
then one name per sector, alternating US / UK, skipping anything covered recently.

Usage:  python -m research.select                # writes research/queue.json
        python -m research.select AAPL TSTL.L    # manual list
"""
import json
import os
import sys
from datetime import date, datetime, timezone

from screener.scoring import band

from . import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results", "latest.json")
COVERAGE = os.path.join(ROOT, "research", "coverage.json")
QUEUE = os.path.join(ROOT, "research", "queue.json")


def value_score(s):
    v, m = s["valuation"], s["metrics"]
    parts = [
        band(v.get("fcf_yield"), [0, 0.03, 0.05, 0.08, 0.12], [0, 3, 5, 7, 9, 10]),
        band(v.get("growth_gap"), [-0.05, 0, 0.05, 0.10], [1, 3, 6, 8, 10]),
        {"cheap": 10, "fair": 6, "rich": 2}.get(v.get("tag"), 4),
    ]
    parts = [p for p in parts if p is not None]
    return sum(parts) / len(parts) if parts else 5.0


def load_coverage():
    if os.path.exists(COVERAGE):
        with open(COVERAGE) as f:
            return json.load(f)
    return {}


def candidates():
    with open(RESULTS) as f:
        stocks = json.load(f)["stocks"]
    cov = load_coverage()
    today = date.today()
    out = []
    for s in stocks:
        if s["tier"] != "Pass" or s["score"] < config.MIN_SCORE or s["coverage"] < config.MIN_COVERAGE:
            continue
        last = cov.get(s["symbol"], {}).get("date")
        if last and (today - date.fromisoformat(last)).days < config.RECOVER_AFTER_DAYS:
            continue
        vs = value_score(s)
        out.append({
            "symbol": s["symbol"], "name": s["name"], "market": s["market"], "sector": s["sector"],
            "score": s["score"], "value_score": round(vs, 2),
            "conviction": round(config.QUALITY_WEIGHT * s["score"] + (1 - config.QUALITY_WEIGHT) * vs * 10, 1),
            "tag": s["valuation"].get("tag"), "fcf_yield": s["valuation"].get("fcf_yield"),
        })
    out.sort(key=lambda r: -r["conviction"])
    return out


def pick(cands, n):
    chosen, sectors = [], {}
    want_market = "US"
    pool = list(cands)
    while pool and len(chosen) < n:
        pick_ = next((c for c in pool if c["market"] == want_market
                      and sectors.get(c["sector"], 0) < config.MAX_PER_SECTOR), None)
        if pick_ is None:
            pick_ = next((c for c in pool if sectors.get(c["sector"], 0) < config.MAX_PER_SECTOR), None)
        if pick_ is None:
            break
        chosen.append(pick_)
        sectors[pick_["sector"]] = sectors.get(pick_["sector"], 0) + 1
        pool.remove(pick_)
        want_market = "UK" if want_market == "US" else "US"
    return chosen


def main():
    manual = [a for a in sys.argv[1:] if a.strip()]
    if manual:
        queue = [{"symbol": t.strip().upper() if not t.endswith(".L") else t.strip(), "manual": True} for t in manual]
        ranked = []
    else:
        ranked = candidates()
        queue = pick(ranked, config.CANDIDATES_PER_RUN)
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "queue": queue, "next_best": ranked[:25]}
    with open(QUEUE, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(queue, indent=1))


if __name__ == "__main__":
    main()
