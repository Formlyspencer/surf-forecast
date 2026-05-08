"""Render the static HTML page from scored windows."""
from __future__ import annotations

import html
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from score import Hour, Window


CSS = """
:root {
  --bg: #0e1116;
  --panel: #161b22;
  --text: #e6edf3;
  --muted: #8b949e;
  --border: #30363d;
  --bright-green: #2ea043;
  --light-green: #56d364;
  --yellow: #d29922;
  --orange: #db6d28;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 16px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  background: var(--bg); color: var(--text);
  max-width: 720px; margin-left: auto; margin-right: auto;
  -webkit-font-smoothing: antialiased;
}
h1 { font-size: 22px; margin: 4px 0 2px; }
h2 { font-size: 16px; margin: 24px 0 8px; color: var(--muted); font-weight: 600; }
.subtitle { color: var(--muted); font-size: 13px; margin-bottom: 16px; }
.now {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 10px; padding: 12px 14px; margin-bottom: 20px;
  font-size: 14px;
}
.now .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }
.day { margin-bottom: 18px; }
.day-header {
  font-size: 14px; font-weight: 600; color: var(--muted);
  border-bottom: 1px solid var(--border); padding-bottom: 4px; margin-bottom: 10px;
  display: flex; justify-content: space-between;
}
.tide-line { font-size: 11px; color: var(--muted); font-weight: 400; }
.window {
  background: var(--panel); border-left: 4px solid;
  border-radius: 8px; padding: 10px 12px; margin-bottom: 8px;
  display: grid; grid-template-columns: auto 1fr auto; gap: 12px;
  align-items: center;
}
.window.bright-green { border-left-color: var(--bright-green); }
.window.light-green  { border-left-color: var(--light-green); }
.window.yellow       { border-left-color: var(--yellow); }
.window.orange       { border-left-color: var(--orange); }
.win-time { font-weight: 600; font-size: 15px; min-width: 110px; }
.win-detail { font-size: 12px; color: var(--muted); line-height: 1.4; }
.win-score {
  font-variant-numeric: tabular-nums; font-weight: 700; font-size: 16px;
  padding: 4px 8px; border-radius: 6px; min-width: 44px; text-align: center;
}
.win-score.bright-green { background: var(--bright-green); color: white; }
.win-score.light-green  { background: var(--light-green); color: #0e1116; }
.win-score.yellow       { background: var(--yellow); color: #0e1116; }
.win-score.orange       { background: var(--orange); color: white; }
.empty {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 10px; padding: 20px; text-align: center; color: var(--muted);
}
.legend { font-size: 11px; color: var(--muted); margin-top: 24px; line-height: 1.6; }
.legend .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin: 0 4px 0 8px; vertical-align: middle; }
footer { font-size: 11px; color: var(--muted); margin-top: 32px; text-align: center; }
.factors { font-size: 10px; color: var(--muted); margin-top: 4px; font-family: ui-monospace, monospace; }
@media (prefers-color-scheme: light) {
  :root {
    --bg: #ffffff; --panel: #f6f8fa; --text: #1f2328;
    --muted: #57606a; --border: #d0d7de;
  }
}
"""


def _cardinal(deg: float | None) -> str:
    if deg is None:
        return "?"
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return dirs[int((deg % 360) / 22.5 + 0.5) % 16]


def _fmt_time(t: datetime) -> str:
    return t.strftime("%-I:%M %p").lstrip("0")


def _fmt_hour(t: datetime) -> str:
    return t.strftime("%-I %p").lstrip("0")


def _fmt_window_range(w: Window) -> str:
    return f"{_fmt_hour(w.start)} – {_fmt_hour(w.end)}"


def _fmt_window_detail(w: Window) -> str:
    h = w.peak_hour
    parts = []
    if h.wave_h_ft is not None and h.wave_T is not None:
        parts.append(f"{h.wave_h_ft:.1f}ft @ {h.wave_T:.0f}s")
    if h.swell_dir is not None:
        parts.append(f"swell {_cardinal(h.swell_dir)}")
    if h.wind_kt is not None and h.wind_dir is not None:
        parts.append(f"wind {_cardinal(h.wind_dir)} {h.wind_kt:.0f}kt")
    parts.append(h.tide_phase.replace("-", " "))
    peak_label = f"peak {_fmt_hour(h.t)}: " + " · ".join(parts)
    return peak_label


