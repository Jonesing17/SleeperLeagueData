"""
preview.py
----------
Weekly Preview: Head-to-head records for current week matchups.

Fetches the current week's matchups live from the Sleeper API
(avoiding partial/zero scores in history) and computes H2H records
from stored history for each matchup.

H2H records use regular season games only.

Records shown per matchup:
    - All-time regular season record
    - This season's regular season record
    - Last 5 direct regular season matchups (game log)

Usage:
    Called from weekly_runner.py, or standalone:
    python preview.py
"""

import os
from datetime import datetime
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins

from sleeper_api import (
    get_user, get_leagues_for_user, get_rosters, get_users,
    get_matchups, get_playoff_start_week, get_playoff_status,
    build_team_map, parse_matchups, get_league_state,
)
from history import load_history
from config import DOCS_DIR, stamp
from data_quality import load_rules, apply_all_rules

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

HEADER_FILL  = PatternFill("solid", fgColor="1F4E79")
ALT_FILL     = PatternFill("solid", fgColor="D6E4F0")
WIN_FILL     = PatternFill("solid", fgColor="E2EFDA")
LOSS_FILL    = PatternFill("solid", fgColor="FCE4D6")
MATCHUP_FILL = PatternFill("solid", fgColor="D9E1F2")

TITLE_FONT   = Font(name="Arial", bold=True, size=12, color="FFFFFF")
HEADER_FONT  = Font(name="Arial", bold=True, size=10, color="FFFFFF")
BODY_FONT    = Font(name="Arial", size=10)
BOLD_FONT    = Font(name="Arial", bold=True, size=10)
NOTE_FONT    = Font(name="Arial", size=11)

CENTER = Alignment(horizontal="center", vertical="center")
LEFT   = Alignment(horizontal="left",   vertical="center")

THIN        = Side(style="thin", color="BBBBBB")
THIN_BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _cell(ws, row, col, value, font=None, fill=None, align=None, num_fmt=None):
    c = ws.cell(row=row, column=col, value=value)
    if font:    c.font   = font
    if fill:    c.fill   = fill
    if align:   c.alignment = align
    if num_fmt: c.number_format = num_fmt
    c.border = THIN_BORDER
    return c


# ---------------------------------------------------------------------------
# H2H computation — regular season only
# ---------------------------------------------------------------------------

def get_h2h_record(
    clean_history: dict,
    team_a: str,
    team_b: str,
    season_filter: Optional[int] = None,
    last_n: Optional[int] = None,
) -> dict:
    """
    Compute head-to-head record between two teams.
    Only counts regular season direct matchups.

    Args:
        clean_history:  Quality-rules-applied history dict
        team_a:         display_name of team A
        team_b:         display_name of team B
        season_filter:  Restrict to a single season (None = all seasons)
        last_n:         If set, only return the N most recent matchups

    Returns:
        {
            "wins_a":  int,
            "wins_b":  int,
            "games":   int,
            "history": [
                {
                    "season": int, "week": int,
                    "score_a": float, "score_b": float,
                    "winner": str,
                }
            ]
        }
    """
    matchup_log = []
    seasons = [str(season_filter)] if season_filter else sorted(clean_history.keys())

    for season_key in seasons:
        season_data = clean_history.get(season_key, {})
        psw = season_data.get("playoff_start_week", 15)

        for week_key, week_data in sorted(
            season_data.get("weeks", {}).items(), key=lambda x: int(x[0])
        ):
            w = int(week_key)
            # Regular season only
            if w >= psw:
                continue

            for m in week_data.get("matchups", []):
                names = {m["home"]["display_name"], m["away"]["display_name"]}
                if {team_a, team_b} != names:
                    continue

                if m["home"]["display_name"] == team_a:
                    score_a = m["home"]["points"]
                    score_b = m["away"]["points"]
                else:
                    score_a = m["away"]["points"]
                    score_b = m["home"]["points"]

                matchup_log.append({
                    "season":  int(season_key),
                    "week":    w,
                    "score_a": score_a,
                    "score_b": score_b,
                    "winner":  team_a if score_a > score_b else team_b,
                })

    if last_n is not None:
        matchup_log = matchup_log[-last_n:]

    wins_a = sum(1 for g in matchup_log if g["winner"] == team_a)
    wins_b = sum(1 for g in matchup_log if g["winner"] == team_b)

    return {
        "wins_a":  wins_a,
        "wins_b":  wins_b,
        "games":   len(matchup_log),
        "history": matchup_log,
    }


