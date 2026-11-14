"""Valuation columns. Display only: nothing here changes the score or the tier."""
import math
import statistics
from collections import defaultdict

from . import config


def _pos_ratio(a, b):
    if a is None or b is None or b <= 0:
        return None
    return a / b


def implied_growth(ev, fcf, r=None, g_term=None, years=None):
    """Annual FCF growth over `years` that today's EV prices in (simple reverse DCF)."""
    r = r or config.DCF_DISCOUNT_RATE
    g_term = g_term or config.DCF_TERMINAL_GROWTH
    years = years or config.DCF_YEARS
    if not ev or not fcf or fcf <= 0 or ev <= 0:
        return None

    def value(g):
        pv, f = 0.0, fcf
        for t in range(1, years + 1):
            f *= 1 + g
            pv += f / (1 + r) ** t
        return pv + f * (1 + g_term) / (r - g_term) / (1 + r) ** years

    lo, hi = -0.5, 1.0
    if value(lo) > ev:
        return lo
    if value(hi) < ev:
        return hi
    for _ in range(60):
        mid = (lo + hi) / 2
        if value(mid) < ev:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def compute(mcap, m):
    ev = mcap + (m.get("debt") or 0) - (m.get("cash") or 0)
    v = {
        "market_cap_usd": mcap,
        "ev_usd": ev,
        "ev_ebit": _pos_ratio(ev, m.get("ebit_ttm")),
        "ev_sales": _pos_ratio(ev, m.get("revenue_ttm")),
        "pe": _pos_ratio(mcap, m.get("net_income_ttm")),
        "fcf_yield": (m["fcf_ttm"] / mcap) if m.get("fcf_ttm") is not None and mcap else None,
        "implied_growth": implied_growth(ev, m.get("fcf_ttm")),
    }
    g, actual = v["implied_growth"], m.get("rev_cagr")
    v["growth_gap"] = (actual - g) if g is not None and actual is not None else None
    return v


def add_tags(rows):
    """cheap / fair / rich vs sector median EV/EBIT among scored stocks."""
    by_sector, everyone = defaultdict(list), []
    for r in rows:
        x = r["valuation"].get("ev_ebit")
        if x is not None and 0 < x < 200:
            by_sector[r.get("sector") or "?"].append(x)
            everyone.append(x)
    overall = statistics.median(everyone) if everyone else None
    for r in rows:
        v = r["valuation"]
        peers = by_sector.get(r.get("sector") or "?", [])
        med = statistics.median(peers) if len(peers) >= 5 else overall
        v["sector_median_ev_ebit"] = med
        x = v.get("ev_ebit")
        if x is None or med is None:
            v["tag"] = "n/a" if x is None else "fair"
        elif x < med * config.CHEAP_VS_SECTOR:
            v["tag"] = "cheap"
        elif x > med * config.RICH_VS_SECTOR:
            v["tag"] = "rich"
        else:
            v["tag"] = "fair"