def _tide_summary(extremes_for_date) -> str:
    bits = []
    for e in extremes_for_date:
        bits.append(f"{e['type']} {_fmt_time(e['time'])}")
    return " · ".join(bits)


def _now_panel(buoy, fetched_at: datetime) -> str:
    if not buoy:
        return f"""<div class="now"><div class="label">Last updated</div>{fetched_at:%a %b %-d, %-I:%M %p %Z}</div>"""
    bits = []
    if buoy.get("wvht_ft") is not None and buoy.get("dpd_s") is not None:
        bits.append(f"{buoy['wvht_ft']:.1f}ft @ {buoy['dpd_s']:.0f}s")
    if buoy.get("mwd_deg") is not None:
        bits.append(f"swell {_cardinal(buoy['mwd_deg'])}")
    if buoy.get("wspd_kt") is not None and buoy.get("wdir_deg") is not None:
        bits.append(f"wind {_cardinal(buoy['wdir_deg'])} {buoy['wspd_kt']:.0f}kt")
    obs = " · ".join(bits) if bits else "(no wave data)"
    return f"""
<div class="now">
  <div class="label">Buoy 41004 · {buoy['time']:%-I:%M %p}</div>
  {html.escape(obs)}
  <div class="label" style="margin-top:8px">Last updated</div>
  {fetched_at:%a %b %-d, %-I:%M %p %Z}
</div>
"""


def render(windows: list[Window], extremes: list[dict], buoy, fetched_at: datetime) -> str:
    tz = ZoneInfo(config.TZ)

    by_date: dict = defaultdict(list)
    for w in windows:
        by_date[w.start.date()].append(w)

    extremes_by_date: dict = defaultdict(list)
    for e in extremes:
        extremes_by_date[e["time"].date()].append(e)

    days_html = []
    if not windows:
        days_html.append("""<div class="empty">No surfable windows in the next 7 days.<br><span style="font-size:12px">Conditions don't clear the orange threshold. Check back tomorrow.</span></div>""")
    else:
        # Iterate days that have at least one window, in date order
        for date in sorted(by_date.keys()):
            day_windows = by_date[date]
            extremes_today = extremes_by_date.get(date, [])
            tide_str = _tide_summary(extremes_today) if extremes_today else ""
            day_label = date.strftime("%A · %b %-d")

            wins_html = []
            for w in sorted(day_windows, key=lambda x: x.start):
                wins_html.append(f"""
<div class="window {w.color}">
  <div class="win-time">{html.escape(_fmt_window_range(w))}</div>
  <div class="win-detail">{html.escape(_fmt_window_detail(w))}</div>
  <div class="win-score {w.color}">{int(round(w.peak_hour.score * 100))}</div>
</div>
""")

            days_html.append(f"""
<div class="day">
  <div class="day-header"><span>{html.escape(day_label)}</span><span class="tide-line">{html.escape(tide_str)}</span></div>
  {''.join(wins_html)}
</div>
""")

    legend = """
<div class="legend">
<strong>Score buckets:</strong>
<span class="swatch" style="background:var(--bright-green)"></span>≥65 stellar
<span class="swatch" style="background:var(--light-green)"></span>≥45 good
<span class="swatch" style="background:var(--yellow)"></span>≥30 decent
<span class="swatch" style="background:var(--orange)"></span>≥20 marginal<br>
Score = wave · swell-direction · wind-direction · wind-speed · tide (each 0–1, multiplied).
</div>
"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>Folly Beach surf windows</title>
<style>{CSS}</style>
</head>
<body>
<h1>Folly Beach surf windows</h1>
<div class="subtitle">{html.escape(config.SPOT_NAME)} · {config.FORECAST_DAYS}-day outlook</div>
{_now_panel(buoy, fetched_at)}
{''.join(days_html)}
{legend}
<footer>Data: Open-Meteo (waves + wind), NOAA CO-OPS station {config.TIDE_STATION} (tides), NDBC buoy {config.NDBC_BUOY} (current obs). Page auto-refreshes every 15 min.</footer>
</body>
</html>
"""
