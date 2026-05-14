"""Score each forecast hour and group consecutive surfable hours into windows.

Final hourly score = wave × swell_dir × wind_dir × wind_speed × tide
Anything multiplicative — a zero in any factor kills the window.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from dataclasses import dataclass

import config


# ---------------------------------------------------------------------------
# Per-factor scoring
# ---------------------------------------------------------------------------

def wave_score(height_ft: float | None, period_s: float | None) -> float:
    """H²·T energy proxy mapped via sqrt curve through user's calibration points."""
    if height_ft is None or period_s is None or height_ft <= 0 or period_s <= 0:
        return 0.0
    energy = (height_ft ** 2) * period_s
    if energy <= config.WAVE_ENERGY_FLOOR:
        return 0.0
    span = config.WAVE_ENERGY_CEIL - config.WAVE_ENERGY_FLOOR
    norm = (energy - config.WAVE_ENERGY_FLOOR) / span
    return min(1.0, norm ** config.WAVE_CURVE_EXPONENT)


def swell_dir_score(direction_deg: float | None) -> float:
    """1.0 at SE (135°); falls to SWELL_DIR_EDGE_FLOOR at pure E or pure S; 0 outside."""
    if direction_deg is None:
        return 0.0
    d = direction_deg % 360
    if d < config.SWELL_DIR_LO or d > config.SWELL_DIR_HI:
        return 0.0
    span = max(config.SWELL_DIR_BEST - config.SWELL_DIR_LO,
               config.SWELL_DIR_HI - config.SWELL_DIR_BEST)
    offset = abs(d - config.SWELL_DIR_BEST)
    drop = (1.0 - config.SWELL_DIR_EDGE_FLOOR) * (offset / span)
    return max(0.0, 1.0 - drop)


def wind_dir_score(direction_deg: float | None) -> float:
    """Direction wind is FROM. Folly faces ~135°.
       Pure NW (315°) → 1.0  (full offshore, best)
       Pure W or N    → 0.71 (mostly offshore)
       NE / SW (45/225) → 0  (crossshore, worst)
       Pure E or S    → 0.35 (mostly onshore)
       Pure SE (135°) → 0.50 (full onshore, OK)
    """
    if direction_deg is None:
        return 0.0
    cos_factor = math.cos(math.radians(direction_deg - config.SHORE_NORMAL_DEG))
    if cos_factor < 0:                  # offshore half
        return -cos_factor              # 0..1, peaks at NW
    return 0.5 * cos_factor             # onshore half, capped at 0.5


def wind_speed_score(speed_kt: float | None) -> float:
    if speed_kt is None or speed_kt < 0:
        return 0.0
    prev_kt, prev_score = 0.0, 1.0
    for kt, score in config.WIND_SPEED_RAMP:
        if speed_kt <= kt:
            if kt == prev_kt:
                return score
            frac = (speed_kt - prev_kt) / (kt - prev_kt)
            return prev_score + frac * (score - prev_score)
        prev_kt, prev_score = kt, score
    return config.WIND_SPEED_FLOOR


def tide_score(t: datetime, extremes: list[dict]) -> float:
    """Score tide phase at time `t` based on hours-from-nearest-extreme.

    Calibrated to user's verbal model:
      - within 1.5h of low      → 0.0  (no-go)
      - within 1h of high       → 1.0  (peak)
      - rising, last 2h to high → 0.9
      - rising, 2-3h to high    → 0.7
      - rising, 3-4.5h to high  → 0.4
      - falling, 1-2h post-high → 0.9
      - falling, 2-3h post-high → 0.7  (user's "3h cutoff for near high")
      - falling, 3-4.5h post-high → 0.4 (mid-fall, "ok but weighted bad")
      - everything else         → 0.2  (just outside no-go band)
    """
    nearest_high = _nearest_extreme(t, extremes, "H")
    nearest_low = _nearest_extreme(t, extremes, "L")
    if nearest_high is None or nearest_low is None:
        return 0.0

    hrs_to_high = abs((nearest_high["time"] - t).total_seconds()) / 3600
    hrs_to_low = abs((nearest_low["time"] - t).total_seconds()) / 3600

    if hrs_to_low < config.TIDE_LOW_NOGO_HOURS:
        return 0.0
    if hrs_to_high < 1.0:
        return 1.0

    # Determine rising vs falling: closer surrounding extremes
    prev_extreme = _previous_extreme(t, extremes)
    rising = prev_extreme is not None and prev_extreme["type"] == "L"

    if rising:
        if hrs_to_high < 2.0: return 0.9
        if hrs_to_high < 3.0: return 0.7
        if hrs_to_high < 4.5: return 0.4
        return 0.2
    else:  # falling
        hrs_since_high = (t - prev_extreme["time"]).total_seconds() / 3600 if prev_extreme else 99
        if hrs_since_high < 2.0: return 0.9
        if hrs_since_high < 3.0: return 0.7
        if hrs_since_high < 4.5: return 0.4
        return 0.2