# ---------------------------------------------------------------------------
# Fetch live current week matchups
# ---------------------------------------------------------------------------

def fetch_current_matchups(
    username: str,
    season: int,
    week: int,
    raw_history: dict,
) -> Optional[list[dict]]:
    """
    Fetch the current week's matchups live from the Sleeper API.
    Returns list of matchup dicts with display_names, or None on error.
    """
    user = get_user(username)
    if not user:
        print("  [ERROR] Could not find Sleeper user.")
        return None

    leagues = get_leagues_for_user(user["user_id"], season)
    if not leagues:
        print(f"  [ERROR] No leagues found for season {season}.")
        return None

    # Prefer league already stored in history for this season
    stored_id = raw_history.get(str(season), {}).get("league_id")
    league    = next((lg for lg in leagues if lg["league_id"] == stored_id), leagues[0])

    league_id          = league["league_id"]
    playoff_start_week = get_playoff_start_week(league_id)
    rosters            = get_rosters(league_id)
    users_data         = get_users(league_id)

    if not rosters or not users_data:
        print("  [ERROR] Could not fetch rosters/users.")
        return None

    raw_matchups = get_matchups(league_id, week)
    if not raw_matchups:
        print(f"  [ERROR] No matchups returned for Week {week}.")
        return None

    status_map = None
    if week >= playoff_start_week:
        all_roster_ids = [r["roster_id"] for r in rosters]
        status_map = get_playoff_status(
            league_id, week, playoff_start_week, all_roster_ids
        )

    team_map = build_team_map(rosters, users_data)
    parsed   = parse_matchups(raw_matchups, team_map, status_map=status_map)
    return parsed.get("matchups", [])


# ---------------------------------------------------------------------------
# Build preview Excel sheet
# ---------------------------------------------------------------------------

