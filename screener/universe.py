"""Build the daily universe straight from Yahoo's own equity screener.

One paged query per market returns every listed stock in the kept sectors with
price, market cap, volume and listing date, so no separate ticker files are needed.
"""
import logging
import time

import yfinance as yf
from yfinance import EquityQuery as Q

from . import config
from .fx import FX

log = logging.getLogger(__name__)

PAGE = 250


def _sector_filter():
    return Q("or", [
        Q("is-in", ["sector", *config.SECTORS_KEPT]),
        Q("is-in", ["industry", *config.EXTRA_INDUSTRIES_KEPT]),
    ])


def _query(market):
    parts = [Q("is-in", ["exchange", *config.MARKETS[market]["exchanges"]]), _sector_filter()]
    if market == "US":
        # Yahoo's market-cap field is USD for US listings; leave a buffer, we re-check later.
        parts.append(Q("btwn", ["intradaymarketcap",
                                config.MIN_MARKET_CAP_USD * 0.8,
                                config.MAX_MARKET_CAP_USD * 1.2]))
    # UK: no cap filter in the query (Yahoo's unit for LSE caps is unreliable);
    # we compute it ourselves from price x shares below.
    return Q("and", parts)


def _page_through(query, label):
    quotes, offset, total = [], 0, None
    while True:
        for attempt in range(4):
            try:
                resp = yf.screen(query, offset=offset, size=PAGE, sortField="ticker", sortAsc=True)
                break
            except Exception as e:  # rate limit / transient
                wait = 20 * (attempt + 1)
                log.warning("%s screener page %s failed (%s); retry in %ss", label, offset, e, wait)
                time.sleep(wait)
        else:
            raise RuntimeError(f"Yahoo screener failed for {label}")
        batch = resp.get("quotes", [])
        total = resp.get("total", total)
        quotes.extend(batch)
        offset += PAGE
        if len(batch) < PAGE or (total is not None and offset >= total):
            break
        time.sleep(1)
    log.info("%s: %d listings from Yahoo screener (total reported %s)", label, len(quotes), total)
    return quotes


def market_cap_usd(q, fx: FX):
    """Market cap in USD, computed from price x shares where possible."""
    price, shares = q.get("regularMarketPrice"), q.get("sharesOutstanding")
    cur = q.get("currency") or "USD"
    r = fx.rate(cur)
    if not r:
        return None
    if price and shares:
        return price * shares * r
    mc = q.get("marketCap")
    if mc is None:
        return None
    # Yahoo reports LSE market caps in GBP even though prices are in pence.
    if cur == "GBp":
        return mc * fx.rate("GBP")
    return mc * r


def build(fx: FX, now_ms=None):
    now_ms = now_ms or time.time() * 1000
    universe, rejected = {}, {"market_cap": 0, "liquidity": 0, "too_new": 0, "not_equity": 0,
                              "industry": 0, "foreign_line": 0}
    for market in config.MARKETS:
        for q in _page_through(_query(market), market):
            sym = q.get("symbol")
            if not sym or q.get("quoteType", "EQUITY") != "EQUITY":
                rejected["not_equity"] += 1
                continue
            # LSE "0XXX.L" codes are overseas companies on the International Order Book.
            if market == "UK" and sym.startswith("0"):
                rejected["foreign_line"] += 1
                continue
            if q.get("industry") in config.EXCLUDED_INDUSTRIES:
                rejected["industry"] += 1
                continue
            mcap = market_cap_usd(q, fx)
            if mcap is None or not (config.MIN_MARKET_CAP_USD <= mcap <= config.MAX_MARKET_CAP_USD):
                rejected["market_cap"] += 1
                continue
            price_usd = (q.get("regularMarketPrice") or 0) * (fx.rate(q.get("currency") or "USD") or 0)
            adv = (q.get("averageDailyVolume3Month") or 0) * price_usd
            if adv < config.MIN_AVG_DAILY_VALUE_USD:
                rejected["liquidity"] += 1
                continue
            first = q.get("firstTradeDateMilliseconds")
            if first and (now_ms - first) / (365.25 * 86400e3) < config.MIN_YEARS_LISTED:
                rejected["too_new"] += 1
                continue
            universe[sym] = {
                "symbol": sym,
                "name": q.get("longName") or q.get("shortName") or sym,
                "market": market,
                "exchange": q.get("fullExchangeName") or q.get("exchange"),
                "currency": q.get("currency"),
                "financial_currency": q.get("financialCurrency"),
                "price": q.get("regularMarketPrice"),
                "market_cap_usd": mcap,
                "avg_daily_value_usd": adv,
                "reported_market_cap": q.get("marketCap"),
            }
    log.info("Universe: %d stocks kept; rejected %s", len(universe), rejected)
    return universe, rejected
