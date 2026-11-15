"""DCF (10-year unlevered FCF), trading comps, football field and target price.

default_inputs(pack) proposes assumptions from history + consensus, each with a reason.
run(pack, inputs) is pure arithmetic, so Claude (or you) can override any input and re-run:

    python -m research.dcf HRMY                     # re-run with research/packs/HRMY/assumptions.json if present
"""
import json
import math
import os
import statistics
import sys

from . import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def _median(xs):
    xs = [x for x in xs if x is not None and x == x]
    return statistics.median(xs) if xs else None


def _q(xs, p):
    xs = sorted(x for x in xs if x is not None and x == x)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _consensus_growth(pack, base_rev):
    rows = {r.get("period"): r for r in pack["estimates"].get("revenue", []) if r.get("period")}
    y0, y1 = rows.get("0y"), rows.get("+1y")
    out = []
    if y0 and y0.get("avg") and (y0.get("numberOfAnalysts") or 0) >= 1 and base_rev:
        g1 = y0["avg"] / base_rev - 1
        out.append(_clip(g1, -0.2, 0.5))
        if y1 and y1.get("avg"):
            out.append(_clip(y1["avg"] / y0["avg"] - 1, -0.2, 0.5))
    return out, (y0 or {}).get("numberOfAnalysts")


def default_inputs(pack):
    a = pack["annual"]
    base = a[-1] if a else {}
    rev0 = base.get("revenue")
    why = {}
    n = config.FORECAST_YEARS

    # --- growth
    cons, n_an = _consensus_growth(pack, rev0)
    hist = [r.get("revenue") for r in a if r.get("revenue")]
    cagr = (hist[-1] / hist[0]) ** (1 / (len(hist) - 1)) - 1 if len(hist) >= 2 and hist[0] > 0 else 0.05
    tg = config.TERMINAL_GROWTH
    if cons:
        g = cons + [cons[-1]] * (2 - len(cons))
        why["growth"] = (f"Years 1–2 from analyst consensus ({n_an} analysts: {g[0]:.1%}, {g[1]:.1%}); "
                         f"then a straight-line fade to {tg:.1%} terminal growth by year {n}.")
    else:
        g0 = _clip(cagr, -0.05, 0.25)
        g = [g0, g0]
        why["growth"] = (f"No consensus available: years 1–2 at the {len(hist) - 1}-year historical revenue "
                         f"CAGR ({cagr:.1%}, capped to -5%…25%), fading to {tg:.1%} by year {n}.")
    path = g[:2] + [g[1] + (tg - g[1]) * (i - 1) / (n - 2) for i in range(2, n)]

    # --- margins & intensities
    em = [r.get("ebit_margin") for r in a]
    m0 = base.get("ebit_margin") if base.get("ebit_margin") is not None else (_median(em) or 0.1)
    mt = _median(em) if _median(em) is not None else m0
    margins = [m0 + (mt - m0) * min(i + 1, 5) / 5 for i in range(n)]
    why["ebit_margin"] = (f"Starts at last year's EBIT margin ({m0:.1%}) and moves to the {len(em)}-year "
                          f"median ({mt:.1%}) over 5 years.")
    taxes = [r["tax"] / r["pretax"] for r in a if r.get("tax") is not None and (r.get("pretax") or 0) > 0]
    tax = _clip(_median(taxes), 0.15, 0.30) if taxes else config.DEFAULT_TAX[pack["market"]]
    why["tax"] = f"Median effective tax rate ({tax:.1%}), kept within 15–30%."
    da = _median([r.get("da_pct") for r in a]) or 0.03
    capex = _median([r.get("capex_pct") for r in a]) or da
    nwc = _clip(_median([r.get("nwc_pct") for r in a]) or 0.0, -0.3, 0.5)
    why["reinvestment"] = (f"Historical medians: D&A {da:.1%}, capex {capex:.1%} of revenue; working capital "
                           f"{nwc:.1%} of revenue, so each extra $1 of sales ties up ${nwc:.2f}.")

    # --- WACC
    rf = pack["risk_free"]["rate"]
    braw = pack["beta"]["raw"]
    b = _clip(0.67 * braw + 0.33, config.BETA_FLOOR, config.BETA_CAP) if braw is not None else 1.0
    ke = rf + b * config.EQUITY_RISK_PREMIUM + config.SIZE_PREMIUM
    cap = pack["capital"]
    debt = cap["debt"] or 0
    ints = [abs(r["interest"]) for r in a[-2:] if r.get("interest")]
    kd = (statistics.mean(ints) / debt) if ints and debt > 0 else rf + 0.02
    kd = _clip(kd, rf + 0.01, 0.15)
    E = cap["market_cap"] or 0
    wd = debt / (E + debt) if E + debt > 0 else 0
    wacc = (1 - wd) * ke + wd * kd * (1 - tax)
    why["wacc"] = (f"CAPM: risk-free {rf:.2%} ({pack['risk_free']['source']}) + adjusted beta {b:.2f} × "
                   f"ERP {config.EQUITY_RISK_PREMIUM:.1%} + small-cap premium {config.SIZE_PREMIUM:.1%} = "
                   f"cost of equity {ke:.2%}. Pre-tax cost of debt {kd:.2%} (interest ÷ debt). "
                   f"Market-value weights: debt {wd:.1%}.")
    tg = min(tg, wacc - 0.03)

    mults = [p.get("ev_ebitda") for p in pack.get("peers", []) if p.get("ev_ebitda") and 0 < p["ev_ebitda"] < 60]
    exit_mult = _clip(_median(mults), 4, 25) if mults else None
    why["exit_multiple"] = (f"Median peer EV/EBITDA ({exit_mult:.1f}x) as a cross-check terminal value."
                            if exit_mult else "No usable peer EV/EBITDA; exit-multiple cross-check skipped.")
    return {
        "base_year": base.get("period_end"), "base_revenue": rev0, "years": n,
        "revenue_growth": [round(x, 4) for x in path], "ebit_margin": [round(x, 4) for x in margins],
        "tax_rate": round(tax, 4), "da_pct": round(da, 4), "capex_pct": round(capex, 4),
        "nwc_pct": round(nwc, 4), "terminal_growth": round(tg, 4), "exit_ebitda_multiple": exit_mult,
        "risk_free": rf, "beta_raw": braw, "beta_adjusted": round(b, 3), "erp": config.EQUITY_RISK_PREMIUM,
        "size_premium": config.SIZE_PREMIUM, "cost_of_equity": round(ke, 4), "cost_of_debt_pre_tax": round(kd, 4),
        "debt_weight": round(wd, 4), "wacc": round(wacc, 4), "mid_year": config.MID_YEAR,
        "rationale": why, "overrides": {},
    }


