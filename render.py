"""Render the static HTML page from scored windows."""
from __future__ import annotations

import html
import math
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
from score import Hour, Window

# Bar scales — pick maxima that cover Folly's realistic range
WAVE_BAR_MAX_FT = 6.0   # 0-6ft covers ~99% of Folly conditions
PERIOD_BAR_MAX_S = 15.0  # 0-15s covers tropical-grade ground swell


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
  --red: #da3633;
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
}
.win-header {
  display: grid; grid-template-columns: auto 1fr auto; gap: 12px;
  align-items: center;
}
.win-visuals {
  margin-top: 10px; padding-top: 10px;
  border-top: 1px solid var(--border);
  display: grid; grid-template-columns: 1fr; gap: 8px;
}
.tide-spark { width: 100%; height: 38px; display: block; }
.tide-spark .tide-line { fill: none; stroke: var(--muted); stroke-width: 1.5; }
.tide-spark .tide-now { stroke-width: 2; }
.tide-spark text { font-size: 9px; fill: var(--muted); font-family: ui-monospace, monospace; }
.metric-bars { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.metric-bar { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--muted); }
.metric-bar .label { min-width: 38px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; font-size: 10px; }
.metric-bar .track { flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
.metric-bar .fill { height: 100%; border-radius: 3px; }
.metric-bar .value { font-variant-numeric: tabular-nums; min-width: 38px; text-align: right; color: var(--text); font-weight: 600; }
.window.bright-green { border-left-color: var(--bright-green); }
.window.light-green  { border-left-color: var(--light-green); }
.window.yellow       { border-left-color: var(--yellow); }
.window.orange       { border-left-color: var(--orange); }
.window.red          { border-left-color: var(--red); opacity: 0.85; }
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
.win-score.red          { background: var(--red); color: white; }
.fallback-note {
  background: var(--panel); border-left: 4px solid var(--red);
  border-radius: 8px; padding: 10px 14px; margin: 12px 0 16px;
  font-size: 13px; color: var(--text);
}
.fallback-note strong { color: var(--red); }
.fallback-note .sub { color: var(--muted); font-size: 12px; margin-top: 4px; display: block; }
.section-heading {
  font-size: 12px; font-weight: 600; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.06em;
  margin: 28px 0 8px;
}
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


def _tide_at(t: datetime, extremes: list[dict]) -> float | None:
    """Cosine interpolation of tide height between bracketing hi/lo extremes.
    Real tide curves are sums of harmonics, but a single cosine between
    extremes is visually indistinguishable at sparkline resolution.
    """
    before = max((e for e in extremes if e["time"] <= t), key=lambda e: e["time"], default=None)
    after = min((e for e in extremes if e["time"] > t), key=lambda e: e["time"], default=None)
    if not before or not after:
        return None
    span = (after["time"] - before["time"]).total_seconds()
    if span <= 0:
        return before["height_ft"]
    elapsed = (t - before["time"]).total_seconds()
    # S-curve: 0 → 1 monotonically with zero rate at endpoints, peak rate at midpoint
    frac = (1 - math.cos(math.pi * elapsed / span)) / 2
    return before["height_ft"] + frac * (after["height_ft"] - before["height_ft"])


def _tide_sparkline(window: Window, extremes: list[dict], color_var: str) -> str:
    """SVG tide curve ±3h around the window, with the window range highlighted."""
    pad = timedelta(hours=3)
    view_start = window.start - pad
    view_end = window.end + pad
    width, height = 320.0, 38.0
    pad_y_top, pad_y_bot = 4.0, 12.0  # leave room for time labels at bottom

    # Sample every 15 min for a smooth curve
    samples = []
    n_steps = int((view_end - view_start).total_seconds() / 900) + 1
    for i in range(n_steps):
        t = view_start + timedelta(minutes=15 * i)
        h = _tide_at(t, extremes)
        if h is not None:
            samples.append((t, h))
    if len(samples) < 2:
        return ""

    h_min = min(h for _, h in samples)
    h_max = max(h for _, h in samples)
    h_range = max(0.3, h_max - h_min)

    def x_for(t: datetime) -> float:
        frac = (t - view_start).total_seconds() / (view_end - view_start).total_seconds()
        return frac * width

    def y_for(h: float) -> float:
        frac = (h - h_min) / h_range
        return pad_y_top + (1 - frac) * (height - pad_y_top - pad_y_bot)

    # Tide line path
    path_d = "M" + " L".join(f"{x_for(t):.1f},{y_for(h):.1f}" for t, h in samples)

    # Highlighted band for the window range
    bx = x_for(window.start)
    bw = x_for(window.end) - bx
    band = f'<rect x="{bx:.1f}" y="0" width="{bw:.1f}" height="{height - pad_y_bot:.1f}" fill="var({color_var})" opacity="0.18"/>'

    # Dots at bracketing extremes that fall in view. H/L labels go INSIDE the
    # curve area (H dot is at top → label below; L dot is at bottom → label
    # above) so they don't collide with time labels at the bottom.
    dots = []
    for e in extremes:
        if view_start <= e["time"] <= view_end:
            cx = x_for(e["time"])
            cy = y_for(e["height_ft"])
            dots.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.5" fill="var(--muted)"/>')
            label_y = cy + 10 if e["type"] == "H" else cy - 5
            dots.append(f'<text x="{cx:.1f}" y="{label_y:.1f}" text-anchor="middle">{e["type"]}</text>')

    # Time labels at bottom: start and end of window. Peak hour isn't marked
    # here — the detail text already calls out the peak hour by name, no need
    # to duplicate in the sparkline. Dedupe in case start == end (shouldn't
    # happen, but be safe).
    label_y = height - 2
    label_positions = {
        _fmt_hour(window.start): x_for(window.start),
        _fmt_hour(window.end): x_for(window.end),
    }
    labels = [
        f'<text x="{x:.1f}" y="{label_y:.1f}" text-anchor="middle">{html.escape(h)}</text>'
        for h, x in label_positions.items()
    ]

    return f'''<svg class="tide-spark" viewBox="0 0 {width:.0f} {height:.0f}" preserveAspectRatio="none">
{band}
<path class="tide-line" d="{path_d}"/>
{''.join(dots)}
{''.join(labels)}
</svg>'''


def _metric_bars(wave_ft: float | None, period_s: float | None, color_var: str) -> str:
    """Two stacked-ish bars for wave height (0-6ft) and period (0-15s)."""
    wave_pct = min(100, ((wave_ft or 0) / WAVE_BAR_MAX_FT) * 100)
    period_pct = min(100, ((period_s or 0) / PERIOD_BAR_MAX_S) * 100)
    wave_label = f"{wave_ft:.1f} ft" if wave_ft is not None else "—"
    period_label = f"{period_s:.0f} s" if period_s is not None else "—"
    return f'''<div class="metric-bars">
  <div class="metric-bar">
    <span class="label">Wave</span>
    <div class="track"><div class="fill" style="width:{wave_pct:.0f}%;background:var({color_var})"></div></div>
    <span class="value">{wave_label}</span>
  </div>
  <div class="metric-bar">
    <span class="label">Period</span>
    <div class="track"><div class="fill" style="width:{period_pct:.0f}%;background:var({color_var})"></div></div>
    <span class="value">{period_label}</span>
  </div>
</div>'''


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


def render(
    windows: list[Window],
    extremes: list[dict],
    buoy,
    fetched_at: datetime,
    fallback_windows: list[Window] | None = None,
) -> str:
    tz = ZoneInfo(config.TZ)
    fallback_windows = fallback_windows or []

    extremes_by_date: dict = defaultdict(list)
    for e in extremes:
        extremes_by_date[e["time"].date()].append(e)

    def render_day_groups(window_list: list[Window]) -> str:
        """Group windows by day and emit day cards."""
        by_date: dict = defaultdict(list)
        for w in window_list:
            by_date[w.start.date()].append(w)
        out = []
        for date in sorted(by_date.keys()):
            extremes_today = extremes_by_date.get(date, [])
            tide_str = _tide_summary(extremes_today) if extremes_today else ""
            day_label = date.strftime("%A · %b %-d")
            wins_html = []
            for w in sorted(by_date[date], key=lambda x: x.start):
                score_pct = int(round(w.peak_hour.score * 100))
                color_var = f"--{w.color}"
                tide_svg = _tide_sparkline(w, extremes, color_var)
                bars_html = _metric_bars(w.peak_hour.wave_h_ft, w.peak_hour.wave_T, color_var)
                wins_html.append(f"""
<div class="window {w.color}">
  <div class="win-header">
    <div class="win-time">{html.escape(_fmt_window_range(w))}</div>
    <div class="win-detail">{html.escape(_fmt_window_detail(w))}</div>
    <div class="win-score {w.color}">{score_pct}</div>
  </div>
  <div class="win-visuals">
    {tide_svg}
    {bars_html}
  </div>
</div>
""")
            out.append(f"""
<div class="day">
  <div class="day-header"><span>{html.escape(day_label)}</span><span class="tide-line">{html.escape(tide_str)}</span></div>
  {''.join(wins_html)}
</div>
""")
        return ''.join(out)

    days_html = []
    if windows:
        days_html.append(render_day_groups(windows))
        if fallback_windows:
            days_html.append(f"""<div class="section-heading">Next best · sub-threshold</div>""")
            days_html.append(render_day_groups(fallback_windows))
    elif fallback_windows:
        days_html.append(f"""
<div class="fallback-note">
  <strong>Nothing surfable in the next 7 days.</strong>
  <span class="sub">Here are the {len(fallback_windows)} hours where the swell, wind, and tide come closest to lining up — but the wave size is too small to make it worth paddling out. Scores in red.</span>
</div>
""")
        days_html.append(render_day_groups(fallback_windows))
    else:
        days_html.append("""<div class="empty">No data — APIs may be unreachable.<br><span style="font-size:12px">Try refreshing in a few minutes.</span></div>""")

    legend = """
<div class="legend">
<strong>Score buckets:</strong>
<span class="swatch" style="background:var(--bright-green)"></span>≥65 stellar
<span class="swatch" style="background:var(--light-green)"></span>≥45 good
<span class="swatch" style="background:var(--yellow)"></span>≥30 decent
<span class="swatch" style="background:var(--orange)"></span>≥20 marginal
<span class="swatch" style="background:var(--red)"></span>below 20 — shown as filler so the page always lists at least 5 windows<br>
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
