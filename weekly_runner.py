"""
weekly_runner.py
----------------
Weekly Runner: Sleeper Fantasy Football   (THE ENTRY POINT)

What one run does:
    1. Reads the current NFL season/week from the Sleeper API
    2. Fetches and stores any completed weeks missing from data/history.json
    3. Applies data quality rules (in memory; history.json stays raw)
    4. Writes the Excel workbook, award/standings images, summary.txt and
       index.html into docs/ at the repo root

Run by hand (prompts for anything you do not supply):
    python weekly_runner.py

Run unattended (GitHub Actions):
    python weekly_runner.py --username YOUR_SLEEPER_NAME --week auto --non-interactive

Inputs (command-line argument, else environment variable, else prompt):
    --username      SLEEPER_USERNAME     Sleeper username (required)
    --week          SLEEPER_WEEK         auto | 14 | 2025-14   (default: auto)
    --week-type     SLEEPER_WEEK_TYPE    regular | playoff | regular+playoff | all (default: regular)
    SLEEPER_LEAGUE_NAME                  only needed if you are in several leagues in a new season
"""

import argparse
import os
import sys

from sleeper_api import (
    get_user,
    get_leagues_for_user,
    get_league_state,
    get_rosters,
    get_users,
    get_playoff_start_week,
)
from history import (
    load_history,
    save_history,
    get_seasons_list,
    fetch_and_store_week,
    _select_league,
)
from data_quality import load_rules, apply_all_rules
from awards import compute_all_awards, find_top_n
from export import export_to_excel
from preview import build_preview_sheet
from image_export import save_award_images, save_standings_images, IMAGE_DIR
from web_output import write_site
from config import set_non_interactive, is_interactive, ask, DOCS_DIR
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill

NEW_WEEK_FILL = PatternFill("solid", start_color="FFFF99")   # bright yellow highlight
NEW_WEEK_FONT = Font(name="Arial", bold=True, size=10, color="1F4E79")


# ---------------------------------------------------------------------------
# Step 1: Detect current state
# ---------------------------------------------------------------------------

def get_current_state() -> tuple[int, int]:
    """Return (current_season, current_week) from the Sleeper API."""
    state = get_league_state()
    if not state:
        raise RuntimeError("Could not fetch NFL state from Sleeper API.")
    return int(state["season"]), int(state["week"])


def get_last_completed_week(
    api_season: int,
    api_week: int,
    history: dict,
) -> tuple[int, int]:
    """
    Return the last completed week we should fetch up to.

    Logic:
        - If current week > 1: fetch up to current_week - 1 (last complete week)
        - If current week == 1: fetch up to the last stored week of the
          previous season, since week 1 of the new season is in progress
          and last season is fully complete.

    Args:
        api_season: Current season from Sleeper API
        api_week:   Current week from Sleeper API
        history:    Raw history dict

    Returns:
        (season, week) of the last completed week
    """
    if api_week > 1:
        return api_season, api_week - 1

    # Week 1 — look at last season's final stored week
    prev_season = api_season - 1
    prev_key    = str(prev_season)
    if prev_key in history:
        weeks = history[prev_key].get("weeks", {})
        if weeks:
            return prev_season, max(int(w) for w in weeks.keys())

    # Previous season not in history yet — return current as fallback
    print(f"  [WARN] Week 1 of new season detected but no history for {prev_season}.")
    print(f"  Consider running a backfill for {prev_season} first.")
    return api_season, api_week


# ---------------------------------------------------------------------------
# Step 2: Fetch any missing weeks up to current week
# ---------------------------------------------------------------------------