def _forecast(inp):
    rows, rev = [], inp["base_revenue"]
    for t in range(inp["years"]):
        g, m = inp["revenue_growth"][t], inp["ebit_margin"][t]
        prev, rev = rev, rev * (1 + g)
        ebit = rev * m
        nopat = ebit * (1 - inp["tax_rate"])
        da = rev * inp["da_pct"]
        capex = rev * inp["capex_pct"]
        dnwc = inp["nwc_pct"] * (rev - prev)
        rows.append({"year": t + 1, "revenue": rev, "growth": g, "ebit": ebit, "ebit_margin": m,
                     "nopat": nopat, "da": da, "ebitda": ebit + da, "capex": capex, "change_nwc": dnwc,
                     "fcff": nopat + da - capex - dnwc})
    return rows


def _value(inp, rows, wacc, g, cap, shares, px_to_fin, method="gordon"):
    pv = 0
    for r in rows:
        t = r["year"] - (0.5 if inp.get("mid_year") else 0)
        r_df = 1 / (1 + wacc) ** t
        pv += r["fcff"] * r_df
    last = rows[-1]
    if method == "gordon":
        tv = last["fcff"] * (1 + g) / (wacc - g)
    else:
        tv = last["ebitda"] * inp["exit_ebitda_multiple"]
    pv_tv = tv / (1 + wacc) ** inp["years"]
    ev = pv + pv_tv
    eq = ev - cap["debt"] - cap["minority"] - cap["preferred"] + cap["cash"]
    ps = eq / shares if shares else None
    return {"pv_fcff": pv, "terminal_value": tv, "pv_terminal": pv_tv, "enterprise_value": ev,
            "equity_value": eq, "per_share_reporting": ps,
            "per_share_price_ccy": ps / px_to_fin if ps is not None and px_to_fin else None,
            "tv_share_of_ev": pv_tv / ev if ev else None}


