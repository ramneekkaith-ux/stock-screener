"""Render an equity research report as a Claude Slides deck (16:9, institutional template).

Inputs, per ticker in research/packs/<T>/:
  pack.json, dcf.json      numbers (from research.pack / research.dcf)
  report.json              the analyst's words (see PLAYBOOK.md)
  assets.json              {"price_3y": "/_blob/..", "financials": .., "peers": .., "football_field": ..}
Output: research/decks/<T>/project/{deck.json, deck.css, slides/*.html}

Usage: python -m research.render_slides HRMY
"""
import html
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRM = "[Firm name]"

CSS = """
section { background:#FBFBF9; color:#1B2433; font-family:'Inter', Arial, sans-serif; padding:72px 96px 120px; display:flex; flex-direction:column; gap:20px; counter-increment: page; }
.eyebrow { font-size:26px; color:#7A8493; font-weight:400; }
.title { font-size:52px; font-weight:600; color:#0B1F3F; line-height:1.1; }
.rule { border-top:3px solid #0B1F3F; }
.sub { font-size:28px; font-style:italic; font-weight:600; color:#8A93A0; line-height:1.2; }
.row { display:flex; gap:32px; }
.col { display:flex; flex-direction:column; gap:14px; flex:1; }
.bar { background:#0B1F3F; border-radius:8px; padding:10px 20px; }
.bar p { color:#FBFBF9; font-size:28px; font-weight:600; }
.body { font-size:24px; line-height:1.35; color:#1B2433; }
.muted { font-size:24px; color:#5A6472; line-height:1.3; }
.bul { font-size:24px; line-height:1.35; color:#1B2433; padding-left:28px; display:flex; flex-direction:column; gap:8px; }
.panel { background:#EEF1F5; border-radius:8px; padding:16px 20px; display:flex; flex-direction:column; gap:8px; }
.panel h3 { font-size:26px; color:#0B1F3F; font-weight:600; }
.tbl { font-size:24px; color:#1B2433; font-variant-numeric:tabular-nums; }
.tbl-sm { font-size:24px; color:#1B2433; font-variant-numeric:tabular-nums; }
.chip { background:#0B1F3F; border-radius:8px; padding:8px 18px; }
.chip p { color:#FBFBF9; font-size:26px; font-weight:600; white-space:nowrap; }
.chip-buy { background:#1F6F43; } .chip-hold { background:#8A6D1E; } .chip-sell { background:#9B2C2C; }
.head { display:flex; justify-content:space-between; align-items:flex-start; gap:24px; }
.foot { position:absolute; left:96px; bottom:40px; width:1728px; display:flex; justify-content:space-between; }
.foot p { font-size:24px; color:#8A93A0; }
.big { font-size:56px; font-weight:600; color:#0B1F3F; line-height:1.05; }
.label { font-size:24px; color:#5A6472; }
.card { background:#EEF1F5; border-radius:8px; padding:16px 20px; display:flex; flex-direction:column; gap:4px; flex:1; }
.up { color:#1F6F43; } .down { color:#9B2C2C; }
.cover { background:#0B1F3F; justify-content:center; gap:28px; padding:128px; }
.cover .t1 { font-size:88px; font-weight:600; color:#FBFBF9; line-height:1.05; }
.cover .t2 { font-size:36px; color:#C9D3E2; line-height:1.25; }
.cover .t3 { font-size:28px; color:#9FB1CC; }
.draft { background:#C99A2E; border-radius:6px; padding:6px 14px; align-self:flex-start; }
.draft p { font-size:24px; font-weight:600; color:#14213D; }
.porter { display:flex; gap:16px; align-items:stretch; }
.porter .k { background:#0B1F3F; border-radius:8px; padding:10px 14px; width:300px; display:flex; align-items:center; }
.porter .k p { color:#FBFBF9; font-size:24px; font-weight:600; }
.porter .v { background:#EEF1F5; border-radius:8px; padding:10px 16px; flex:1; display:flex; align-items:center; }
.porter .v p { font-size:24px; line-height:1.3; }
.cat { background:#EEF1F5; border-radius:8px; padding:16px; flex:1; display:flex; flex-direction:column; gap:8px; border-top:6px solid #0B1F3F; }
.cat .d { font-size:24px; font-weight:600; color:#0B1F3F; }
"""