def build_preview_sheet(
    wb: Workbook,
    username: str,
    season: int,
    week: int,
    clean_history: dict,
    raw_history: dict,
) -> bool:
    """
    Add a 'Week N Preview' sheet to the workbook.
    Shows each matchup with all-time, season, and last-5 H2H records
    (regular season only).
    """
    ws = wb.create_sheet(title=f"Week {week} Preview")
    ws.sheet_view.showGridLines = False

    for letter, width in {
        "A": 2, "B": 16, "C": 16, "D": 7,
        "E": 7, "F": 4, "G": 16, "H": 7, "I": 7, "J": 2,
    }.items():
        ws.column_dimensions[letter].width = width

    S = 2   # data starts in column B
    r = 2   # start with one blank row

    print(f"    Fetching Week {week} matchups live from Sleeper API...")
    matchups = fetch_current_matchups(username, season, week, raw_history)

    if not matchups:
        ws.cell(row=r, column=S, value="Could not fetch matchups for this week.")
        return False

    for m in matchups:
        team_a = m["home"]["display_name"]
        team_b = m["away"]["display_name"]

        # ── Matchup title row ──────────────────────────────────────────────
        ws.merge_cells(
            start_row=r, start_column=S,
            end_row=r,   end_column=S + 7
        )
        c = ws.cell(row=r, column=S, value=f"{team_a}  vs  {team_b}")
        c.font = TITLE_FONT; c.fill = HEADER_FILL; c.alignment = CENTER
        r += 1

        # ── Column sub-headers ─────────────────────────────────────────────
        for col, val in [
            (S,   "Record"),
            (S+1, team_a), (S+2, "W"), (S+3, "L"),
            (S+4, ""),
            (S+5, team_b), (S+6, "W"), (S+7, "L"),
        ]:
            _cell(ws, r, col, val, font=HEADER_FONT, fill=MATCHUP_FILL, align=CENTER)
        r += 1

        # ── H2H record rows ────────────────────────────────────────────────
        h2h_all    = get_h2h_record(clean_history, team_a, team_b)
        h2h_season = get_h2h_record(clean_history, team_a, team_b, season_filter=season)
        h2h_last5  = get_h2h_record(clean_history, team_a, team_b, last_n=5)

        records = [
            ("All-Time",          h2h_all,    False),
            (f"{season} Season",  h2h_season, True),
            ("Last 5 Matchups",   h2h_last5,  False),
        ]

        for label, h2h, alt in records:
            fill = ALT_FILL if alt else None
            _cell(ws, r, S,   label,           font=BOLD_FONT, fill=fill, align=LEFT)
            _cell(ws, r, S+1, team_a,          font=BODY_FONT, fill=fill, align=LEFT)
            _cell(ws, r, S+2, h2h["wins_a"],   font=BODY_FONT, fill=fill, align=CENTER)
            _cell(ws, r, S+3, h2h["wins_b"],   font=BODY_FONT, fill=fill, align=CENTER)
            _cell(ws, r, S+4, "",              font=BODY_FONT, fill=fill, align=CENTER)
            _cell(ws, r, S+5, team_b,          font=BODY_FONT, fill=fill, align=LEFT)
            _cell(ws, r, S+6, h2h["wins_b"],   font=BODY_FONT, fill=fill, align=CENTER)
            _cell(ws, r, S+7, h2h["wins_a"],   font=BODY_FONT, fill=fill, align=CENTER)
            r += 1

        # ── Last 5 game log ────────────────────────────────────────────────
        if h2h_last5["history"]:
            r += 1
            for col, val in [
                (S, "Season"), (S+1, "Week"),
                (S+2, team_a), (S+3, "vs"), (S+4, team_b),
                (S+5, "Winner"),
            ]:
                _cell(ws, r, col, val, font=HEADER_FONT, fill=MATCHUP_FILL, align=CENTER)
            r += 1

            for i, game in enumerate(reversed(h2h_last5["history"])):
                win_a = game["winner"] == team_a
                alt   = ALT_FILL if i % 2 == 0 else None
                w_fill = WIN_FILL if win_a else LOSS_FILL

                _cell(ws, r, S,   game["season"],  font=BODY_FONT, fill=alt,    align=CENTER)
                _cell(ws, r, S+1, f"Wk {game['week']}", font=BODY_FONT, fill=alt, align=CENTER)
                _cell(ws, r, S+2, game["score_a"], font=BODY_FONT, fill=alt,    align=CENTER, num_fmt="#,##0.00")
                _cell(ws, r, S+3, "vs",            font=BODY_FONT, fill=alt,    align=CENTER)
                _cell(ws, r, S+4, game["score_b"], font=BODY_FONT, fill=alt,    align=CENTER, num_fmt="#,##0.00")
                _cell(ws, r, S+5, game["winner"],  font=BOLD_FONT, fill=w_fill, align=LEFT)
                r += 1

        r += 2  # gap between matchups

    # Asterisk note
    c = ws.cell(row=r, column=S,
                value=f"*Live matchups fetched for Season {season} Week {week}. H2H records use regular season only.")
    c.font = NOTE_FONT

    ws.print_area   = f"A1:J{r}"
    ws.page_margins = PageMargins(left=0.25, right=0.25, top=0.75, bottom=0.75)
    return True


# ---------------------------------------------------------------------------
# Main: standalone runner
# ---------------------------------------------------------------------------

def main():
    print("\n--- Sleeper Fantasy Football | Weekly Preview ---\n")

    raw_history = load_history()
    if not raw_history:
        print("  No history found. Run history.py first.")
        return

    rules = load_rules()
    clean_history, _ = apply_all_rules(raw_history, rules)

    state          = get_league_state()
    current_season = int(state["season"]) if state else 2024
    current_week   = int(state["week"])   if state else 1

    username     = input("  Enter your Sleeper username: ").strip()
    season_input = input(f"  Season [{current_season}]: ").strip()
    season       = int(season_input) if season_input else current_season
    week_input   = input(f"  Week [{current_week}]: ").strip()
    week         = int(week_input) if week_input else current_week

    wb = Workbook()
    wb.remove(wb.active)
    build_preview_sheet(wb, username, season, week, clean_history, raw_history)

    export_dir = str(DOCS_DIR)
    os.makedirs(export_dir, exist_ok=True)
    filepath = os.path.join(
        export_dir,
        f"preview_{season}_week{week}_{stamp()}.xlsx"
    )
    wb.save(filepath)
    print(f"\n  Preview saved to: {filepath}")


if __name__ == "__main__":
    main()