def _nearest_extreme(t: datetime, extremes: list[dict], type_filter: str) -> dict | None:
    matching = [e for e in extremes if e["type"] == type_filter]
    if not matching:
        return None
    return min(matching, key=lambda e: abs((e["time"] - t).total_seconds()))


def _previous_extreme(t: datetime, extremes: list[dict]) -> dict | None:
    past = [e for e in extremes if e["time"] <= t]
    if not past:
        return None
    return max(past, key=lambda e: e["time"])


# ---------------------------------------------------------------------------
# Hour assembly + windowing
# ---------------------------------------------------------------------------

@dataclass
class Hour:
    t: datetime
    swell_h_ft: float | None
    swell_dir: float | None
    swell_T: float | None
    wave_h_ft: float | None  # combined seas (wind+swell)
    wave_dir: float | None
    wave_T: float | None
    wind_kt: float | None
    wind_dir: float | None
    wind_gust_kt: float | None
    tide_phase: str           # "rising", "falling", "low-nogo", "high-peak", "unknown"
    score: float
    factors: dict             # per-factor scores for debugging/display


@dataclass
class Window:
    start: datetime
    end: datetime
    peak_hour: Hour
    avg_score: float
    color: str                # bucket name


def color_bucket(score: float) -> str | None:
    if score >= config.BRIGHT_GREEN: return "bright-green"
    if score >= config.LIGHT_GREEN:  return "light-green"
    if score >= config.YELLOW:       return "yellow"
    if score >= config.ORANGE:       return "orange"
    return None  # below threshold → hide (use find_fallback_windows for red)


def _alignment(h: Hour) -> float:
    """Quality of non-wave factors only (swell-dir × wind-dir × wind-speed × tide).
    Used to rank fallback windows when wave score is the limiter.
    """
    return (h.factors["swell_dir"] * h.factors["wind_dir"]
            * h.factors["wind_speed"] * h.factors["tide"])


def _fallback_quality(h: Hour) -> float:
    """Used to rank fallback hours/windows. Combines alignment with a soft
    wave proxy so a 2ft day ranks higher than a 0.5ft day even if everything
    else is the same.
    """
    wave_proxy = min(1.0, (h.wave_h_ft or 0) / 4.0)
    return _alignment(h) * wave_proxy


def build_hours(bundle: dict) -> list[Hour]:
    tz = ZoneInfo(config.TZ)
    marine_h = bundle["marine"]["hourly"]
    wind_h = bundle["wind"]["hourly"]
    extremes = bundle["tide_extremes"]

    # Marine and wind share the same time grid (Open-Meteo, same tz, same horizon)
    times = marine_h["time"]
    assert times == wind_h["time"], "marine/wind time grids diverged"

    # Build daylight window per date for fast lookup
    daylight = bundle["daylight"]["daily"]
    sunrise_by_date = {
        date_str: datetime.fromisoformat(s).replace(tzinfo=tz)
        for date_str, s in zip(daylight["time"], daylight["sunrise"])
    }
    sunset_by_date = {
        date_str: datetime.fromisoformat(s).replace(tzinfo=tz)
        for date_str, s in zip(daylight["time"], daylight["sunset"])
    }

    hours: list[Hour] = []
    for i, ts in enumerate(times):
        t = datetime.fromisoformat(ts).replace(tzinfo=tz)
        date_key = t.date().isoformat()
        sr = sunrise_by_date.get(date_key)
        ss = sunset_by_date.get(date_key)
        if sr and ss and not (sr <= t < ss):
            continue  # skip non-daylight hours entirely

        swell_h = marine_h["swell_wave_height"][i]
        swell_dir = marine_h["swell_wave_direction"][i]
        swell_T = marine_h["swell_wave_period"][i]
        wave_h = marine_h["wave_height"][i]
        wave_dir = marine_h["wave_direction"][i]
        wave_T = marine_h["wave_period"][i]
        wind_kt = wind_h["wind_speed_10m"][i]
        wind_dir = wind_h["wind_direction_10m"][i]
        wind_gust = wind_h["wind_gusts_10m"][i]

        # Score wave energy off the COMBINED seas (more representative of what
        # surfers actually ride at Folly — wind swell often dominates) but use
        # SWELL direction for the direction match (where the energy is *coming*
        # from that matters for break orientation).
        ws = wave_score(wave_h, wave_T)
        sds = swell_dir_score(swell_dir)
        wds = wind_dir_score(wind_dir)
        wss = wind_speed_score(wind_kt)
        ts_score = tide_score(t, extremes)

        score = ws * sds * wds * wss * ts_score

        prev = _previous_extreme(t, extremes)
        nearest_low = _nearest_extreme(t, extremes, "L")
        nearest_high = _nearest_extreme(t, extremes, "H")
        hrs_to_low = abs((nearest_low["time"] - t).total_seconds())/3600 if nearest_low else 99
        hrs_to_high = abs((nearest_high["time"] - t).total_seconds())/3600 if nearest_high else 99
        if hrs_to_low < config.TIDE_LOW_NOGO_HOURS:
            phase = "low-nogo"
        elif hrs_to_high < 1.0:
            phase = "high-peak"
        elif prev and prev["type"] == "L":
            phase = "rising"
        elif prev and prev["type"] == "H":
            phase = "falling"
        else:
            phase = "unknown"

        hours.append(Hour(
            t=t,
            swell_h_ft=swell_h, swell_dir=swell_dir, swell_T=swell_T,
            wave_h_ft=wave_h, wave_dir=wave_dir, wave_T=wave_T,
            wind_kt=wind_kt, wind_dir=wind_dir, wind_gust_kt=wind_gust,
            tide_phase=phase,
            score=score,
            factors={
                "wave": round(ws, 2),
                "swell_dir": round(sds, 2),
                "wind_dir": round(wds, 2),
                "wind_speed": round(wss, 2),
                "tide": round(ts_score, 2),
            },
        ))
    return hours


