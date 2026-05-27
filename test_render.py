"""Visual smoke test — synthesizes a forecast with one window of each color
so you can verify the render before there are real green windows.

Run: python test_render.py  →  writes docs/test.html
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
import score
import render


def _hour(t, swell_h, swell_dir, swell_T, wave_h, wave_T, wind_kt, wind_dir, phase):
    ws = score.wave_score(wave_h, wave_T)
    sds = score.swell_dir_score(swell_dir)
    wds = score.wind_dir_score(wind_dir)
    wss = score.wind_speed_score(wind_kt)
    # Pick tide score based on phase label
    tide_lookup = {"high-peak": 1.0, "rising-late": 0.9, "rising": 0.7,
                   "falling-near": 0.9, "falling": 0.7, "rising-early": 0.4,
                   "falling-mid": 0.4, "low-nogo": 0.0}
    ts = tide_lookup.get(phase, 0.7)
    return score.Hour(
        t=t, swell_h_ft=swell_h, swell_dir=swell_dir, swell_T=swell_T,
        wave_h_ft=wave_h, wave_dir=swell_dir, wave_T=wave_T,
        wind_wave_h_ft=0.0,
        wind_kt=wind_kt, wind_dir=wind_dir, wind_gust_kt=wind_kt+5,
        tide_phase=phase.replace("-", " "),
        score=ws*sds*wds*wss*ts,
        factors={"wave":round(ws,2),"swell_dir":round(sds,2),
                 "wind_dir":round(wds,2),"wind_speed":round(wss,2),"tide":round(ts,2),
                 "mixed_sea":1.0},
    )


def main():
    tz = ZoneInfo(config.TZ)
    base = datetime.now(tz).replace(hour=7, minute=0, second=0, microsecond=0) + timedelta(days=1)

    hours = []
    # Day 1: bright-green window 7-10am (4ft @ 11s SE, NW 5kt, late-rising to high)
    for i in range(3):
        hours.append(_hour(base + timedelta(hours=i), 3.5, 135, 11, 4.0, 11, 5, 315, "high-peak"))

    # Day 2: light-green window 8-11am (3.5ft @ 10s ESE, N 8kt, rising)
    d2 = base + timedelta(days=1, hours=1)
    for i in range(3):
        hours.append(_hour(d2 + timedelta(hours=i), 3.0, 110, 10, 3.5, 10, 8, 350, "rising"))

    # Day 3: yellow window 9am-12pm (3ft @ 9s S, light onshore SE 7kt, rising late)
    d3 = base + timedelta(days=2, hours=2)
    for i in range(3):
        hours.append(_hour(d3 + timedelta(hours=i), 2.5, 175, 9, 3.0, 9, 7, 130, "rising-late"))

    # Day 4: orange window 10am-12pm (2.5ft @ 7s E, SE 12kt, falling)
    d4 = base + timedelta(days=3, hours=3)
    for i in range(3):
        hours.append(_hour(d4 + timedelta(hours=i), 2.2, 95, 7, 2.6, 7, 12, 140, "falling-near"))

    windows = score.find_windows(hours)
    print(f"Synthesized {len(windows)} windows:")
    for w in windows:
        print(f"  {w.start:%a %I%p} – {w.end:%I%p}  {w.color}  peak={w.peak_hour.score:.2f}")

    fake_extremes = []
    fake_buoy = {
        "time": datetime.now(tz),
        "wvht_ft": 2.8, "dpd_s": 8, "mwd_deg": 130,
        "wspd_kt": 6, "wdir_deg": 320,
    }
    html = render.render(windows, fake_extremes, fake_buoy, datetime.now(tz))

    from pathlib import Path
    out = Path(__file__).parent / "docs" / "test.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
