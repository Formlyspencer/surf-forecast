"""Folly Beach surf-window forecast — tunable knobs.

Edit values here to recalibrate. Everything else reads from this module.
"""

# --- Location -----------------------------------------------------------------
SPOT_NAME = "Folly Beach, SC"
LAT = 32.655
LON = -79.94
TZ = "America/New_York"

# Tide station: Charleston (Customhouse Wharf) is the nearest harmonic station.
# No oceanfront subordinate exists for Folly; surfers use Charleston directly.
TIDE_STATION = "8665530"

# Cross-check buoy: NDBC 41004 (Edisto), ~40nm SE of Folly. Used for "current
# conditions" sanity panel only — not for forecast scoring.
NDBC_BUOY = "41004"

# Shore-normal heading for Folly Beach (degrees, FROM which direction the
# beach faces). ~135° = SE-facing. Wind angles are scored relative to this.
SHORE_NORMAL_DEG = 135

# --- Forecast horizon ---------------------------------------------------------
FORECAST_DAYS = 7
MIN_WINDOW_HOURS = 2

# --- Score thresholds (color buckets) -----------------------------------------
# A window's color = bucket(max hourly score in the window).
# Anything below ORANGE is hidden entirely.
BRIGHT_GREEN = 0.65
LIGHT_GREEN = 0.45
YELLOW = 0.30
ORANGE = 0.20

# --- Wave energy calibration --------------------------------------------------
# Energy proxy = H² × T (height in ft, period in s).
# User reference points:
#   2 ft @ 5 s  → energy 20  → score 0.00 (never go out)
#   3 ft @ 9 s  → energy 81  → score ~0.62 (decent)
#   4 ft @ 11 s → energy 176 → score 1.00 (stellar)
WAVE_ENERGY_FLOOR = 20      # below this, score = 0
WAVE_ENERGY_CEIL = 176      # at this, score = 1.0
WAVE_CURVE_EXPONENT = 0.5   # sqrt curve fits the three calibration points

# --- Swell direction ----------------------------------------------------------
# SE (135°) is best. Pure E (90°) and pure S (180°) are the boundary edges.
# Outside the E–S arc, score is 0 (skip the window).
SWELL_DIR_BEST = 135
SWELL_DIR_LO = 90    # pure E
SWELL_DIR_HI = 180   # pure S
SWELL_DIR_EDGE_FLOOR = 0.85  # score at the edges of the acceptable arc

# --- Wind speed ramp (knots → score) ------------------------------------------
WIND_SPEED_RAMP = [
    (10, 1.00),
    (15, 0.80),
    (20, 0.50),
    (30, 0.20),
]
WIND_SPEED_FLOOR = 0.10  # for anything > last ramp point

# --- Tide scoring -------------------------------------------------------------
TIDE_LOW_NOGO_HOURS = 1.5  # within this many hours of low → score 0
