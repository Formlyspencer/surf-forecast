"""Fetch raw forecast data from public APIs.

All three sources are free and require no API key:
  - Open-Meteo Marine API     → swell height/direction/period
  - Open-Meteo Forecast API   → 10m wind speed/direction/gusts
  - NOAA CO-OPS               → tide hi/lo + hourly height predictions
"""
from __future__ import annotations

import urllib.parse
import urllib.request
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config

USER_AGENT = "folly-surf-forecast/1.0 (spencer@formly.ai)"


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_marine() -> dict:
    """Hourly swell forecast for FORECAST_DAYS days.

    Uses NCEP GFS-Wave (0.25°) — the same model NOAA and Surfline reference,
    so the wave height + period shown here align with the numbers Spencer
    sees on NOAA AMZ360 and Surfline. (Open-Meteo's default ECMWF model
    reports mean period, which runs ~2s shorter than the peak period those
    other sources report.)
    """
    params = {
        "latitude": config.LAT,
        "longitude": config.LON,
        "hourly": ",".join([
            "wave_height", "wave_direction", "wave_period",
            "swell_wave_height", "swell_wave_direction", "swell_wave_period",
        ]),
        "models": "ncep_gfswave025",
        "length_unit": "imperial",
        "timezone": config.TZ,
        "forecast_days": config.FORECAST_DAYS,
    }
    url = "https://marine-api.open-meteo.com/v1/marine?" + urllib.parse.urlencode(params)
    return _get_json(url)


def fetch_wind() -> dict:
    """Hourly 10m wind for FORECAST_DAYS days."""
    params = {
        "latitude": config.LAT,
        "longitude": config.LON,
        "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "wind_speed_unit": "kn",
        "timezone": config.TZ,
        "forecast_days": config.FORECAST_DAYS,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    return _get_json(url)


def fetch_daylight() -> dict:
    """Sunrise/sunset per day."""
    params = {
        "latitude": config.LAT,
        "longitude": config.LON,
        "daily": "sunrise,sunset",
        "timezone": config.TZ,
        "forecast_days": config.FORECAST_DAYS,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    return _get_json(url)


def fetch_tide_extremes() -> list[dict]:
    """Predicted high/low tide events for the forecast window.

    Returns: list of {"time": datetime (tz-aware), "type": "H"|"L", "height_ft": float}
    """
    tz = ZoneInfo(config.TZ)
    today = datetime.now(tz).date()
    end = today + timedelta(days=config.FORECAST_DAYS + 1)  # +1 buffer for cycle math

    params = {
        "product": "predictions",
        "application": "folly_surf_forecast",
        "begin_date": today.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
        "datum": "MLLW",
        "station": config.TIDE_STATION,
        "time_zone": "lst_ldt",
        "units": "english",
        "interval": "hilo",
        "format": "json",
    }
    url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?" + urllib.parse.urlencode(params)
    data = _get_json(url)

    out = []
    for p in data.get("predictions", []):
        # CO-OPS returns naive local time strings, e.g. "2026-05-05 10:56"
        naive = datetime.strptime(p["t"], "%Y-%m-%d %H:%M")
        out.append({
            "time": naive.replace(tzinfo=tz),
            "type": p["type"],  # "H" or "L"
            "height_ft": float(p["v"]),
        })
    return out


def fetch_buoy_latest() -> dict | None:
    """Latest observation from NDBC buoy 41004 for the 'current conditions' panel.

    Returns dict with keys: time, wvht_ft, dpd_s, mwd_deg, wspd_kt, wdir_deg
    or None if the buoy is offline / parse fails.
    """
    url = f"https://www.ndbc.noaa.gov/data/realtime2/{config.NDBC_BUOY}.txt"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    if not lines:
        return None
    parts = lines[0].split()
    # NDBC realtime2 columns:
    # YY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS PTDY TIDE
    if len(parts) < 12:
        return None

    def f(s):
        try:
            v = float(s)
            return None if v == 99.0 or v == 999.0 or v == 9999.0 else v
        except ValueError:
            return None

    yy, mo, dd, hh, mm = (int(parts[i]) for i in range(5))
    obs_time = datetime(yy, mo, dd, hh, mm, tzinfo=ZoneInfo("UTC"))

    wdir = f(parts[5])
    wspd_ms = f(parts[6])
    wvht_m = f(parts[8])
    dpd = f(parts[9])
    mwd = f(parts[11])

    return {
        "time": obs_time.astimezone(ZoneInfo(config.TZ)),
        "wvht_ft": wvht_m * 3.28084 if wvht_m is not None else None,
        "dpd_s": dpd,
        "mwd_deg": mwd,
        "wspd_kt": wspd_ms * 1.94384 if wspd_ms is not None else None,
        "wdir_deg": wdir,
    }


def fetch_all() -> dict:
    """Fetch everything and return a single bundle."""
    return {
        "marine": fetch_marine(),
        "wind": fetch_wind(),
        "daylight": fetch_daylight(),
        "tide_extremes": fetch_tide_extremes(),
        "buoy": fetch_buoy_latest(),
        "fetched_at": datetime.now(ZoneInfo(config.TZ)),
    }


if __name__ == "__main__":
    bundle = fetch_all()
    print(f"marine hourly count: {len(bundle['marine']['hourly']['time'])}")
    print(f"wind hourly count:   {len(bundle['wind']['hourly']['time'])}")
    print(f"tide extremes:       {len(bundle['tide_extremes'])}")
    print(f"buoy:                {bundle['buoy']}")
