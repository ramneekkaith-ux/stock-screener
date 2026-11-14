"""Turn cached Yahoo statements into the raw metrics the methodology uses.

Every metric returns None when the data isn't there; missing data never excludes.
Absolute amounts are converted to USD; ratios are currency-free.
"""
import math
import statistics
from datetime import date

from . import config

ROWS = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "gross_profit": ["Gross Profit"],
    "operating_income": ["Operating Income", "Total Operating Income As Reported"],
    "ebit": ["EBIT", "Operating Income"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "net_income": ["Net Income Common Stockholders", "Net Income",
                   "Net Income From Continuing Operation Net Minority Interest"],
    "interest": ["Interest Expense", "Interest Expense Non Operating"],
    "pretax": ["Pretax Income"],
    "tax": ["Tax Provision"],
    "diluted_shares": ["Diluted Average Shares", "Basic Average Shares"],
    "ocf": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "capex": ["Capital Expenditure", "Purchase Of PPE"],
    "buybacks": ["Repurchase Of Capital Stock", "Common Stock Payments"],
    "dividends": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
    "debt": ["Total Debt"],
    "long_term_debt": ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"],
    "cash": ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"],
    "equity": ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"],
    "total_assets": ["Total Assets"],
    "current_assets": ["Current Assets"],
    "current_liabilities": ["Current Liabilities"],
    "total_liabilities": ["Total Liabilities Net Minority Interest"],
    "retained_earnings": ["Retained Earnings"],
    "shares": ["Ordinary Shares Number", "Share Issued"],
}
STATEMENT_OF = {
    **{k: "income" for k in ["revenue", "gross_profit", "operating_income", "ebit", "ebitda",
                             "net_income", "interest", "pretax", "tax", "diluted_shares"]},
    **{k: "cashflow" for k in ["ocf", "capex", "buybacks", "dividends"]},
    **{k: "balance" for k in ["debt", "long_term_debt", "cash", "equity", "total_assets",
                              "current_assets", "current_liabilities", "total_liabilities",
                              "retained_earnings", "shares"]},
}


def _series(rec, period, item):
    """[(date, value)] ascending for one line item, first matching row name wins."""
    stmt = rec.get(period, {}).get(STATEMENT_OF[item], {})
    for row in ROWS[item]:
        if row in stmt and stmt[row]:
            return sorted(stmt[row].items())
    return []


def _annual(rec, item, n=5):
    return _series(rec, "annual", item)[-n:]


def _vals(s):
    return [v for _, v in s]


def _d(s):
    return date.fromisoformat(s[:10])


def _ttm(rec, item):
    """Sum of last 4 quarters if they are 4 consecutive quarters, else latest annual."""
    q = _series(rec, "quarterly", item)[-4:]
    if len(q) == 4 and 250 <= (_d(q[-1][0]) - _d(q[0][0])).days <= 300:
        return sum(_vals(q))
    a = _annual(rec, item, 1)
    return a[0][1] if a else None


def _latest(rec, item):
    a = _annual(rec, item, 1)
    return a[0][1] if a else None


def _by_year(rec, item):
    return {d[:4]: v for d, v in _annual(rec, item)}


def _cagr(first, last, years):
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def _span_years(s):
    return max((_d(s[-1][0]) - _d(s[0][0])).days / 365.25, 0) if len(s) >= 2 else 0


def _div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def _yoy(vals):
    return [(b / a - 1) for a, b in zip(vals, vals[1:]) if a and a > 0]


# ---------------------------------------------------------------- main

