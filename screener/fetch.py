"""Fetch and cache company fundamentals from Yahoo via yfinance.

Statements only change a few times a year, so each company is refreshed at most
weekly (or right after a new earnings date). The cache is a single gzipped JSON
file kept on the repo's `cache` branch between runs.
"""
import gzip
import json
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import yfinance as yf

from . import config

log = logging.getLogger(__name__)

INFO_KEYS = [
    "sector", "industry", "country", "website", "fullTimeEmployees", "longBusinessSummary",
    "heldPercentInsiders", "heldPercentInstitutions", "financialCurrency", "currency",
    "sharesOutstanding", "totalDebt", "totalCash", "ebitda", "earningsTimestamp",
    "mostRecentQuarter", "lastFiscalYearEnd", "firstTradeDateEpochUtc",
]


def _df_to_dict(df):
    if df is None or getattr(df, "empty", True):
        return {}
    out = {}
    for row in df.index:
        vals = {}
        for col in df.columns:
            v = df.at[row, col]
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if not math.isnan(v):
                vals[str(col)[:10]] = v
        if vals:
            out[str(row)] = vals
    return out


def fetch_one(symbol):
    t = yf.Ticker(symbol)
    info = t.get_info() or {}
    rec = {
        "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "info": {k: info.get(k) for k in INFO_KEYS if info.get(k) is not None},
        "annual": {
            "income": _df_to_dict(t.get_income_stmt(freq="yearly", pretty=True)),
            "balance": _df_to_dict(t.get_balance_sheet(freq="yearly", pretty=True)),
            "cashflow": _df_to_dict(t.get_cashflow(freq="yearly", pretty=True)),
        },
        "quarterly": {
            "income": _df_to_dict(t.get_income_stmt(freq="quarterly", pretty=True)),
            "cashflow": _df_to_dict(t.get_cashflow(freq="quarterly", pretty=True)),
        },
        "insider": {},
    }
    s = rec["info"].get("longBusinessSummary")
    if s and len(s) > 600:
        rec["info"]["longBusinessSummary"] = s[:600].rsplit(" ", 1)[0] + "…"
    try:
        ip = t.get_insider_purchases()
        if ip is not None and not ip.empty:
            label_col, shares_col = ip.columns[0], "Shares"
            for _, r in ip.iterrows():
                try:
                    val = float(r[shares_col])
                    if val == val:
                        rec["insider"][str(r[label_col])] = val
                except (TypeError, ValueError, KeyError):
                    pass
    except Exception:
        pass
    return rec


# ---------------------------------------------------------------- cache

def load_cache(path):
    if not os.path.exists(path):
        log.info("No cache at %s; starting fresh", path)
        return {}
    with gzip.open(path, "rt") as f:
        cache = json.load(f)
    log.info("Loaded cache with %d companies", len(cache))
    return cache


def save_cache(cache, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with gzip.open(path, "wt") as f:
        json.dump(cache, f, separators=(",", ":"))


def _age_days(rec, now):
    try:
        return (now - datetime.fromisoformat(rec["fetched"])).total_seconds() / 86400
    except Exception:
        return 1e9


def needs_refresh(rec, now):
    if not rec:
        return True
    if _age_days(rec, now) >= config.STATEMENT_REFRESH_DAYS:
        return True
    # A results date has passed since we last fetched -> new statements likely out.
    et = rec.get("info", {}).get("earningsTimestamp")
    if et:
        fetched = datetime.fromisoformat(rec["fetched"]).timestamp()
        if fetched < et + 86400 * 2 < now.timestamp():
            return True
    return False


def refresh(symbols, cache, cache_path):
    now = datetime.now(timezone.utc)
    todo = [s for s in symbols if needs_refresh(cache.get(s), now)]
    # Never-fetched first, then oldest.
    todo.sort(key=lambda s: -_age_days(cache.get(s) or {}, now))
    log.info("%d of %d companies need a refresh", len(todo), len(symbols))

    deadline = time.time() + config.MAX_FETCH_MINUTES * 60
    lock = threading.Lock()
    stop = threading.Event()
    pause = {"until": 0.0}
    stats = {"ok": 0, "failed": 0, "rate_limited": 0}

    def wait_turn():
        while time.time() < pause["until"] and not stop.is_set():
            time.sleep(5)
        time.sleep(config.FETCH_DELAY_SECONDS)

    def work(sym):
        for attempt in range(3):
            if stop.is_set() or time.time() > deadline:
                return
            wait_turn()
            try:
                rec = fetch_one(sym)
                with lock:
                    cache[sym] = rec
                    stats["ok"] += 1
                    if stats["ok"] % 200 == 0:
                        log.info("fetched %d / %d", stats["ok"], len(todo))
                        save_cache(cache, cache_path)   # checkpoint
                return
            except Exception as e:
                if "RateLimit" in type(e).__name__ or "Too Many Requests" in str(e):
                    with lock:
                        stats["rate_limited"] += 1
                        n = stats["rate_limited"]
                        if time.time() >= pause["until"]:
                            pause["until"] = time.time() + config.RATE_LIMIT_PAUSE_SECONDS
                            log.warning("Rate-limited by Yahoo (%d); pausing %ss", n,
                                        config.RATE_LIMIT_PAUSE_SECONDS)
                        if n > config.MAX_RATE_LIMITS:
                            log.error("Still rate-limited; stopping fetch for today")
                            stop.set()
                elif attempt == 2:
                    with lock:
                        stats["failed"] += 1
                    log.debug("%s failed: %s", sym, e)

    with ThreadPoolExecutor(max_workers=config.FETCH_WORKERS) as ex:
        list(as_completed([ex.submit(work, s) for s in todo]))

    skipped = len(todo) - stats["ok"] - stats["failed"]
    log.info("Fetch done: %s, %d deferred to next run", stats, max(skipped, 0))
    save_cache(cache, cache_path)
    return {**stats, "deferred": max(skipped, 0), "needed": len(todo)}
