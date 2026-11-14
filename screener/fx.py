"""Currency conversion to USD, including Yahoo's minor-unit quotes (GBp = pence).

All rates are fetched in one batch at the start of the run, before company data,
so a later Yahoo rate-limit can't leave us without them.
"""
import logging

import yfinance as yf

log = logging.getLogger(__name__)

MINOR_UNITS = {"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ZAc": ("ZAR", 100), "ILA": ("ILS", 100)}

PREFETCH = ["GBP", "EUR", "CAD", "AUD", "CHF", "SEK", "NOK", "DKK", "JPY", "ZAR", "ILS", "HKD",
            "CNY", "INR", "SGD", "NZD", "BRL", "MXN", "ARS", "PEN", "CLP", "COP", "KRW", "TWD",
            "TRY", "EGP", "PLN", "CZK", "HUF", "RUB", "IDR", "MYR", "THB", "PHP", "NGN", "KZT",
            "AED", "SAR", "ISK", "UAH", "VND", "PKR", "KES"]

# Used only if Yahoo's FX quote can't be fetched.
FALLBACK = {"GBP": 1.27, "EUR": 1.08, "CAD": 0.72, "AUD": 0.65, "CHF": 1.12}


class FX:
    def __init__(self, prefetch=True):
        self._cache = {"USD": 1.0}
        if prefetch:
            self._prefetch()

    def _prefetch(self):
        tickers = [f"{c}USD=X" for c in PREFETCH]
        try:
            df = yf.download(tickers, period="10d", progress=False, auto_adjust=False,
                             threads=False)["Close"]
            for c, t in zip(PREFETCH, tickers):
                if t in df:
                    s = df[t].dropna()
                    if len(s):
                        self._cache[c] = float(s.iloc[-1])
        except Exception as e:
            log.warning("FX batch download failed: %s", e)
        log.info("FX rates loaded for %d currencies", len(self._cache))

    def _major(self, cur):
        if cur in self._cache:
            return self._cache[cur]
        rate = None
        try:
            rate = float(yf.Ticker(f"{cur}USD=X").fast_info["last_price"])
        except Exception as e:
            log.warning("FX %s fetch failed: %s", cur, e)
        if not rate or rate != rate:
            rate = FALLBACK.get(cur)
            log.warning("FX %s using fallback %s", cur, rate)
        self._cache[cur] = rate
        return rate

    def rate(self, cur):
        """USD per 1 unit of `cur`, or None if unknown."""
        if not cur:
            return 1.0
        if cur in MINOR_UNITS:
            major, div = MINOR_UNITS[cur]
            r = self._major(major)
            return r / div if r else None
        return self._major(cur)

    def snapshot(self):
        return dict(self._cache)