def compute(rec, fx_rate):
    """Raw metrics for one company. fx_rate converts financial-statement currency to USD."""
    m = {}
    rev_a = _annual(rec, "revenue")
    m["years_of_data"] = len(rev_a)

    # --- size & TTM figures (USD)
    def usd(x):
        return None if x is None else x * fx_rate

    for item in ["revenue", "ebit", "ebitda", "net_income", "ocf", "capex"]:
        m[f"{item}_ttm"] = usd(_ttm(rec, item))
    m["fcf_ttm"] = (m["ocf_ttm"] + m["capex_ttm"]) if m["ocf_ttm"] is not None and m["capex_ttm"] is not None else m["ocf_ttm"]
    m["debt"] = usd(_latest(rec, "debt")) or 0.0
    m["cash"] = usd(_latest(rec, "cash")) or 0.0

    # --- growth
    rv = _vals(rev_a)
    yoy = _yoy(rv)[-3:]
    m["rev_cagr"] = _cagr(rv[0], rv[-1], _span_years(rev_a)) if len(rv) >= 2 else None
    m["rev_growth_years"] = sum(1 for g in yoy if g > 0)
    m["rev_growth_periods"] = len(yoy)
    m["rev_growth_frac"] = (m["rev_growth_years"] / len(yoy)) if yoy else None
    m["rev_growth_vol"] = statistics.pstdev(yoy) if len(yoy) >= 2 else None
    m["rev_yoy_history"] = [round(g, 4) for g in yoy]
    q = _series(rec, "quarterly", "revenue")
    m["recent_growth"] = None
    if len(q) >= 5:
        latest_d, latest_v = _d(q[-1][0]), q[-1][1]
        for d_, v_ in q[:-1]:
            if 330 <= (latest_d - _d(d_)).days <= 400 and v_ > 0:
                m["recent_growth"] = latest_v / v_ - 1
    if m["recent_growth"] is None and yoy:
        m["recent_growth"] = yoy[-1]

    # --- cash flow
    ocf_y, capex_y, ni_y = _by_year(rec, "ocf"), _by_year(rec, "capex"), _by_year(rec, "net_income")
    years = sorted(ocf_y)[-4:]
    m["ocf_years"] = len(years)
    m["ocf_negative_years"] = sum(1 for y in years if ocf_y[y] < 0)
    m["ocf_positive_frac"] = (1 - m["ocf_negative_years"] / len(years)) if years else None
    fcf_y = {y: ocf_y[y] + capex_y.get(y, 0) for y in ocf_y}
    m["fcf_margin"] = _div(m["fcf_ttm"], m["revenue_ttm"]) if (m["revenue_ttm"] or 0) > 0 else None
    last3 = sorted(fcf_y)[-3:]
    ni_sum = sum(ni_y.get(y, 0) for y in last3)
    fcf_sum = sum(fcf_y[y] for y in last3)
    m["fcf_conversion"] = (fcf_sum / ni_sum) if last3 and ni_sum > 0 else None
    ocf_s = [(y, ocf_y[y]) for y in sorted(ocf_y)]
    m["ocf_cagr"] = _cagr(ocf_s[0][1], ocf_s[-1][1], len(ocf_s) - 1) if len(ocf_s) >= 2 else None

    # --- business quality
    gp_y = _by_year(rec, "gross_profit")
    op_y = _by_year(rec, "operating_income")
    rev_y = _by_year(rec, "revenue")
    gm = [gp_y[y] / rev_y[y] for y in sorted(gp_y) if rev_y.get(y, 0) > 0]
    gm = [g for g in gm if -1 < g <= 1]
    m["gross_margin"] = gm[-1] if gm else None
    m["gross_margin_std"] = statistics.pstdev(gm) if len(gm) >= 2 else None
    om = [op_y[y] / rev_y[y] for y in sorted(op_y) if rev_y.get(y, 0) > 0]
    m["operating_margin"] = om[-1] if om else None
    m["op_margin_trend"] = (om[-1] - om[0]) if len(om) >= 2 else None

    ebit_y, tax_y, pre_y = _by_year(rec, "ebit"), _by_year(rec, "tax"), _by_year(rec, "pretax")
    debt_y, cash_y, eq_y, ta_y = (_by_year(rec, k) for k in ["debt", "cash", "equity", "total_assets"])
    roic = []
    for y in sorted(ebit_y):
        if y not in eq_y:
            continue
        t = _div(tax_y.get(y), pre_y.get(y))
        t = 0.25 if t is None or not (0 <= t <= 0.4) else t
        ic = debt_y.get(y, 0) + eq_y[y] - cash_y.get(y, 0)
        ic = max(ic, 0.1 * ta_y.get(y, 0)) if ta_y.get(y) else ic
        if ic and ic > 0:
            roic.append(ebit_y[y] * (1 - t) / ic)
    m["roic"] = roic[-1] if roic else None
    m["roic_avg"] = statistics.mean(roic) if roic else None
    m["roic_min"] = min(roic) if roic else None
    m["roic_trend"] = (roic[-1] - roic[0]) if len(roic) >= 2 else None

    net_debt = m["debt"] - m["cash"]
    m["net_debt"] = net_debt
    if net_debt <= 0:
        m["net_debt_ebitda"] = -1.0                       # net cash
    elif m["ebitda_ttm"] and m["ebitda_ttm"] > 0:
        m["net_debt_ebitda"] = net_debt / m["ebitda_ttm"]
    elif m["ebitda_ttm"] is not None:
        m["net_debt_ebitda"] = math.inf                   # debt and no EBITDA
    else:
        m["net_debt_ebitda"] = None
    interest = _ttm(rec, "interest")
    if interest is None or interest == 0:
        m["interest_coverage"] = math.inf if m["debt"] == 0 else None
    else:
        m["interest_coverage"] = _div(_ttm(rec, "ebit"), abs(interest))

    # Altman Z'' (non-manufacturer version; distress < 1.1, safe > 2.6)
    ta = _latest(rec, "total_assets")
    ca, cl, re_ = _latest(rec, "current_assets"), _latest(rec, "current_liabilities"), _latest(rec, "retained_earnings")
    tl, eq = _latest(rec, "total_liabilities"), _latest(rec, "equity")
    ebit_l = _latest(rec, "ebit")
    if ta and ta > 0 and None not in (ca, cl, re_, tl, eq, ebit_l) and tl > 0:
        m["altman_z2"] = (6.56 * (ca - cl) / ta + 3.26 * re_ / ta + 6.72 * ebit_l / ta + 1.05 * eq / tl)
    else:
        m["altman_z2"] = None

    m["piotroski"], m["piotroski_tests"] = _piotroski(rec)

    # --- management & ownership
    info = rec.get("info", {})
    m["insider_pct"] = info.get("heldPercentInsiders")
    ins = rec.get("insider", {})
    m["insider_net_pct"] = None
    for k, v in ins.items():
        if k.startswith("% Net Shares"):
            m["insider_net_pct"] = v
    if m["insider_net_pct"] is None and ins:
        net = next((v for k, v in ins.items() if k.startswith("Net Shares")), None)
        held = next((v for k, v in ins.items() if k.startswith("Total Insider Shares")), None)
        if net is not None and held:
            m["insider_net_pct"] = net / held
    sh = _annual(rec, "shares") or _annual(rec, "diluted_shares")
    m["share_cagr"] = _cagr(sh[0][1], sh[-1][1], _span_years(sh)) if len(sh) >= 2 else None
    bb, dv = _by_year(rec, "buybacks"), _by_year(rec, "dividends")
    returned = sum(abs(bb.get(y, 0)) + abs(dv.get(y, 0)) for y in last3)
    m["shareholder_returns_3y"] = usd(returned)
    m["returns_to_fcf"] = (returned / fcf_sum) if returned > 0 and fcf_sum > 0 else (
        math.inf if returned > 0 else None)

    # --- hard exclusions (only on data we actually have)
    reasons = []
    if m["revenue_ttm"] is not None and m["revenue_ttm"] < config.HARD["min_revenue_usd"]:
        reasons.append("Revenue under $10M")
    if m["ocf_years"] >= 3 and m["ocf_negative_years"] > config.HARD["max_negative_ocf_years"]:
        reasons.append(f"Negative operating cash flow in {m['ocf_negative_years']} of last {m['ocf_years']} years")
    if m["altman_z2"] is not None and m["altman_z2"] < config.HARD["min_altman_z2"]:
        reasons.append(f"Altman Z'' {m['altman_z2']:.2f} (distress zone)")
    if m["share_cagr"] is not None and m["share_cagr"] > config.HARD["max_share_growth"]:
        reasons.append(f"Share count growing {m['share_cagr']:.0%}/yr")
    if m["net_debt_ebitda"] is not None and m["net_debt_ebitda"] > config.HARD["max_net_debt_ebitda"]:
        nd = m["net_debt_ebitda"]
        reasons.append("Net debt with negative EBITDA" if math.isinf(nd) else f"Net debt/EBITDA {nd:.1f}x")
    m["exclusions"] = reasons
    return m


