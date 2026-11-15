"""Risk-free rates from FRED's public CSV endpoint (no API key needed)."""
import csv
import io
import logging
import urllib.request

from . import config

log = logging.getLogger(__name__)

SERIES = {
    "USD": ("DGS10", "US 10-year Treasury yield (FRED DGS10)"),
    "GBP": ("IRLTLT01GBM156N", "UK 10-year gilt yield (FRED IRLTLT01GBM156N, monthly)"),
}


def _fred_latest(series_id):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "stock-screener research"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = list(csv.reader(io.StringIO(r.read().decode())))
    for d, v in reversed(rows[1:]):
        try:
            return d, float(v) / 100
        except ValueError:
            continue
    raise ValueError("no data")


def risk_free(currency):
    """(rate, as_of, source) for the company's reporting currency; USD for anything else."""
    cur = "GBP" if currency in ("GBP", "GBp") else "USD"
    sid, label = SERIES[cur]
    try:
        d, v = _fred_latest(sid)
        return {"rate": v, "as_of": d, "source": label, "url": f"https://fred.stlouisfed.org/series/{sid}"}
    except Exception as e:
        log.warning("FRED %s failed (%s); using fallback", sid, e)
        return {"rate": config.FALLBACK_RISK_FREE[cur], "as_of": None,
                "source": f"Fallback assumption (FRED {sid} unavailable)", "url": None}
