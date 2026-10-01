"""
weekly_runner.py
----------------
Weekly Runner: Sleeper Fantasy Football

Run this once a week after scores are finalised. It will:
    1. Detect the current NFL season and week from the Sleeper API
    2. Fetch and store any weeks not yet in history
    3. Apply data quality rules to produce clean history
    4. Compute all awards, flagging results from the most recent week
    5. Export a formatted Excel workbook to data/exports/

Usage:
    python weekly_runner.py
"""

import os
from datetime import datetime

from sleeper_api import (
    get_user,
    get_leagues_for_user,
    get_league_state,
    get_rosters,
    get_users,
    get_playoff_start_week,
    build_team_map,
)
from history import (
    load_history,
    save_history,
    get_seasons_list,
    fetch_and_store_week,
)
from data_quality import load_rules, apply_all_rules
from awards import compute_all_awards, find_top_n
from export import export_to_excel
from image_export import save_award_images, save_standings_images, IMAGE_DIR
from awards import compute_all_awards, find_top_n
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
EXPORT_DIR           = os.path.join(os.path.dirname(__file__), "data", "exports")

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
        league = leagues[0] if len(leagues) == 1 else _prompt_league(leagues, season)

    league_id          = league["league_id"]
    league_name        = league["name"]
    playoff_start_week = get_playoff_start_week(league_id)
    rosters            = get_rosters(league_id)
    users_data         = get_users(league_id)

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


def _prompt_league(leagues: list, season: int) -> dict:
    print(f"\n  Multiple leagues found for {season}:")
    for i, lg in enumerate(leagues):
        print(f"    [{i}] {lg['name']}")
    idx = input("  Select league number: ").strip()
    return leagues[int(idx)]


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

def main():
    print("\n--- Sleeper Fantasy Football | Weekly Runner ---\n")

    username = input("  Enter your Sleeper username: ").strip()

    # Step 1: Detect current state
    print("\n  Fetching current NFL state...")
    api_season, api_week = get_current_state()
    print(f"  Current season: {api_season}, current week: {api_week}")

    # Step 2: Load history early so parse_week_input can find the most recent stored week
    print("\n  Loading history...")
    raw_history = load_history()
    existing = get_seasons_list(raw_history)
    print(f"  Existing seasons in history: {existing if existing else 'none'}")

    # Determine the last completed week to fetch up to
    fetch_season, fetch_week = get_last_completed_week(api_season, api_week, raw_history)
    print(f"  Last completed week: Season {fetch_season} Week {fetch_week}")

    # Week selection for the report
    print()
    print("  Which week would you like to report on?")
    print("  Formats: '14' (current season), '2025-14' (specific year), or Enter for most recent")
    week_input   = input("  Week: ").strip()
    season, current_week = parse_week_input(week_input, api_season, api_week, raw_history)
    print(f"  Reporting on: Season {season} Week {current_week}")

    print("\n  Checking for missing weeks...")
    raw_history, newly_stored = update_history(username, raw_history, fetch_season, fetch_week)

    if newly_stored:
        save_history(raw_history)
        print(f"\n  Stored {len(newly_stored)} new week(s): {newly_stored}")
    else:
        print("  History is already up to date.")

    # Step 3: Apply quality rules
    print("\n  Applying data quality rules...")
    rules = load_rules()
    clean_history, changes = apply_all_rules(raw_history, rules)
    total_changes = sum(len(v) for v in changes.values())
    print(f"  {total_changes} rule change(s) applied.")

    # Step 4: Export to Excel
    print("\n  Exporting to Excel...")
    print("  Week type filter:")
    print("    [1] Regular season only")
    print("    [2] True playoffs only")
    print("    [3] Regular season + true playoffs")
    print("    [4] All weeks")
    wt_choice = input("  Select [4]: ").strip()
    wt_map = {"1": "regular", "2": "playoff", "3": "regular+playoff", "4": "all"}
    week_type = wt_map.get(wt_choice, "all")

    filepath = export_to_excel(
        clean_history,
        season=None,
        week_type=week_type,
        include_awards=True,
        top_n=15,
        report_season=season,
        report_week=current_week,
    )
    print(f"  Exported: {filepath}")

    # Step 5: Highlight the reported week rows
    print(f"\n  Highlighting Season {season} Week {current_week} rows...")
    highlight_new_week(filepath, season, current_week)
    print("  Done.")

    # Step 6: Generate images
    print("\n  Generating award images...")
    wt_filter = None if week_type == "all" else week_type
    all_wa    = compute_all_awards(clean_history)
    top       = find_top_n(all_wa, n=15, week_type_filter=wt_filter)
    award_paths = save_award_images(
        top_n_data       = top,
        season_filter    = None,
        week_type        = week_type,
        highlight_season = season,
        highlight_week   = current_week,
        n                = 15,
    )
    print(f"  {len(award_paths)} award image(s) saved.")

    print("\n  Generating standings images...")
    standings_paths = save_standings_images(
        clean_history  = clean_history,
        week_type      = week_type,
        report_season  = season,
        report_week    = current_week,
    )
    print(f"  {len(standings_paths)} standings image(s) saved.")

    total_images = len(award_paths) + len(standings_paths)
    print(f"\n  Weekly runner complete!")
    print(f"  Excel: {filepath}")
    print(f"  Images ({total_images}): {IMAGE_DIR}\n")


if __name__ == "__main__":
    main()