def _piotroski(rec):
    """Piotroski F-score scaled to 9 from the tests we can compute. Returns (score, n_tests)."""
    y = {k: _by_year(rec, k) for k in ["net_income", "total_assets", "ocf", "long_term_debt",
                                        "current_assets", "current_liabilities", "shares",
                                        "gross_profit", "revenue"]}
    yrs = sorted(set(y["net_income"]) & set(y["total_assets"]))
    if len(yrs) < 2:
        return None, 0
    t0, t1 = yrs[-2], yrs[-1]
    tests = []

    def g(k, yr):
        return y[k].get(yr)

    roa1 = _div(g("net_income", t1), g("total_assets", t1))
    roa0 = _div(g("net_income", t0), g("total_assets", t0))
    if roa1 is not None:
        tests.append(roa1 > 0)
    if g("ocf", t1) is not None:
        tests.append(g("ocf", t1) > 0)
        if g("net_income", t1) is not None:
            tests.append(g("ocf", t1) > g("net_income", t1))
    if roa1 is not None and roa0 is not None:
        tests.append(roa1 > roa0)
    l1 = _div(g("long_term_debt", t1) or 0, g("total_assets", t1))
    l0 = _div(g("long_term_debt", t0) or 0, g("total_assets", t0))
    if l1 is not None and l0 is not None:
        tests.append(l1 <= l0)
    cr1 = _div(g("current_assets", t1), g("current_liabilities", t1))
    cr0 = _div(g("current_assets", t0), g("current_liabilities", t0))
    if cr1 is not None and cr0 is not None:
        tests.append(cr1 > cr0)
    if g("shares", t1) and g("shares", t0):
        tests.append(g("shares", t1) <= g("shares", t0) * 1.005)
    gm1 = _div(g("gross_profit", t1), g("revenue", t1))
    gm0 = _div(g("gross_profit", t0), g("revenue", t0))
    if gm1 is not None and gm0 is not None:
        tests.append(gm1 > gm0)
    at1 = _div(g("revenue", t1), g("total_assets", t1))
    at0 = _div(g("revenue", t0), g("total_assets", t0))
    if at1 is not None and at0 is not None:
        tests.append(at1 > at0)
    if len(tests) < 5:
        return None, len(tests)
    return round(sum(tests) / len(tests) * 9, 1), len(tests)