def update_history(
    username: str,
    history: dict,
    season: int,
    current_week: int,
) -> tuple[dict, list[int]]:
    """
    Fetch all weeks not yet stored for the given season up to current_week.
    current_week should already be the last *completed* week — use
    get_last_completed_week() to compute this before calling.

    Returns:
        (updated history, list of newly stored week numbers)
    """
    user = get_user(username)
    if not user:
        raise RuntimeError(f"Could not find Sleeper user '{username}'.")
    user_id = user["user_id"]

    leagues = get_leagues_for_user(user_id, season)
    if not leagues:
        raise RuntimeError(f"No leagues found for season {season}.")

    # Pick league — prefer one already in history for this season
    season_key = str(season)
    league = None
    if season_key in history:
        stored_id = history[season_key].get("league_id")
        for lg in leagues:
            if lg["league_id"] == stored_id:
                league = lg
                break
    if not league:
        league = _select_league(leagues, history, season)
        if league is None:
            raise RuntimeError(f"Could not choose a league for season {season}.")

    league_id          = league["league_id"]
    league_name        = league["name"]
    playoff_start_week = get_playoff_start_week(league_id)
    rosters            = get_rosters(league_id)
    users_data         = get_users(league_id)
    if not rosters or not users_data:
        raise RuntimeError(f"Could not fetch rosters/users for season {season}.")

    newly_stored = []
    for week in range(1, current_week + 1):
        # Skip if already in history
        if (
            season_key in history
            and str(week) in history[season_key].get("weeks", {})
        ):
            continue

        history, success = fetch_and_store_week(
            history=history,
            league_id=league_id,
            league_name=league_name,
            season=season,
            week=week,
            playoff_start_week=playoff_start_week,
            rosters=rosters,
            users=users_data,
        )
        if success:
            newly_stored.append(week)
            print(f"  Fetched Season {season} Week {week}")

    return history, newly_stored


# ---------------------------------------------------------------------------
# Step 3: Highlight new week rows in an existing workbook
# ---------------------------------------------------------------------------

def highlight_new_week(filepath: str, season: int, week: int) -> None:
    """
    Re-open the exported workbook and highlight any row belonging
    to the most recently added week with a yellow background.
    Season and Week columns are used to identify matching rows.
    """
    wb = load_workbook(filepath)

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]

        # Find Season and Week column indices from header row
        # Awards sheets have headers on row 3, others on row 1
        for header_row in (1, 3):
            headers = [
                ws.cell(row=header_row, column=c).value
                for c in range(1, ws.max_column + 1)
            ]
            if "Season" in headers and "Week" in headers:
                season_col = headers.index("Season") + 1
                week_col   = headers.index("Week") + 1
                data_start = header_row + 1
                break
        else:
            continue  # sheet has no Season/Week columns

        for row in ws.iter_rows(min_row=data_start, max_row=ws.max_row):
            row_season = ws.cell(row=row[0].row, column=season_col).value
            row_week   = ws.cell(row=row[0].row, column=week_col).value
            if row_season == season and row_week == week:
                for cell in row:
                    cell.fill = NEW_WEEK_FILL
                    cell.font = NEW_WEEK_FONT

    wb.save(filepath)



# ---------------------------------------------------------------------------
# Week input parser
# ---------------------------------------------------------------------------

def parse_week_input(
    raw_input: str,
    api_season: int,
    api_week: int,
    history: dict,
) -> tuple[int, int]:
    """
    Parse a week input string into (season, week).

    Accepted formats:
        ""          -> most recent week stored in history (fallback to API current week)
        "14"        -> week 14 of the current API season
        "2025-14"   -> week 14 of season 2025

    Args:
        raw_input:  Raw string from user input
        api_season: Current season from Sleeper API
        api_week:   Current week from Sleeper API
        history:    Raw history dict (used to find most recent stored week)

    Returns:
        (season, week)
    """
    raw = raw_input.strip()

    # Empty input -> most recent week in history, fallback to API current
    if not raw:
        if history:
            latest_season = max(int(k) for k in history.keys())
            weeks_stored  = history[str(latest_season)].get("weeks", {})
            if weeks_stored:
                latest_week = max(int(w) for w in weeks_stored.keys())
                return latest_season, latest_week
        return api_season, api_week

    # "YYYY-WW" format
    if "-" in raw:
        parts = raw.split("-")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            return int(parts[0]), int(parts[1])

    # Plain week number -> current season
    if raw.isdigit():
        return api_season, int(raw)

    # Unrecognised -> fall back to most recent
    print(f"  [WARN] Could not parse '{raw}' — using most recent week in history.")
    if history:
        latest_season = max(int(k) for k in history.keys())
        weeks_stored  = history[str(latest_season)].get("weeks", {})
        if weeks_stored:
            return latest_season, max(int(w) for w in weeks_stored.keys())
    return api_season, api_week


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

