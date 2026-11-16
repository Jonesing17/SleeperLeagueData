"""
web_output.py
-------
Writes the files GitHub Pages serves from docs/:
    docs/summary.txt   plain-text recap of the reported week's awards
    docs/index.html    landing page: summary, Excel download, all images
    docs/.nojekyll     tells GitHub Pages to serve the folder as-is
"""

import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from awards import (
    compute_all_awards,
    compute_weekly_awards,
    find_all_time_records,
    is_all_time_record,
)
from config import DOCS_DIR, IMAGES_DIR

MARGIN_AWARDS = {"Biggest Win", "Closest Game"}


def build_summary(clean_history: dict, season: int, week: int, week_type: str) -> str:
    season_data = clean_history.get(str(season), {})
    week_data = season_data.get("weeks", {}).get(str(week))
    if not week_data:
        raise ValueError(f"Season {season} Week {week} is not in history.")

    psw = season_data.get("playoff_start_week", 15)
    weekly = compute_weekly_awards(week_data, season=season, week=week, playoff_start_week=psw)

    wt_filter = None if week_type == "all" else week_type
    records = find_all_time_records(compute_all_awards(clean_history), week_type_filter=wt_filter)

    lines = [
        f"Season {season}  Week {week}  ({weekly.week_type})",
        f"Updated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]
    for e in weekly.all_awards():
        flag = "   *** ALL-TIME RECORD ***" if is_all_time_record(e, records) else ""
        if e.award in MARGIN_AWARDS:
            lines.append(f"{e.award:<14} {e.winner} by {e.value:.2f} (vs {e.opponent}){flag}")
        else:
            lines.append(f"{e.award:<14} {e.winner} - {e.value:.2f} (vs {e.opponent}){flag}")
    return "\n".join(lines) + "\n"


def _image_files() -> list:
    if not IMAGES_DIR.exists():
        return []
    files = sorted(IMAGES_DIR.glob("*.png"))
    latest = [f for f in files if f.stem.endswith("_latest")]
    files = latest or files                      # prefer the stable weekly files
    def order(f):
        group = (0 if f.name.startswith("standings_combined")
                 else 1 if f.name.startswith("second_high_low_combined") else 2)
        has_year = bool(re.search(r"_\d{4}_", f.name))      # season files after all-time
        return (group, has_year, f.name)
    return sorted(files, key=order)


def _caption(f: Path) -> str:
    name = f.stem.removesuffix("_latest")
    m = re.search(r"_(\d{4})$", name)
    scope = f"{m.group(1)} season" if m else "all-time"
    if m:
        name = name[: m.start()]
    if name.startswith(("standings_combined", "second_high_low_combined")):
        title = "Standings" if name.startswith("standings") else "Second Lowest Winner / Second Highest Loser"
        return f"{title} - {scope}"
    name = re.sub(r"_(?:all|\d{4})_[a-z+]+$", "", name)   # drop scope/week-type suffix
    return name.replace("_", " ").title()


def write_site(
    clean_history: dict,
    season: int,
    week: int,
    week_type: str,
    excel_path: Optional[str] = None,
) -> dict:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / ".nojekyll").write_text("")

    summary = build_summary(clean_history, season, week, week_type)
    (DOCS_DIR / "summary.txt").write_text(summary, encoding="utf-8")

    imgs = "\n".join(
        f'<figure><figcaption>{html.escape(_caption(f))}</figcaption><img src="images/{html.escape(f.name)}" alt="{html.escape(_caption(f))}" loading="lazy"></figure>'
        for f in _image_files()
    )
    xlsx = ""
    if excel_path:
        name = Path(excel_path).name
        xlsx = f'<p><a href="{html.escape(name)}">Download the full Excel workbook</a></p>'

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>League recap - Season {season} Week {week}</title>
<style>
 body{{font-family:Arial,Helvetica,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#222}}
 h1{{color:#1F4E79}} pre{{background:#f3f6fa;padding:1rem;overflow-x:auto}}
 figure{{margin:1.5rem 0}} img{{max-width:100%;height:auto;border:1px solid #ccc;border-radius:8px}}
</style></head><body>
<h1>League recap - Season {season} Week {week}</h1>
<pre>{html.escape(summary)}</pre>
{xlsx}
{imgs}
</body></html>
"""
    (DOCS_DIR / "index.html").write_text(page, encoding="utf-8")
    return {"summary": str(DOCS_DIR / "summary.txt"), "index": str(DOCS_DIR / "index.html")}