def find_windows(hours: list[Hour]) -> list[Window]:
    """Group consecutive surfable hours into named windows.

    A window:
      - all hours score ≥ ORANGE threshold
      - all hours are daylight (already filtered)
      - all hours are consecutive (gap ≤ 1h)
      - duration ≥ MIN_WINDOW_HOURS
    Window color = bucket(peak hour score).
    """
    windows: list[Window] = []
    run: list[Hour] = []

    def flush():
        if not run:
            return
        # require consecutive hours within run AND duration ≥ minimum
        duration_h = (run[-1].t - run[0].t).total_seconds() / 3600 + 1
        if duration_h >= config.MIN_WINDOW_HOURS:
            peak = max(run, key=lambda h: h.score)
            avg = sum(h.score for h in run) / len(run)
            color = color_bucket(peak.score)
            if color:
                windows.append(Window(
                    start=run[0].t,
                    end=run[-1].t + timedelta(hours=1),
                    peak_hour=peak,
                    avg_score=avg,
                    color=color,
                ))

    for h in hours:
        if h.score < config.ORANGE:
            flush()
            run = []
            continue
        if run and (h.t - run[-1].t) > timedelta(hours=1):
            flush()
            run = [h]
        else:
            run.append(h)
    flush()
    return windows


def find_fallback_windows(hours: list[Hour], n: int | None = None) -> list[Window]:
    """Surface the 'least-bad' windows when no real windows clear orange.

    Groups consecutive hours where non-wave factors don't zero out (so swell
    direction is in the acceptable arc, tide isn't no-go low, wind isn't pure
    crossshore). Ranks resulting windows by alignment × soft-wave proxy and
    returns the top N (default config.RED_FALLBACK_COUNT). All returned
    windows are tagged "red".

    Use only when find_windows() returns empty.
    """
    if n is None:
        n = config.RED_FALLBACK_COUNT

    runs: list[list[Hour]] = []
    run: list[Hour] = []

    def flush():
        if not run:
            return
        duration_h = (run[-1].t - run[0].t).total_seconds() / 3600 + 1
        if duration_h >= config.MIN_WINDOW_HOURS:
            runs.append(list(run))

    for h in hours:
        # Require at least minimal alignment — skip hours where any non-wave
        # factor is zero (crossshore wind, low-tide nogo, swell out of arc)
        if _alignment(h) < 0.05:
            flush()
            run = []
            continue
        if run and (h.t - run[-1].t) > timedelta(hours=1):
            flush()
            run = [h]
        else:
            run.append(h)
    flush()

    windows: list[Window] = []
    for r in runs:
        peak = max(r, key=_fallback_quality)
        avg = sum(h.score for h in r) / len(r)
        windows.append(Window(
            start=r[0].t,
            end=r[-1].t + timedelta(hours=1),
            peak_hour=peak,
            avg_score=avg,
            color="red",
        ))

    windows.sort(key=lambda w: _fallback_quality(w.peak_hour), reverse=True)
    return windows[:n]


if __name__ == "__main__":
    import fetch
    bundle = fetch.fetch_all()
    hours = build_hours(bundle)
    windows = find_windows(hours)
    print(f"Built {len(hours)} daylight hours, {len(windows)} surf windows.")
    for w in windows:
        h = w.peak_hour
        print(f"  {w.start:%a %b %d %I%p} – {w.end:%I%p}  [{w.color}]  "
              f"peak {h.score:.2f} | {h.wave_h_ft:.1f}ft@{h.wave_T:.0f}s "
              f"swell {h.swell_dir:.0f}° | wind {h.wind_kt:.0f}kt@{h.wind_dir:.0f}° | "
              f"{h.tide_phase}")
