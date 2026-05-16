"""Run the full pipeline: fetch → score → render → write docs/index.html."""
from __future__ import annotations

from pathlib import Path

import fetch
import score
import render


def main():
    from datetime import timedelta
    import config

    bundle = fetch.fetch_all()
    hours = score.build_hours(bundle)
    real = score.find_windows(hours)

    # Set of hour-timestamps covered by real windows (for fallback dedup)
    covered = set()
    for w in real:
        cur = w.start
        while cur < w.end:
            covered.add(cur)
            cur += timedelta(hours=1)

    # Pull enough red fallback windows for the deep-dive view; the top-5
    # view is just a prefix of these. Both are sorted by find_fallback_windows
    # in descending quality order.
    n_red_deep = max(0, config.DEEP_DIVE_TOTAL_WINDOWS - len(real))
    all_reds = score.find_fallback_windows(hours, n=n_red_deep, exclude_times=covered)

    n_red_top = max(0, config.MIN_TOTAL_WINDOWS - len(real))
    top5_windows = sorted(real + all_reds[:n_red_top], key=lambda w: w.start)
    top20_windows = sorted(real + all_reds, key=lambda w: w.start)

    html = render.render(
        top_windows=top5_windows,
        deep_dive_windows=top20_windows,
        any_real=bool(real),
        extremes=bundle["tide_extremes"],
        buoy=bundle["buoy"],
        fetched_at=bundle["fetched_at"],
    )
    out = Path(__file__).parent / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}  ({len(hours)} daylight hours, "
          f"{len(real)} real, {len(top5_windows)} top5, {len(top20_windows)} top20)")


if __name__ == "__main__":
    main()