WEEK_TYPES = ["regular", "playoff", "regular+playoff", "all"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Weekly Sleeper league update + report")
    p.add_argument("--username", default=os.environ.get("SLEEPER_USERNAME"),
                   help="Sleeper username (env: SLEEPER_USERNAME)")
    p.add_argument("--week", default=os.environ.get("SLEEPER_WEEK"),
                   help="auto | 14 | 2025-14  (env: SLEEPER_WEEK). auto = last completed week")
    p.add_argument("--week-type", choices=WEEK_TYPES, default=os.environ.get("SLEEPER_WEEK_TYPE"),
                   help="which weeks to include (env: SLEEPER_WEEK_TYPE, default: regular)")
    p.add_argument("--top-n", type=int, default=15, help="rows per award (default 15)")
    p.add_argument("--non-interactive", action="store_true",
                   help="never prompt; fail if an input is missing (implied by CI=true)")
    p.add_argument("--stable-names", action="store_true",
                   help="write *_latest files that overwrite each week (implied when non-interactive)")
    p.add_argument("--force", action="store_true",
                   help="run even if the NFL season is not active")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.non_interactive:
        set_non_interactive(True)
    if args.stable_names or not is_interactive():
        os.environ["SLEEPER_STABLE_NAMES"] = "1"

    print("\n--- Sleeper Fantasy Football | Weekly Runner ---\n")

    # ---- inputs: argument / env var, else prompt (interactive only) ----
    username = (args.username or "").strip() or ask("  Enter your Sleeper username: ").strip()
    if not username:
        sys.exit("ERROR: no Sleeper username supplied (--username or SLEEPER_USERNAME).")

    if args.week is not None:
        week_text = args.week.strip()
    elif is_interactive():
        print("  Which week would you like to report on?")
        print("  Formats: '14' (current season), '2025-14' (specific year), or Enter for most recent")
        week_text = input("  Week: ").strip()
    else:
        week_text = "auto"
    if week_text.lower() == "auto":
        week_text = ""

    if args.week_type:
        week_type = args.week_type
    elif is_interactive():
        print("  Week type filter:")
        print("    [1] Regular season only\n    [2] True playoffs only")
        print("    [3] Regular season + true playoffs\n    [4] All weeks")
        week_type = {"1": "regular", "2": "playoff", "3": "regular+playoff", "4": "all"}.get(
            input("  Select [1]: ").strip(), "regular")
    else:
        week_type = "regular"

    # ---- current state from Sleeper ----
    print("\n  Fetching current NFL state...")
    state = get_league_state()
    if not state:
        sys.exit("ERROR: could not fetch NFL state from the Sleeper API.")
    api_season, api_week = int(state["season"]), int(state["week"])
    season_type = state.get("season_type", "")
    print(f"  Current season: {api_season}, week: {api_week}, type: {season_type or 'unknown'}")

    if (not is_interactive() and not args.force and not week_text
            and season_type in ("off", "pre")):
        print("  NFL season is not active (offseason/preseason) - nothing to do.")
        return 0

    # ---- load history, fetch missing completed weeks ----
    raw_history = load_history()
    existing = get_seasons_list(raw_history)
    print(f"  Existing seasons in history: {existing if existing else 'none'}")

    fetch_season, fetch_week = get_last_completed_week(api_season, api_week, raw_history)
    print(f"  Last completed week: Season {fetch_season} Week {fetch_week}")

    print("\n  Checking for missing weeks...")
    raw_history, newly_stored = update_history(username, raw_history, fetch_season, fetch_week)
    if newly_stored:
        save_history(raw_history)
        print(f"  Stored {len(newly_stored)} new week(s): {newly_stored}")
    else:
        print("  History is already up to date.")

    # Failure check: the last completed week must now be in history
    if str(fetch_week) not in raw_history.get(str(fetch_season), {}).get("weeks", {}):
        sys.exit(f"ERROR: Season {fetch_season} Week {fetch_week} is not in history after the "
                 "update (API returned no data, or all scores were 0).")

    # Resolve the report week AFTER the update so "auto" means the newest stored week
    season, report_week = parse_week_input(week_text, api_season, api_week, raw_history)
    if str(report_week) not in raw_history.get(str(season), {}).get("weeks", {}):
        sys.exit(f"ERROR: Season {season} Week {report_week} is not in history.")
    print(f"  Reporting on: Season {season} Week {report_week}")

    # ---- quality rules (in memory only) ----
    rules = load_rules()
    clean_history, changes = apply_all_rules(raw_history, rules)
    print(f"  {sum(len(v) for v in changes.values())} data-quality rule change(s) applied.")

    # The footnote reads "regular season games through Week N", so never let it
    # name a playoff week. (Highlighting still uses the real report week.)
    psw = clean_history.get(str(season), {}).get("playoff_start_week")
    note_week = min(report_week, psw - 1) if (week_type == "regular" and psw) else report_week

    # Published files use stable *_latest names; clear last run's so that switching
    # week type never leaves stale files on the page. (Runs only after history succeeded.)
    if os.environ.get("SLEEPER_STABLE_NAMES"):
        for old in [*DOCS_DIR.glob("*_latest.xlsx"), *DOCS_DIR.glob("images/*_latest.png")]:
            old.unlink()

    # ---- Excel ----
    print("\n  Exporting to Excel...")
    filepath = export_to_excel(
        clean_history, season=None, week_type=week_type,
        include_awards=True, top_n=args.top_n,
        report_season=season, report_week=note_week,
    )
    print(f"  Exported: {filepath}")

    # Preview sheet: the CURRENT (upcoming) week, fetched live. Non-fatal if it fails.
    print("\n  Adding weekly preview sheet...")
    wb = load_workbook(filepath)
    if build_preview_sheet(wb, username, api_season, api_week, clean_history, raw_history):
        wb.save(filepath)
        print("  Preview sheet added.")
    else:
        print("::warning::Preview sheet could not be built (live matchups unavailable).")
        wb.save(filepath)

    print(f"  Highlighting Season {season} Week {report_week} rows...")
    highlight_new_week(filepath, season, report_week)

    # ---- images ----
    print("\n  Generating images...")
    wt_filter = None if week_type == "all" else week_type
    top = find_top_n(compute_all_awards(clean_history), n=args.top_n, week_type_filter=wt_filter)
    award_paths = save_award_images(
        top_n_data=top, season_filter=None, week_type=week_type,
        highlight_season=season, highlight_week=report_week, n=args.top_n,
    )
    # All-time standings images (unchanged)
    standings_paths = save_standings_images(
        clean_history=clean_history, week_type=week_type,
        report_season=season, report_week=note_week, season_filter=None,
    )
    # Current-season standings images: alternate standings + second lowest winner /
    # second highest loser, limited to the season being reported on
    standings_paths += save_standings_images(
        clean_history=clean_history, week_type=week_type,
        report_season=season, report_week=note_week, season_filter=season,
    )

    # ---- summary + web page ----
    site_files = write_site(clean_history, season, report_week, week_type, excel_path=filepath)

    print("\n  Weekly runner complete!")
    print(f"  Excel:   {filepath}")
    print(f"  Images:  {len(award_paths) + len(standings_paths)} in {IMAGE_DIR}")
    print(f"  Summary: {site_files['summary']}")
    print(f"  Page:    {site_files['index']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