def esc(s):
    return html.escape(str(s if s is not None else "–"), quote=True)


def money(x, d=1):
    if x is None:
        return "–"
    return f"{x:,.{d}f}"


def pct(x, d=1):
    return "–" if x is None else f"{x * 100:.{d}f}%"


def short(name, n=28):
    name = str(name)
    for suf in [", Inc.", " Inc.", " Ltd.", " Limited", " Corporation", " Corp.", " plc", " PLC", " Holdings", " Co."]:
        name = name.replace(suf, "")
    return name if len(name) <= n else name[: n - 1].rstrip() + "…"


def mult(x):
    if x is None:
        return "–"
    return "n/m" if x > 100 or x < 0 else f"{x:.1f}x"


class Deck:
    def __init__(self, t):
        self.t = t
        d = os.path.join(ROOT, "research", "packs", t)
        self.pack = json.load(open(os.path.join(d, "pack.json")))
        self.dcf = json.load(open(os.path.join(d, "dcf.json")))
        self.r = json.load(open(os.path.join(d, "report.json")))
        self.assets = json.load(open(os.path.join(d, "assets.json")))
        self.slides = []
        p = self.pack
        self.pc = {"USD": "$", "GBp": "", "GBP": "£", "EUR": "€"}.get(p["currency"]["price"], "")
        self.ps = "p" if p["currency"]["price"] == "GBp" else ""
        self.fc = p["currency"]["reporting"]
        self.name = p["info"].get("longName") or t
        self.asof = p["generated_at"][:10]

    def px(self, v, d=2):
        return "–" if v is None else f"{self.pc}{v:,.{d}f}{self.ps}"

    def m(self, v, d=1):
        """reporting currency amount -> millions"""
        return "–" if v is None else f"{v / 1e6:,.{d}f}"

    # ------------------------------------------------------------ chrome
    def frame(self, sid, eyebrow, title, sub, body, source, notes=""):
        foot = (f'<div class="foot"><p>Source: {esc(source)}</p>'
                f'<p>{esc(self.name)} · {esc(FIRM)} · DRAFT</p></div>')
        sub_html = f'<p class="sub">{esc(sub)}</p>' if sub else ""
        aside = f"<aside>{esc(notes)}</aside>" if notes else ""
        self.slides.append((sid, f'<section id="{sid}">\n<p class="eyebrow">{esc(eyebrow)}</p>\n'
                                 f'<h2 class="title">{esc(title)}</h2>\n<div class="rule"></div>\n{sub_html}\n'
                                 f'{body}\n{foot}\n{aside}</section>'))

    def bar(self, text):
        return f'<div class="bar"><p>{esc(text)}</p></div>'

    def bullets(self, items, cls="bul"):
        return f'<ul class="{cls}">' + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"

    def table(self, header, rows, widths, cls="tbl", align=None):
        align = align or (["left"] + ["right"] * (len(header) - 1))
        h = "<tr>" + "".join(f'<th style="width:{w}%;text-align:{a}">{esc(c)}</th>'
                             for c, w, a in zip(header, widths, align)) + "</tr>"
        body = ""
        for r in rows:
            bg = ""
            if isinstance(r, dict):
                bg = f' style="background:{r["bg"]}"'
                r = r["cells"]
            body += f"<tr{bg}>" + "".join(f'<td style="text-align:{a}">{esc(c)}</td>' for c, a in zip(r, align)) + "</tr>"
        return f'<table class="{cls}">{h}{body}</table>'

    def img(self, key, w, h, alt):
        src = self.assets.get(key)
        if not src:
            return f'<div class="panel" style="width:{w}px;height:{h}px"><p class="muted">Chart unavailable</p></div>'
        return f'<img src="{src}" alt="{esc(alt)}" style="width:{w}px;height:{h}px;object-fit:contain">'

    # ------------------------------------------------------------ slides
    def cover(self):
        tg = self.dcf["target"]
        rating = self.r.get("rating") or tg["rating"]
        body = (f'<section id="cover" class="cover">\n<div class="draft"><p>DRAFT – for internal review</p></div>\n'
                f'<p class="t3">Equity research · Initiation of coverage · {esc(self.asof)}</p>\n'
                f'<h1 class="t1">{esc(self.name)}</h1>\n'
                f'<p class="t2">{esc(self.p_ticker())} · {esc(self.pack["info"].get("sector"))} · {esc(self.pack["info"].get("industry"))}</p>\n'
                f'<p class="t2"><b>{esc(rating)}</b> · Target price {esc(self.px(self.r.get("target_price", tg["price"])))} · '
                f'Last price {esc(self.px(self.dcf["price"]))}</p>\n'
                f'<p class="t3">{esc(self.r["headline"])}</p>\n'
                f'<aside>{esc(self.r.get("cover_note", ""))}</aside></section>')
        self.slides.append(("cover", body))

    def p_ticker(self):
        ex = self.pack["info"].get("fullExchangeName") or self.pack["info"].get("exchange") or ""
        return f"{ex}: {self.t}"

    def exec_summary(self):
        tg, g = self.dcf["target"], self.dcf["gordon"]
        target = self.r.get("target_price", tg["price"])
        upside = target / self.dcf["price"] - 1
        rating = self.r.get("rating") or tg["rating"]
        cls = {"Buy": "chip-buy", "Hold": "chip-hold", "Sell": "chip-sell"}.get(rating, "")
        fc = self.fc
        rows = [
            [f"PV of free cash flow ({fc}m)", self.m(g["pv_fcff"])],
            [f"PV of terminal value ({fc}m)", self.m(g["pv_terminal"])],
            [f"Enterprise value, DCF ({fc}m)", self.m(g["enterprise_value"])],
            [f"Net debt and adjustments ({fc}m)", self.m(g["enterprise_value"] - g["equity_value"])],
            [f"Equity value ({fc}m)", self.m(g["equity_value"])],
            ["DCF value per share", self.px(self.dcf["per_share"]["value_price_ccy"])],
            ["Target price (blended)", self.px(target)],
            ["Upside to last price", pct(upside)],
        ]
        body = (f'<div class="row" style="flex:1">'
                f'<div class="col" style="flex:1.05">{self.bar("1. Narrative")}{self.bullets(self.r["narrative"])}</div>'
                f'<div class="col" style="flex:1">'
                f'<div class="head"><div class="chip {cls}"><p>{esc(rating)} · Target {esc(self.px(target))}</p></div>'
                f'<p class="muted">Last {esc(self.px(self.dcf["price"]))} · {esc(self.asof)}</p></div>'
                f'{self.bar("2. Valuation summary")}'
                f'{self.table(["", "Value"], rows, [70, 30])}'
                f'</div></div>')
        self.frame("exec", "Executive summary", self.r["headline"], self.r["subheadline"], body,
                   f"Company filings; Yahoo Finance via research pack ({self.asof}); analyst DCF",
                   self.r.get("exec_notes", ""))

    def exec_chart(self):
        body = (f'<div class="row" style="flex:1;align-items:flex-start">'
                f'<div class="col" style="flex:1.6">{self.bar("3. Share price, last 3 years vs benchmark")}'
                f'{self.img("price_3y", 1040, 472, "Share price over three years against the benchmark index")}</div>'
                f'<div class="col" style="flex:1">{self.bar("What the market is pricing")}'
                f'{self.bullets(self.r["market_pricing"])}</div></div>')
        self.frame("exec2", "Executive summary", "Where the stock stands", None, body,
                   f"Yahoo Finance price history to {self.asof}; events from company releases")

    def business(self):
        b = self.r["business"]
        segs = "".join(f'<div class="panel"><h3>{esc(s["name"])}</h3><p class="body">{esc(s["text"])}</p></div>'
                       for s in b["segments"])
        h = self.pack["holders"]
        maj = {r.get("Breakdown") or r.get("index"): r.get("Value") for r in h.get("major", [])}
        inst = maj.get("institutionsPercentHeld")
        own = [["Insiders", pct(maj.get("insidersPercentHeld"))],
               ["Institutions", "~100%" if inst and inst > 1 else pct(inst)]]
        for r in h.get("institutions", [])[:5]:
            own.append([str(r.get("Holder"))[:28], pct(r.get("pctHeld"))])
        body = (f'<div class="row" style="flex:1">'
                f'<div class="col">{self.bar("1. Business overview")}{self.bullets(b["overview"])}</div>'
                f'<div class="col">{self.bar("2. Segments")}{segs}</div>'
                f'<div class="col" style="flex:0.9">{self.bar("3. Ownership")}'
                f'{self.table(["Holder", "% held"], own, [72, 28])}</div></div>')
        self.frame("business", "Business overview", b["title"], b.get("subtitle"), body,
                   f"{b.get('source', 'Company filings')}; ownership from Yahoo Finance ({self.asof})")

    def financials(self):
        c = self.pack["capital"]
        ev_rows = [["Share price", self.px(self.dcf["price"])],
                   ["Shares (m)", money(c["shares"] / 1e6)],
                   [f"Market cap ({self.fc}m)", self.m(c["market_cap"])],
                   [f"+ Total debt ({self.fc}m)", self.m(c["debt"])],
                   [f"+ Minority interest ({self.fc}m)", self.m(c["minority"])],
                   [f"– Cash ({self.fc}m)", self.m(c["cash"])],
                   [f"Enterprise value ({self.fc}m)", self.m(c["enterprise_value"])]]
        body = (f'<div class="row" style="flex:1;align-items:flex-start">'
                f'<div class="col" style="flex:1.75">{self.bar("4. Key financials")}'
                f'{self.img("financials", 1080, 336, "Revenue, EBIT margin and free cash flow by year")}'
                f'{self.bullets(self.r["business"]["financial_points"])}</div>'
                f'<div class="col" style="flex:1">{self.bar("5. Enterprise value")}'
                f'{self.table(["", "Value"], ev_rows, [64, 36])}'
                f'<p class="muted">Balance sheet at {esc(c.get("as_of_balance_sheet"))}; price {esc(self.asof)}.</p></div></div>')
        self.frame("financials", "Business overview", self.r["business"]["financials_title"], None, body,
                   f"Company annual reports via Yahoo Finance; research pack {self.asof}")

    def industry(self):
        ind = self.r["industry"]
        tw = "".join(f'<div class="panel"><h3>▲ {esc(x["title"])}</h3><p class="body">{esc(x["text"])}</p></div>' for x in ind["tailwinds"])
        hw = "".join(f'<div class="panel"><h3>▼ {esc(x["title"])}</h3><p class="body">{esc(x["text"])}</p></div>' for x in ind["headwinds"])
        body = (f'<div class="row" style="flex:1">'
                f'<div class="col" style="flex:1.1">{self.bar("1. Market")}{self.bullets(ind["market"])}</div>'
                f'<div class="col">{self.bar("2. Tailwinds")}{tw}</div>'
                f'<div class="col">{self.bar("3. Headwinds")}{hw}</div></div>')
        self.frame("industry", "Industry overview", ind["title"], ind.get("subtitle"), body, ind["source"])

    def competition(self):
        c = self.r["competition"]
        porter = "".join(f'<div class="porter"><div class="k"><p>{esc(k)}</p></div><div class="v"><p>{esc(v)}</p></div></div>'
                         for k, v in c["porter"])
        body = (f'<div class="row" style="flex:1">'
                f'<div class="col" style="flex:0.9">{self.bar("1. Positioning: ROE vs revenue")}'
                f'{self.img("peers", 760, 456, "Return on equity against revenue for the company and peers")}'
                f'{self.bullets(c["points"])}</div>'
                f'<div class="col" style="flex:1.1">{self.bar("2. Porter’s five forces")}{porter}</div></div>')
        self.frame("competition", "Competitive analysis", c["title"], c.get("subtitle"), body, c["source"])

    def theses(self):
        for i, th in enumerate(self.r["theses"], 1):
            ev = th.get("evidence", {})
            right = ""
            if ev.get("metrics"):
                cards = "".join(f'<div class="card"><p class="big">{esc(m["value"])}</p><p class="label">{esc(m["label"])}</p></div>'
                                for m in ev["metrics"])
                right += f'<div class="row" style="gap:16px">{cards}</div>'
            if ev.get("table"):
                t = ev["table"]
                right += self.table(t["header"], t["rows"], t["widths"])
            if ev.get("points"):
                right += self.bullets(ev["points"])
            body = (f'<div class="row" style="flex:1">'
                    f'<div class="col">{self.bar("The argument")}{self.bullets(th["points"])}'
                    f'<div class="panel"><h3>What would prove us wrong</h3><p class="body">{esc(th["risk"])}</p></div></div>'
                    f'<div class="col">{self.bar(ev.get("title", "Evidence"))}{right}</div></div>')
            self.frame(f"thesis{i}", f"Investment thesis {i}", th["title"], th.get("subtitle"), body, th["source"])

    def comps(self):
        peers = [p for p in self.pack["peers"] if p.get("symbol") not in set(self.dcf["inputs"].get("exclude_peers", []))]
        rows = []
        for p in peers:
            rows.append([short(p.get("name") or p["symbol"]), p["symbol"],
                         money((p.get("market_cap_usd") or 0) / 1e9, 2), mult(p.get("ev_revenue")),
                         mult(p.get("ev_ebitda")), mult(p.get("ev_ebit")), mult(p.get("pe")),
                         pct(p.get("ebitda_margin")), pct(p.get("roe"))])
        med = {c["key"]: c["peer_multiples"]["median"] for c in self.dcf["comps"]}
        own = {c["key"]: c["company_multiple"] for c in self.dcf["comps"]}
        t = self.pack["ttm"]
        ebm = (t.get("ebitda") or 0) / t["revenue"] if t.get("revenue") else None
        roe = self.pack["annual"][-1].get("roe") if self.pack["annual"] else None
        rows.append({"bg": "#DDE3EC", "cells": ["Peer median", "", "", mult(med.get("ev_revenue")), mult(med.get("ev_ebitda")),
                                                 mult(med.get("ev_ebit")), mult(med.get("pe")), "", ""]})
        rows.append({"bg": "#C9D3E2", "cells": [short(self.name), self.t, money(self.pack["capital"]["market_cap_usd"] / 1e9, 2),
                                                 mult(own.get("ev_revenue")), mult(own.get("ev_ebitda")), mult(own.get("ev_ebit")),
                                                 mult(own.get("pe")), pct(ebm), pct(roe)]})
        tbl = self.table(["Company", "Ticker", "Mkt cap $bn", "EV/Rev", "EV/EBITDA", "EV/EBIT", "P/E", "EBITDA m.", "ROE"],
                         rows, [24, 9, 10, 9, 11, 9, 8, 10, 10],
                         align=["left", "left"] + ["right"] * 7)
        excl = self.dcf["inputs"].get("exclude_reason")
        note = self.r["comps"]["note"] + (f" Excluded from multiples: {excl}" if excl else "")
        body = f'{tbl}<p class="muted">{esc(note)}</p>'
        self.frame("comps", "Comparable company analysis", self.r["comps"]["title"], self.r["comps"].get("subtitle"), body,
                   f"Yahoo Finance, LTM multiples as of {self.asof}; peer set chosen by the analyst")

    def dcf_table(self):
        f = self.dcf["forecast"]
        yrs = [0, 1, 2, 3, 4, 9]
        base_year = int(self.dcf["inputs"]["base_year"][:4])
        hdr = [f"{self.fc}m"] + [f"{base_year + f[i]['year']}E" for i in yrs]
        def row(label, key, fmt=lambda v: f"{v / 1e6:,.0f}"):
            return [label] + [fmt(f[i][key]) for i in yrs]
        rows = [row("Revenue", "revenue"), row("Growth", "growth", pct), row("EBIT", "ebit"),
                row("EBIT margin", "ebit_margin", pct), row("NOPAT", "nopat"), row("+ D&A", "da"),
                row("– Capex", "capex"), row("– Change in working capital", "change_nwc"),
                row("Unlevered free cash flow", "fcff"), row("Discount factor", "discount_factor", lambda v: f"{v:.3f}"),
                row("PV of free cash flow", "pv_fcff")]
        rows[8] = {"bg": "#DDE3EC", "cells": rows[8]}
        tbl = self.table(hdr, rows, [28, 12, 12, 12, 12, 12, 12])
        body = (f'{tbl}<p class="muted">Years 6–9 are modelled but not shown. Mid-year discounting. '
                f'Stock-based compensation stays in EBIT as a cost.</p>')
        self.frame("dcf", "Assumptions & valuation", "Discounted cash flow: 10-year forecast", self.r["dcf"]["subtitle"], body,
                   "Analyst model (research/dcf.py); history from company filings via Yahoo Finance")

    def dcf_sens(self):
        s = self.dcf["sensitivity"]
        hdr = ["WACC \\ g"] + [pct(g) for g in s["terminal_growth"]]
        rows = []
        for w, vals in zip(s["wacc"], s["value_per_share_price_ccy"]):
            r = [pct(w)] + [self.px(v) for v in vals]
            rows.append({"bg": "#DDE3EC", "cells": r} if abs(w - self.dcf["inputs"]["wacc"]) < 1e-6 else r)
        tbl = self.table(hdr, rows, [20, 16, 16, 16, 16, 16])
        inp = self.dcf["inputs"]
        reasons = dict(inp.get("rationale", {}))
        ov = inp.get("override_reasons", {}) or {}
        if "revenue_growth" in ov:
            reasons.pop("growth", None)
        reasons.update(ov)
        order = ["growth", "revenue_growth", "ebit_margin", "wacc", "reinvestment", "terminal_growth"]
        items = [reasons[k] for k in order if k in reasons][:4]
        body = (f'<div class="row" style="flex:1">'
                f'<div class="col" style="flex:1">{self.bar("Value per share: WACC × terminal growth")}{tbl}'
                f'<p class="muted">WACC {pct(inp["wacc"])} · terminal growth {pct(inp["terminal_growth"])} · '
                f'terminal value {pct(self.dcf["gordon"]["tv_share_of_ev"], 0)} of EV</p></div>'
                f'<div class="col" style="flex:1">{self.bar("Key assumptions")}{self.bullets(items)}</div></div>')
        self.frame("dcf2", "Assumptions & valuation", "DCF sensitivity and assumptions", None, body,
                   "Analyst model; assumptions as stated")

    def valuation(self):
        sc = self.dcf.get("scenarios") or []
        right = ""
        if sc:
            rows = [[x["name"], pct(x["weight"], 0), self.px(x["value"])] for x in sc]
            right += self.table(["Scenario", "Weight", "Value"], rows, [56, 18, 26])
            right += self.bullets([f'{x["name"]}: {x["description"]}' for x in sc])
        right += self.bullets(self.r["valuation"]["points"])
        body = (f'<div class="row" style="flex:1;align-items:flex-start">'
                f'<div class="col" style="flex:1.5">{self.img("football_field", 1000, 560, "Football field of valuation ranges by method")}</div>'
                f'<div class="col" style="flex:1">{self.bar("How we get to the target")}{right}</div></div>')
        self.frame("valuation", "Assumptions & valuation", self.r["valuation"]["title"], self.dcf["target"]["method"], body,
                   f"Analyst model; peer multiples and analyst targets from Yahoo Finance ({self.asof})")

    def risks(self):
        rk = self.r["risks"]
        rows = "".join(f'<div class="porter"><div class="k" style="width:520px"><p>{esc(x["risk"])}</p></div>'
                       f'<div class="v"><p>{esc(x["mitigant"])}</p></div></div>' for x in rk["items"])
        cats = "".join(f'<div class="cat"><p class="d">{esc(c["when"])}</p><p class="body">{esc(c["what"])}</p></div>'
                       for c in rk["catalysts"])
        body = (f'<div class="row"><div class="col" style="flex:0.6">{self.bar("Risks")}</div>'
                f'<div class="col">{self.bar("Mitigants")}</div></div>{rows}'
                f'{self.bar("Catalyst path")}<div class="row" style="gap:16px">{cats}</div>')
        self.frame("risks", "Risks & catalysts", rk["title"], None, body, rk["source"])

    def scorecard(self):
        s = self.pack.get("screen") or {}
        p, m = s.get("pillars", {}), s.get("metrics", {})
        cards = "".join(f'<div class="card"><p class="big">{esc(money(p.get(k), 1))}</p><p class="label">{esc(l)} (0–10)</p></div>'
                        for k, l in [("growth", "Growth consistency"), ("cashflow", "Cash flow"),
                                     ("quality", "Quality & resilience"), ("management", "Management & ownership")])
        rows = [["3-yr revenue CAGR", pct(m.get("rev_cagr"))], ["FCF margin", pct(m.get("fcf_margin"))],
                ["FCF / net income", mult(m.get("fcf_conversion"))], ["Average ROIC", pct(m.get("roic_avg"))],
                ["Gross margin", pct(m.get("gross_margin"))], ["Net debt / EBITDA", "net cash" if (m.get("net_debt_ebitda") or 0) < 0 else mult(m.get("net_debt_ebitda"))],
                ["Insider ownership", pct(m.get("insider_pct"))], ["Share count change / yr", pct(m.get("share_cagr"))]]
        body = (f'<div class="row" style="gap:16px"><div class="card" style="background:#0B1F3F"><p class="big" style="color:#FBFBF9">{esc(money(s.get("score"), 1))}</p>'
                f'<p class="label" style="color:#C9D3E2">Screen score (0–100) · {esc(s.get("tier"))}</p></div>{cards}</div>'
                f'<div class="row"><div class="col">{self.table(["Metric", "Value"], rows[:4], [65, 35])}</div>'
                f'<div class="col">{self.table(["Metric", "Value"], rows[4:], [65, 35])}</div></div>'
                f'<p class="muted">Why this stock was picked: it scored in the top tier of our daily US/UK small-cap fundamental screen '
                f'(red-flag exclusions, then 22 metrics across four pillars).</p>')
        self.frame("scorecard", "Quant screen", "How the stock scores on our screen", None, body,
                   f"Stock screener results, {(s.get('date') or self.asof)}")

    def wacc(self):
        i = self.dcf["inputs"]
        rows = [["Risk-free rate", pct(i["risk_free"], 2)], ["Raw beta", money(i["beta_raw"], 2) if i.get("beta_raw") else "–"],
                ["Adjusted beta (Blume)", money(i["beta_adjusted"], 2)], ["Equity risk premium", pct(i["erp"], 2)],
                ["Small-cap premium", pct(i["size_premium"], 2)], ["Cost of equity", pct(i["cost_of_equity"], 2)],
                ["Pre-tax cost of debt", pct(i["cost_of_debt_pre_tax"], 2)], ["Tax rate", pct(i["tax_rate"], 1)],
                ["Debt / (debt + equity)", pct(i["debt_weight"], 1)], ["WACC (model)", pct(self.pack["dcf_inputs"]["wacc"], 2)],
                ["WACC used", pct(i["wacc"], 2)]]
        rf = self.pack["risk_free"]
        body = (f'<div class="row" style="flex:1"><div class="col" style="flex:1">{self.table(["Input", "Value"], rows, [65, 35])}</div>'
                f'<div class="col" style="flex:1">{self.bullets([i["rationale"]["wacc"], "Risk-free: " + rf["source"] + (" as of " + rf["as_of"] if rf.get("as_of") else "") + ".", "Beta: " + self.pack["beta"]["source"] + ".", (i.get("override_reasons") or {}).get("wacc", "No override to the model WACC.")])}</div></div>')
        self.frame("wacc", "Appendix A", "WACC calculation", None, body, "Yahoo Finance; analyst assumptions")

    def references(self):
        refs = self.r["references"]
        half = (len(refs) + 1) // 2
        cols = "".join(f'<div class="col">{self.bullets(refs[a:b])}</div>' for a, b in [(0, half), (half, len(refs))])
        body = f'<div class="row" style="flex:1">{cols}</div>'
        self.frame("refs", "Appendix B", "References", None, body, "As listed")

    def disclaimer(self):
        text = [
            "DRAFT FOR INTERNAL REVIEW. Not approved for distribution. This document has not been reviewed or approved by an authorised person and must not be sent to clients until it has been.",
            "This report is for information only and is not a personal recommendation or an offer to buy or sell any security. It does not take into account any reader’s objectives, financial situation or needs.",
            "Figures are drawn from company filings and third-party data (Yahoo Finance and the sources listed) believed to be reliable but not independently verified. Forecasts, target prices and ratings are estimates and may prove wrong. Past performance is not a guide to future returns; the value of investments can fall as well as rise.",
            "Prepared with the help of automated screening and AI-assisted research tools; all figures should be checked against primary sources before use.",
            "Disclosures: [to be completed by the firm: holdings in the security, conflicts of interest, analyst certification, regulatory status].",
        ]
        body = self.bullets(text)
        self.frame("disclaimer", "Important information", "Disclaimer and disclosures", None, body, FIRM)

    def build(self):
        self.cover(); self.exec_summary(); self.exec_chart(); self.business(); self.financials()
        self.industry(); self.competition(); self.theses(); self.comps(); self.dcf_table(); self.dcf_sens()
        self.valuation(); self.risks(); self.scorecard(); self.wacc(); self.references(); self.disclaimer()
        out = os.path.join(ROOT, "research", "decks", self.t, "project")
        os.makedirs(os.path.join(out, "slides"), exist_ok=True)
        for f in os.listdir(os.path.join(out, "slides")):
            os.remove(os.path.join(out, "slides", f))
        for sid, h in self.slides:
            with open(os.path.join(out, "slides", f"{sid}.html"), "w") as f:
                f.write(h)
        with open(os.path.join(out, "deck.css"), "w") as f:
            f.write(CSS.strip() + "\n")
        order = [s for s, _ in self.slides]
        deck = {"v": 5, "createdOnFiles": {"v": 1, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                "lists": "css", "format": {"v": 1, "shared": ["project/deck.css"]},
                "title": f"{self.name} ({self.t}) – Initiation", "cover": "cover", "order": order,
                "sections": {"s1": {"description": "Summary", "start": "cover"},
                             "s2": {"description": "Business, industry and competition", "start": "business"},
                             "s3": {"description": "Investment theses", "start": "thesis1"},
                             "s4": {"description": "Valuation", "start": "comps"},
                             "s5": {"description": "Risks, screen and appendix", "start": "risks"}},
                "faces": {"inter": {"family": "Inter", "href": "https://fonts.googleapis.com/css2?family=Inter:wght@400;600"}},
                "designSystems": []}
        with open(os.path.join(out, "deck.json"), "w") as f:
            json.dump(deck, f, indent=1, ensure_ascii=False)
        return out


def preview_html(t):
    """One local HTML page with every slide, for a quick screenshot check."""
    out = os.path.join(ROOT, "research", "decks", t, "project")
    deck = json.load(open(os.path.join(out, "deck.json")))
    css = open(os.path.join(out, "deck.css")).read()
    assets = json.load(open(os.path.join(ROOT, "research", "packs", t, "assets.json")))
    local = json.load(open(os.path.join(ROOT, "research", "packs", t, "assets_local.json")))
    parts = []
    for sid in deck["order"]:
        h = open(os.path.join(out, "slides", f"{sid}.html")).read()
        for k, u in assets.items():
            h = h.replace(f'src="{u}"', f'src="file://{local[k]}"')
        h = h.replace("<aside>", "<aside hidden>")
        parts.append(h)
    page = ("<html><head><link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=Inter:wght@400;600'>"
            "<style>body{margin:0;background:#888} section{width:1920px;height:1080px;box-sizing:border-box;position:relative;overflow:hidden;margin-bottom:20px}"
            "h1,h2,h3,p,ul{margin:0} " + css + "</style></head><body>" + "\n".join(parts) + "</body></html>")
    path = os.path.join(ROOT, "research", "decks", t, "preview.html")
    open(path, "w").write(page)
    return path


if __name__ == "__main__":
    for t in sys.argv[1:]:
        print(Deck(t).build())
