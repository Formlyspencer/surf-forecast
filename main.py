"""Run the full pipeline: fetch → score → render → write docs/index.html."""
from __future__ import annotations

from pathlib import Path

import fetch
import score
import render


def main():
    from datetime import timedelta

    bundle = fetch.fetch_all()
    hours = score.build_hours(bundle)
    windows = score.find_windows(hours)

    # Build the set of hour-timestamps already covered by real windows so we
    # don't double-display them as red windows.
    covered = set()
    for w in windows:
        cur = w.start
        while cur < w.end:
            covered.add(cur)
            cur += timedelta(hours=1)
    fallback = score.find_fallback_windows(hours, exclude_times=covered)

    html = render.render(
        windows=windows,
        fallback_windows=fallback,
        extremes=bundle["tide_extremes"],
        buoy=bundle["buoy"],
        fetched_at=bundle["fetched_at"],
    )
    out = Path(__file__).parent / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}  ({len(hours)} daylight hours, "
          f"{len(windows)} surf windows, {len(fallback)} fallback)")


if __name__ == "__main__":
    main()