def _comps(pack, px_to_fin):
    peers = pack.get("peers", [])
    t, cap = pack["ttm"], pack["capital"]
    shares = cap["shares"]
    bridge = -cap["debt"] - cap["minority"] - cap["preferred"] + cap["cash"]
    metric = {"ev_revenue": t.get("revenue"), "ev_ebitda": t.get("ebitda"), "ev_ebit": t.get("ebit")}
    out = []
    for key, label in [("ev_revenue", "EV / LTM revenue"), ("ev_ebitda", "EV / LTM EBITDA"),
                       ("ev_ebit", "EV / LTM EBIT"), ("pe", "P / E (LTM)")]:
        vals = [p.get(key) for p in peers if p.get(key) and 0 < p[key] < 100]
        if len(vals) < 3:
            continue
        qs = {"p25": _q(vals, .25), "median": _q(vals, .5), "p75": _q(vals, .75)}
        implied = {}
        for k, mult in qs.items():
            if key == "pe":
                ni = t.get("net_income")
                v = mult * ni / shares / px_to_fin if ni and ni > 0 and shares else None
            else:
                base = metric[key]
                v = (mult * base + bridge) / shares / px_to_fin if base and base > 0 and shares else None
            implied[k] = v
        target_mult = None
        if cap["enterprise_value"] and key != "pe" and metric[key] and metric[key] > 0:
            target_mult = cap["enterprise_value"] / metric[key]
        elif key == "pe" and t.get("net_income") and t["net_income"] > 0 and cap["market_cap"]:
            target_mult = cap["market_cap"] / t["net_income"]
        out.append({"method": label, "key": key, "peer_multiples": qs, "n_peers": len(vals),
                    "company_multiple": target_mult, "implied_price": implied})
    return out


