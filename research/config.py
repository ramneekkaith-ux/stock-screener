"""Settings for the research layer (candidate selection, packs, DCF, comps)."""

# ---------------------------------------------------------------- candidate selection
MIN_SCORE = 75
MIN_COVERAGE = 0.85
QUALITY_WEIGHT = 0.70            # rest is value
CANDIDATES_PER_RUN = 6           # packs built per run; Claude picks the best after a news check
MAX_PER_SECTOR = 1
RECOVER_AFTER_DAYS = 180         # don't re-cover a name within this window
# Research covers developed-market companies only: the DCF uses a US/UK risk-free rate and
# has no country-risk or currency-inflation adjustment for emerging-market cash flows.
RESEARCH_COUNTRIES = {"United States", "United Kingdom", "Ireland", "Jersey", "Guernsey", "Isle of Man",
                      "Canada", "Germany", "France", "Netherlands", "Switzerland", "Sweden", "Norway",
                      "Denmark", "Finland", "Belgium", "Luxembourg", "Austria", "Spain", "Italy",
                      "Australia", "New Zealand", "Israel", "Bermuda"}

# ---------------------------------------------------------------- WACC / DCF
EQUITY_RISK_PREMIUM = 0.050
SIZE_PREMIUM = 0.010             # small-cap premium added to cost of equity (disclosed)
BETA_FLOOR, BETA_CAP = 0.6, 2.0
TERMINAL_GROWTH = 0.025
FADE_BY_YEAR = 7                 # growth fades from year 2 to terminal by this year
FORECAST_YEARS = 10
FALLBACK_RISK_FREE = {"USD": 0.043, "GBP": 0.045}
DEFAULT_TAX = {"US": 0.25, "UK": 0.25}
MID_YEAR = True

# ---------------------------------------------------------------- rating bands (upside to target)
BUY_ABOVE = 0.15
SELL_BELOW = -0.10

# ---------------------------------------------------------------- peers
MAX_PEERS = 8
