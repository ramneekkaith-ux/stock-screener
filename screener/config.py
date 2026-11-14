"""All tunable settings for the screener live here.

Change a number, push, and the next daily run uses it.
"""

# ---------------------------------------------------------------- universe
MARKETS = {
    # Yahoo exchange codes. US: Nasdaq (NMS/NGM/NCM), NYSE (NYQ), NYSE American (ASE).
    "US": {"exchanges": ["NMS", "NGM", "NCM", "NYQ", "ASE"]},
    # UK: London Stock Exchange (Main Market + AIM both report as LSE on Yahoo).
    "UK": {"exchanges": ["LSE"]},
}

MIN_MARKET_CAP_USD = 100e6
MAX_MARKET_CAP_USD = 2e9
MIN_AVG_DAILY_VALUE_USD = 50e3      # 3-month average daily traded value
MIN_YEARS_LISTED = 3

# Whole sectors kept. Financial Services and Real Estate are mostly excluded
# (banks, insurers, REITs, investment trusts, SPACs) because FCF / margins / ROIC
# don't mean the same thing for them; the industries below are let back in.
SECTORS_KEPT = [
    "Basic Materials", "Communication Services", "Consumer Cyclical",
    "Consumer Defensive", "Energy", "Healthcare", "Industrials",
    "Technology", "Utilities",
]
EXTRA_INDUSTRIES_KEPT = [
    "Capital Markets", "Financial Data & Stock Exchanges",
    "Insurance Brokers", "Real Estate Services",
]
EXCLUDED_INDUSTRIES = []            # e.g. ["Biotechnology", "Gold"] to drop more

# ---------------------------------------------------------------- hard exclusions
# Only clear rubbish is excluded outright. Missing data never excludes.
HARD = {
    "min_revenue_usd": 10e6,             # TTM revenue
    "max_negative_ocf_years": 2,         # of the last 4 years; 3+ negative = out
    "min_altman_z2": 1.1,                # Altman Z'' distress zone
    "max_share_growth": 0.15,            # 15%/yr average dilution
    "max_net_debt_ebitda": 4.0,
}
MIN_YEARS_OF_DATA = 2                    # annual statements needed to be scored

# ---------------------------------------------------------------- scoring
PILLAR_WEIGHTS = {
    "growth": 0.30,
    "cashflow": 0.30,
    "quality": 0.25,
    "management": 0.15,
}
PASS_SCORE = 55
WATCH_SCORE = 45
PILLAR_FLOOR = 2.0                       # any pillar below this can't be "Pass"
LOW_COVERAGE = 0.70                      # flag if <70% of metrics available
MISSING_METRIC_SCORE = 5.0               # neutral

# ---------------------------------------------------------------- valuation (display only)
DCF_DISCOUNT_RATE = 0.10
DCF_TERMINAL_GROWTH = 0.025
DCF_YEARS = 10
CHEAP_VS_SECTOR = 0.75                   # EV/EBIT below 0.75x sector median = cheap
RICH_VS_SECTOR = 1.33

# ---------------------------------------------------------------- fetching
STATEMENT_REFRESH_DAYS = 7               # refresh a company's statements at least weekly
FETCH_WORKERS = 2
FETCH_DELAY_SECONDS = 1.0                # per worker, between companies (be polite to Yahoo)
RATE_LIMIT_PAUSE_SECONDS = 240           # all workers pause this long when Yahoo says "too many"
MAX_RATE_LIMITS = 40                     # give up for the day after this many
MAX_FETCH_MINUTES = 200                  # stop fetching and score what we have after this