def run(pack, inp):
    inp = {**inp, **inp.get("overrides", {})}
    cap = pack["capital"]
    shares = cap["shares"]
    px_to_fin = pack["currency"]["price_to_reporting"]
    price = pack["price"]["last"]
    rows = _forecast(inp)
    wacc, g = inp["wacc"], inp["terminal_growth"]
    base = _value(inp, rows, wacc, g, cap, shares, px_to_fin)
    for r in rows:
        t = r["year"] - (0.5 if inp.get("mid_year") else 0)
        r["discount_factor"] = 1 / (1 + wacc) ** t
        r["pv_fcff"] = r["fcff"] * r["discount_factor"]
    exit_ = _value(inp, rows, wacc, g, cap, shares, px_to_fin, "exit") if inp.get("exit_ebitda_multiple") else None
    implied_exit_mult = base["terminal_value"] / rows[-1]["ebitda"] if rows[-1]["ebitda"] > 0 else None

    w_grid = [round(wacc + d, 4) for d in (-0.01, -0.005, 0, 0.005, 0.01)]
    g_grid = [round(g + d, 4) for d in (-0.01, -0.005, 0, 0.005, 0.01)]
    sens = [[(_value(inp, rows, w, gg, cap, shares, px_to_fin)["per_share_price_ccy"] if w - gg > 0.01 else None)
             for gg in g_grid] for w in w_grid]
    inner = [v for row in sens[1:4] for v in row[1:4] if v is not None]

    comps = _comps(pack, px_to_fin)
    ff = []
    for c in comps:
        ip = c["implied_price"]
        if ip["p25"] is not None and ip["p75"] is not None:
            ff.append({"method": c["method"], "group": "Trading comparables", "low": ip["p25"],
                       "high": ip["p75"], "mid": ip["median"],
                       "note": f"{c['peer_multiples']['p25']:.1f}x–{c['peer_multiples']['p75']:.1f}x across {c['n_peers']} peers"})
    if inner:
        ff.append({"method": "DCF – Gordon growth", "group": "Discounted cash flow", "low": min(inner),
                   "high": max(inner), "mid": base["per_share_price_ccy"],
                   "note": f"WACC {w_grid[1]:.1%}–{w_grid[3]:.1%}, terminal growth {g_grid[1]:.1%}–{g_grid[3]:.1%}"})
    if exit_:
        lo_ = _value({**inp, "exit_ebitda_multiple": inp["exit_ebitda_multiple"] - 2}, rows, wacc, g, cap, shares, px_to_fin, "exit")
        hi_ = _value({**inp, "exit_ebitda_multiple": inp["exit_ebitda_multiple"] + 2}, rows, wacc, g, cap, shares, px_to_fin, "exit")
        ff.append({"method": "DCF – exit multiple", "group": "Discounted cash flow",
                   "low": lo_["per_share_price_ccy"], "high": hi_["per_share_price_ccy"],
                   "mid": exit_["per_share_price_ccy"],
                   "note": f"{inp['exit_ebitda_multiple'] - 2:.1f}x–{inp['exit_ebitda_multiple'] + 2:.1f}x EBITDA in year {inp['years']}"})
    pt = pack["estimates"].get("price_targets") or {}
    if pt.get("low") and pt.get("high"):
        ff.append({"method": "Analyst price targets", "group": "Market", "low": pt["low"], "high": pt["high"],
                   "mid": pt.get("median") or pt.get("mean"), "note": "Consensus range (Yahoo Finance)"})
    if pack["price"].get("low_52w") and pack["price"].get("high_52w"):
        ff.append({"method": "52-week trading range", "group": "Market", "low": pack["price"]["low_52w"],
                   "high": pack["price"]["high_52w"], "mid": price, "note": "Last 12 months"})

    parts, weights = [], []
    if base["per_share_price_ccy"] and base["per_share_price_ccy"] > 0:
        parts.append(base["per_share_price_ccy"]); weights.append(0.5)
    for key in ("ev_ebitda", "pe"):
        c = next((c for c in comps if c["key"] == key and c["implied_price"]["median"]), None)
        if c and c["implied_price"]["median"] > 0:
            parts.append(c["implied_price"]["median"]); weights.append(0.25)
    target = sum(p * w for p, w in zip(parts, weights)) / sum(weights) if parts else None
    upside = target / price - 1 if target and price else None
    rating = None if upside is None else ("Buy" if upside > config.BUY_ABOVE else
                                         "Sell" if upside < config.SELL_BELOW else "Hold")
    flags = []
    if base["tv_share_of_ev"] and base["tv_share_of_ev"] > 0.8:
        flags.append(f"Terminal value is {base['tv_share_of_ev']:.0%} of EV: valuation leans on the long run.")
    if not (0.06 <= wacc <= 0.16):
        flags.append(f"WACC {wacc:.1%} is outside the usual 6–16% range.")
    if exit_ and base["per_share_price_ccy"] and exit_["per_share_price_ccy"]:
        gap = exit_["per_share_price_ccy"] / base["per_share_price_ccy"] - 1
        if abs(gap) > 0.35:
            flags.append(f"Gordon and exit-multiple values differ by {gap:+.0%}: check terminal assumptions.")
    if any(r["fcff"] < 0 for r in rows[:3]):
        flags.append("Negative free cash flow in the first 3 forecast years.")

    return {
        "symbol": pack["symbol"], "price": price, "price_currency": pack["currency"]["price"],
        "reporting_currency": pack["currency"]["reporting"], "inputs": inp, "forecast": rows,
        "gordon": base, "exit_multiple": exit_, "implied_exit_ebitda_multiple": implied_exit_mult,
        "per_share": {"value_price_ccy": base["per_share_price_ccy"],
                      "upside": base["per_share_price_ccy"] / price - 1 if base["per_share_price_ccy"] and price else None},
        "sensitivity": {"wacc": w_grid, "terminal_growth": g_grid, "value_per_share_price_ccy": sens},
        "comps": comps, "football_field": ff,
        "target": {"price": target, "upside": upside, "rating": rating,
                   "method": "50% DCF (Gordon) + 25% EV/EBITDA comps median + 25% P/E comps median "
                             "(re-weighted over whatever is available)",
                   "bands": f"Buy above +{config.BUY_ABOVE:.0%}, Sell below {config.SELL_BELOW:.0%}"},
        "flags": flags,
    }


def main():
    sym = sys.argv[1]
    d = os.path.join(ROOT, "research", "packs", sym)
    with open(os.path.join(d, "pack.json")) as f:
        pack = json.load(f)
    inp = pack["dcf_inputs"]
    ap = os.path.join(d, "assumptions.json")
    if os.path.exists(ap):
        with open(ap) as f:
            inp = {**inp, **json.load(f)}
    out = run(pack, inp)
    with open(os.path.join(d, "dcf.json"), "w") as f:
        json.dump(out, f, indent=1, default=float)
    t = out["target"]
    print(f"{sym}: DCF {out['per_share']['value_price_ccy']:.2f} | target {t['price']:.2f} "
          f"({t['upside']:+.1%}) {t['rating']} | flags: {out['flags']}")


if __name__ == "__main__":
    main()
