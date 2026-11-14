"""Offline checks with made-up companies (no network). Run: python -m pytest tests -q"""
import math

from screener import metrics, scoring, valuation

YEARS = ["2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31"]
QTRS = ["2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30"]


def make(rev, ocf, capex, ni, ebit, debt, cash, equity, ta, shares, gp=None, q_rev=None,
         insider=0.12, re_=None):
    a = lambda xs: dict(zip(YEARS, xs))
    rec = {
        "fetched": "2026-11-14T06:00:00+00:00",
        "info": {"heldPercentInsiders": insider, "sector": "Industrials"},
        "annual": {
            "income": {"Total Revenue": a(rev), "Gross Profit": a(gp or [r * 0.4 for r in rev]),
                       "Operating Income": a(ebit), "EBIT": a(ebit),
                       "EBITDA": a([e * 1.3 for e in ebit]), "Net Income": a(ni),
                       "Interest Expense": a([2] * 4), "Pretax Income": a([e - 2 for e in ebit]),
                       "Tax Provision": a([(e - 2) * 0.25 for e in ebit])},
            "balance": {"Total Debt": a(debt), "Cash And Cash Equivalents": a(cash),
                        "Stockholders Equity": a(equity), "Total Assets": a(ta),
                        "Current Assets": a([t * 0.4 for t in ta]),
                        "Current Liabilities": a([t * 0.2 for t in ta]),
                        "Total Liabilities Net Minority Interest": a([t - e for t, e in zip(ta, equity)]),
                        "Retained Earnings": a(re_ or [e * 0.5 for e in equity]),
                        "Ordinary Shares Number": a(shares)},
            "cashflow": {"Operating Cash Flow": a(ocf), "Capital Expenditure": a(capex)},
        },
        "quarterly": {"income": {"Total Revenue": dict(zip(QTRS, q_rev))} if q_rev else {},
                      "cashflow": {}},
        "insider": {"% Net Shares Purchased (Sold)": 0.02},
    }
    return rec


def good():
    return make(rev=[100, 115, 130, 150], ocf=[15, 18, 21, 25], capex=[-4, -4, -5, -5],
                ni=[10, 12, 14, 17], ebit=[14, 17, 20, 24], debt=[20, 18, 15, 10],
                cash=[10, 12, 15, 20], equity=[80, 90, 100, 115], ta=[150, 160, 170, 185],
                shares=[50, 50, 49.5, 49], q_rev=[36, 38, 37, 40, 41])


def junk():
    return make(rev=[30, 25, 28, 20], ocf=[-5, -6, 1, -4], capex=[-2] * 4, ni=[-8, -9, -3, -10],
                ebit=[-6, -7, -1, -8], debt=[30, 40, 45, 50], cash=[5, 3, 2, 1],
                equity=[20, 10, 5, -2], ta=[60, 55, 52, 50], shares=[10, 13, 18, 25],
                re_=[-20, -30, -35, -45])


def test_good_company_passes():
    m = metrics.compute(good(), 1e6)          # statements in $M
    assert not m["exclusions"], m["exclusions"]
    assert abs(m["rev_cagr"] - (1.5 ** (1 / 3) - 1)) < 0.01
    assert m["rev_growth_years"] == 3
    assert abs(m["recent_growth"] - (41 / 36 - 1)) < 1e-9
    assert m["net_debt_ebitda"] == -1.0
    m["gm_sector_pct"] = 0.6
    s = scoring.score(m)
    assert s["tier"] == "Pass", s
    v = valuation.compute(400e6, m)
    assert 0 < v["ev_ebit"] < 30 and v["implied_growth"] is not None


def test_junk_is_excluded():
    m = metrics.compute(junk(), 1e6)
    reasons = " ".join(m["exclusions"])
    assert "Negative operating cash flow" in reasons
    assert "Share count" in reasons


def test_missing_data_is_neutral_not_fatal():
    rec = good()
    del rec["annual"]["balance"]["Retained Earnings"]
    rec["info"].pop("heldPercentInsiders")
    rec["insider"] = {}
    m = metrics.compute(rec, 1e6)
    assert m["altman_z2"] is None and not m["exclusions"]
    m["gm_sector_pct"] = None
    s = scoring.score(m)
    assert s["detail"]["insider_pct"]["missing"] and s["detail"]["insider_pct"]["points"] == 5.0
    assert s["tier"] in ("Pass", "Watch")


def test_implied_growth_roundtrip():
    g = valuation.implied_growth(1000, 50)
    assert -0.5 < g < 1.0
    assert valuation.implied_growth(1000, -5) is None


def test_band():
    assert scoring.band(0.12, [0, 0.05, 0.10, 0.20], [0, 3, 6, 8, 10]) == 8
    assert scoring.band(None, [1], [0, 1]) is None
    assert scoring.band(math.nan, [1], [0, 1]) is None
