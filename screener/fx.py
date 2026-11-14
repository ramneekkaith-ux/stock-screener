"""Currency conversion to USD, including Yahoo's minor-unit quotes (GBp = pence)."""
import logging

import yfinance as yf

log = logging.getLogger(__name__)

MINOR_UNITS = {"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ZAc": ("ZAR", 100), "ILA": ("ILS", 100)}

# Used only if Yahoo's FX quote can't be fetched.
FALLBACK = {"USD": 1.0, "GBP": 1.27, "EUR": 1.08, "CAD": 0.72, "AUD": 0.65, "CHF": 1.12,
            "SEK": 0.094, "NOK": 0.092, "DKK": 0.145, "JPY": 0.0066, "ZAR": 0.055,
            "ILS": 0.27, "HKD": 0.128, "CNY": 0.138, "INR": 0.012, "SGD": 0.74}


class FX:
    def __init__(self):
        self._cache = {"USD": 1.0}

    def _major(self, cur):
        if cur in self._cache:
            return self._cache[cur]
        rate = None
        try:
            rate = yf.Ticker(f"{cur}USD=X").fast_info["last_price"]
        except Exception as e:
            log.warning("FX %s fetch failed: %s", cur, e)
        if not rate or rate != rate:
            rate = FALLBACK.get(cur)
            log.warning("FX %s using fallback %s", cur, rate)
        self._cache[cur] = rate
        return rate

    def rate(self, cur):
        """USD per 1 unit of `cur`. Unknown currency -> None-safe 0."""
        if not cur:
            return 1.0
        if cur in MINOR_UNITS:
            major, div = MINOR_UNITS[cur]
            r = self._major(major)
            return r / div if r else 0.0
        return self._major(cur) or 0.0

    def snapshot(self):
        return dict(self._cache)
