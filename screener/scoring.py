"""Absolute 0-10 scoring against fixed bands, four weighted pillars, 0-100 composite.

Scores mean the same thing every day, so the Pass / Watch cutoffs are stable.
The one relative metric is gross margin, ranked within its sector, because a
'good' margin for a distributor and for a software company are very different.
"""
import math
from bisect import bisect_right
from collections import defaultdict

from . import config


def band(x, edges, points):
    """Points for x given ascending edges; len(points) == len(edges) + 1."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return float(points[bisect_right(edges, x)])


# metric name -> (pillar, label, scorer)
def _growth_frac(m):
    if m.get("rev_growth_periods", 0) == 0:
        return None
    return band(m["rev_growth_frac"], [0.01, 0.5, 0.99], [0, 3, 7, 10])


def _net_debt(m):
    x = m.get("net_debt_ebitda")
    if x is None:
        return None
    if x < 0:
        return 10.0
    return band(x, [1, 2, 3, 4], [8, 6, 4, 2, 0])


def _coverage(m):
    x = m.get("interest_coverage")
    if x is None:
        return None
    return band(x, [2, 4, 6, 10], [0, 3, 6, 8, 10])


def _returns(m):
    x = m.get("returns_to_fcf")
    if x is None:
        return 6.0 if (m.get("fcf_ttm") or 0) > 0 else None   # retains cash: neutral-good
    return band(x, [0.5, 1.0, 1.3], [10, 8, 4, 1])


def _insider_flow(m):
    x = m.get("insider_net_pct")
    if x is None:
        return None
    return band(x, [-0.05, -0.01, 0.0001, 0.01], [2, 4, 6, 8, 10])


METRICS = {
    # growth
    "rev_cagr":        ("growth", "3-yr revenue CAGR",
                        lambda m: band(m.get("rev_cagr"), [0, 0.05, 0.10, 0.20], [0, 3, 6, 8, 10])),
    "rev_growth_frac": ("growth", "Years of revenue growth", _growth_frac),
    "rev_growth_vol":  ("growth", "Growth steadiness",
                        lambda m: band(m.get("rev_growth_vol"), [0.05, 0.10, 0.20, 0.35], [10, 8, 5, 3, 1])),
    "recent_growth":   ("growth", "Latest YoY growth",
                        lambda m: band(m.get("recent_growth"), [-0.05, 0, 0.05, 0.15], [0, 3, 5, 8, 10])),
    # cash flow
    "fcf_margin":      ("cashflow", "FCF margin",
                        lambda m: band(m.get("fcf_margin"), [0, 0.03, 0.08, 0.15], [0, 3, 6, 8, 10])),
    "fcf_conversion":  ("cashflow", "FCF / net income",
                        lambda m: band(m.get("fcf_conversion"), [0.3, 0.6, 0.8, 1.2], [1, 4, 6, 9, 10])),
    "ocf_positive":    ("cashflow", "Years of positive op. cash flow",
                        lambda m: band(m.get("ocf_positive_frac"), [0.5, 0.74, 0.99], [0, 2, 6, 10])),
    "ocf_cagr":        ("cashflow", "Op. cash flow growth",
                        lambda m: band(m.get("ocf_cagr"), [0, 0.05, 0.15], [2, 5, 8, 10])),
    # business quality & resilience
    "roic_avg":        ("quality", "Average ROIC",
                        lambda m: band(m.get("roic_avg"), [0, 0.06, 0.12, 0.20], [0, 3, 6, 8, 10])),
    "roic_min":        ("quality", "Worst-year ROIC",
                        lambda m: band(m.get("roic_min"), [0, 0.05, 0.10, 0.15], [0, 3, 6, 8, 10])),
    "gross_margin_rank": ("quality", "Gross margin vs sector",
                        lambda m: None if m.get("gm_sector_pct") is None else round(m["gm_sector_pct"] * 10, 1)),
    "gross_margin_std": ("quality", "Gross margin stability",
                        lambda m: band(m.get("gross_margin_std"), [0.02, 0.04, 0.07, 0.12], [10, 8, 5, 3, 1])),
    "op_margin_trend": ("quality", "Operating margin trend",
                        lambda m: band(m.get("op_margin_trend"), [-0.05, -0.01, 0.01, 0.04], [1, 4, 6, 8, 10])),
    "net_debt_ebitda": ("quality", "Net debt / EBITDA", _net_debt),
    "interest_cover":  ("quality", "Interest coverage", _coverage),
    "piotroski":       ("quality", "Piotroski F-score",
                        lambda m: None if m.get("piotroski") is None else round(m["piotroski"] / 9 * 10, 1)),
    "altman_z2":       ("quality", "Altman Z''",
                        lambda m: band(m.get("altman_z2"), [1.1, 2.6, 4.0], [0, 5, 8, 10])),
    # management & ownership
    "insider_pct":     ("management", "Insider ownership",
                        lambda m: band(m.get("insider_pct"), [0.01, 0.05, 0.15], [2, 5, 8, 10])),
    "insider_flow":    ("management", "Insider buying (6m)", _insider_flow),
    "share_cagr":      ("management", "Share count change",
                        lambda m: band(m.get("share_cagr"), [-0.02, 0.01, 0.03, 0.06], [10, 8, 6, 4, 2])),
    "capital_returns": ("management", "Payouts funded by FCF", _returns),
    "roic_trend":      ("management", "ROIC trend (capital allocation)",
                        lambda m: band(m.get("roic_trend"), [-0.03, 0, 0.03], [2, 5, 7, 10])),
}


def add_sector_ranks(rows):
    """Percentile of gross margin within sector (min 5 peers, else whole universe)."""
    by_sector = defaultdict(list)
    everyone = []
    for r in rows:
        gm = r["metrics"].get("gross_margin")
        if gm is not None:
            by_sector[r.get("sector") or "?"].append(gm)
            everyone.append(gm)
    for vals in by_sector.values():
        vals.sort()
    everyone.sort()
    for r in rows:
        gm = r["metrics"].get("gross_margin")
        if gm is None:
            r["metrics"]["gm_sector_pct"] = None
            continue
        peers = by_sector[r.get("sector") or "?"]
        peers = peers if len(peers) >= 5 else everyone
        r["metrics"]["gm_sector_pct"] = bisect_right(peers, gm) / len(peers)


def score(m):
    detail, pillars, available, total = {}, defaultdict(list), 0, 0
    for key, (pillar, label, fn) in METRICS.items():
        try:
            pts = fn(m)
        except Exception:
            pts = None
        total += 1
        if pts is not None:
            available += 1
        detail[key] = {"label": label, "pillar": pillar,
                       "points": pts if pts is not None else config.MISSING_METRIC_SCORE,
                       "missing": pts is None}
        pillars[pillar].append(detail[key]["points"])
    pillar_scores = {p: round(sum(v) / len(v), 2) for p, v in pillars.items()}
    composite = sum(pillar_scores[p] * w for p, w in config.PILLAR_WEIGHTS.items()) * 10
    coverage = available / total
    weakest = min(pillar_scores.values())
    if composite >= config.PASS_SCORE and weakest >= config.PILLAR_FLOOR:
        tier = "Pass"
    elif composite >= config.WATCH_SCORE:
        tier = "Watch"
    else:
        tier = "Below"
    return {
        "score": round(composite, 1),
        "pillars": pillar_scores,
        "tier": tier,
        "coverage": round(coverage, 2),
        "low_coverage": coverage < config.LOW_COVERAGE,
        "pillar_floor_hit": weakest < config.PILLAR_FLOOR,
        "detail": detail,
    }
