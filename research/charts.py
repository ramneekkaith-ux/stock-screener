"""Report charts from a research pack (PNG, 16:9-friendly, house style).

Usage:  python -m research.charts                # every ticker in research/queue.json
        python -m research.charts HRMY           # one ticker
Optional research/packs/<T>/annotations.json: [{"date": "2025-04-03", "label": "Tariff shock"}, ...]
is drawn on the price chart.
"""
import json
import os
import sys
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAVY, LIGHT, GREY, RED, GREEN = "#0B1F3F", "#7FA7D6", "#9AA3AE", "#C0392B", "#2E7D32"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.edgecolor": GREY, "axes.labelcolor": "#333",
                     "xtick.color": "#555", "ytick.color": "#555", "figure.dpi": 200})


def _ccy(pack):
    c = pack["currency"]["price"]
    return {"GBp": "p", "USD": "$", "GBP": "£", "EUR": "€"}.get(c, c + " ")


def price_chart(pack, out, years=3):
    h = pack["price"]["history_5y"]
    if not h:
        return
    cut = h[-1][0][:4]
    start = f"{int(cut) - years}{h[-1][0][4:]}"
    s = [(datetime.fromisoformat(d), v) for d, v in h if d >= start]
    b = [(datetime.fromisoformat(d), v) for d, v in pack["price"]["benchmark"]["history_5y"] if d >= start]
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    ax.plot([d for d, _ in s], [v for _, v in s], color=NAVY, lw=1.4, label=pack["symbol"])
    if b:
        base = s[0][1] / b[0][1]
        ax.plot([d for d, _ in b], [v * base for _, v in b], color=LIGHT, lw=1.1,
                label=f"{pack['price']['benchmark']['name']} (rebased)")
    ann_path = os.path.join(os.path.dirname(out), "..", "annotations.json")
    if os.path.exists(ann_path):
        with open(ann_path) as f:
            anns = json.load(f)
        for i, a in enumerate(anns):
            d = a["date"]
            near = min(s, key=lambda x: abs((x[0] - datetime.fromisoformat(d)).days))
            ax.annotate(a["label"], xy=near, xytext=(0, 38 if i % 2 == 0 else -46), textcoords="offset points",
                        ha="center", fontsize=7.5, color="#222",
                        bbox=dict(boxstyle="round,pad=0.3", fc="#F1F3F6", ec=GREY, ls="--"),
                        arrowprops=dict(arrowstyle="-", color=GREY, ls="--"))
    ax.set_ylabel(f"Share price ({pack['currency']['price']})")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.grid(axis="y", color="#E6E8EB", lw=0.6)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def financials_chart(pack, out):
    a = [r for r in pack["annual"] if r.get("revenue")][-4:]
    if not a:
        return
    yrs = [r["period_end"][:4] for r in a]
    fin = pack["currency"]["reporting"]
    rev = [r["revenue"] / 1e6 for r in a]
    em = [(r.get("ebit_margin") or 0) * 100 for r in a]
    fcf = [(r.get("fcf") or 0) / 1e6 for r in a]
    fig, axes = plt.subplots(1, 3, figsize=(9, 2.8))
    for ax, vals, title, fmt in [(axes[0], rev, f"Revenue ({fin}m)", "{:,.0f}"),
                                 (axes[1], em, "EBIT margin (%)", "{:.1f}%"),
                                 (axes[2], fcf, f"Free cash flow ({fin}m)", "{:,.0f}")]:
        bars = ax.bar(yrs, vals, color=LIGHT, width=0.6)
        ax.set_title(title, fontsize=10, color=NAVY, fontweight="bold")
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), fmt.format(v),
                    ha="center", va="bottom", fontsize=8)
        if title.startswith("Revenue"):
            for i in range(1, len(vals)):
                if vals[i - 1]:
                    g = vals[i] / vals[i - 1] - 1
                    ax.text(i, vals[i] * 0.5, f"{g:+.1%}", ha="center", color="white", fontsize=8,
                            bbox=dict(boxstyle="square,pad=0.25", fc=NAVY, ec=NAVY))
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def peers_chart(pack, out):
    ps = [p for p in pack.get("peers", []) if p.get("roe") is not None and p.get("revenue_usd")]
    me_rev = (pack["ttm"].get("revenue") or 0) * pack["currency"]["reporting_to_usd"] / 1e9
    me_roe = pack["annual"][-1].get("roe") if pack["annual"] else None
    if not ps or me_roe is None:
        return
    fig, ax = plt.subplots(figsize=(6, 3.6))
    ax.scatter([p["revenue_usd"] / 1e9 for p in ps], [p["roe"] * 100 for p in ps], s=40, color=LIGHT, zorder=3)
    for p in ps:
        ax.annotate(p["symbol"], (p["revenue_usd"] / 1e9, p["roe"] * 100), xytext=(4, 4),
                    textcoords="offset points", fontsize=7.5, color="#333")
    ax.scatter([me_rev], [me_roe * 100], s=90, color=NAVY, zorder=4)
    ax.annotate(pack["symbol"], (me_rev, me_roe * 100), xytext=(5, -10), textcoords="offset points",
                fontsize=8.5, color=NAVY, fontweight="bold")
    ax.set_xscale("log")
    ax.set_xlabel("LTM revenue (US$bn, log scale)")
    ax.set_ylabel("Return on equity (%)")
    ax.grid(color="#E6E8EB", lw=0.6)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def football_field(pack, model, out):
    ff = [f for f in model["football_field"] if f.get("low") is not None and f.get("high") is not None]
    if not ff:
        return
    fig, ax = plt.subplots(figsize=(7.5, 0.55 * len(ff) + 1.2))
    for i, f in enumerate(reversed(ff)):
        lo, hi = sorted([f["low"], f["high"]])
        ax.barh(i, hi - lo, left=lo, color=NAVY, height=0.5)
        ax.text(lo, i, f"{lo:,.1f} ", ha="right", va="center", fontsize=8)
        ax.text(hi, i, f" {hi:,.1f}", ha="left", va="center", fontsize=8)
    ax.set_yticks(range(len(ff)))
    ax.set_yticklabels([f["method"] for f in reversed(ff)], fontsize=8.5)
    price = model["price"]
    ax.axvline(price, color=RED, ls="--", lw=1.2)
    ax.text(price, len(ff) - 0.4, f"Current {price:,.1f}", color=RED, fontsize=8, ha="center")
    if model["target"]["price"]:
        tp = model["target"]["price"]
        ax.axvline(tp, color=LIGHT, ls="--", lw=1.2)
        ax.text(tp, -0.9, f"Target {tp:,.1f}", color="#3C6EA8", fontsize=8, ha="center")
    ax.set_xlabel(f"Implied value per share ({pack['currency']['price']})")
    ax.spines["left"].set_visible(False)
    ax.grid(axis="x", color="#E6E8EB", lw=0.6)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def draw(sym):
    d = os.path.join(ROOT, "research", "packs", sym)
    with open(os.path.join(d, "pack.json")) as f:
        pack = json.load(f)
    with open(os.path.join(d, "dcf.json")) as f:
        model = json.load(f)
    cd = os.path.join(d, "charts")
    os.makedirs(cd, exist_ok=True)
    price_chart(pack, os.path.join(cd, "price_3y.png"))
    financials_chart(pack, os.path.join(cd, "financials.png"))
    peers_chart(pack, os.path.join(cd, "peers_roe_revenue.png"))
    football_field(pack, model, os.path.join(cd, "football_field.png"))
    print(sym, sorted(os.listdir(cd)))


def main():
    syms = sys.argv[1:]
    if not syms:
        with open(os.path.join(ROOT, "research", "queue.json")) as f:
            syms = [q["symbol"] for q in json.load(f)["queue"]]
    for s in syms:
        if os.path.exists(os.path.join(ROOT, "research", "packs", s, "pack.json")):
            draw(s)


if __name__ == "__main__":
    main()
