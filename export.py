"""
export.py
---------
Phase 3.6: Sleeper Fantasy Football - Excel Export for Data Validation

Exports history and standings to a formatted Excel workbook for
data validation and review. Each export produces a timestamped file
in the data/exports/ folder.

Sheets produced:
    - Standings         : Team records, PF, PA per selected scope
    - Matchups          : Every head-to-head result with metadata
    - Byes              : Bye week entries with scores and playoff status

Usage:
    python export.py
"""

import json
import os
from datetime import datetime
from typing import Optional

from openpyxl import Workbook
from openpyxl.worksheet.page import PageMargins
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from awards import compute_all_awards, find_top_n
from data_quality import load_rules, apply_all_rules
from history import (
    load_history,
    get_all_weeks,
    get_seasons_list,
    compute_standings,
    compute_beat_average_standings,
    compute_schedules_against_everyone,
    compute_second_lowest_winner,
    compute_second_highest_loser,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_HISTORY_PATH = os.path.join(os.path.dirname(__file__), "data", "history.json")
EXPORT_DIR = os.path.join(os.path.dirname(__file__), "data", "exports")

# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------

HEADER_FILL   = PatternFill("solid", start_color="1F4E79")   # dark blue
ALT_FILL      = PatternFill("solid", start_color="D6E4F0")   # light blue
PLAYOFF_FILL  = PatternFill("solid", start_color="E2EFDA")   # light green
ELIM_FILL     = PatternFill("solid", start_color="FCE4D6")   # light orange
HEADER_FONT   = Font(name="Arial", bold=True, color="FFFFFF", size=10)
BODY_FONT     = Font(name="Arial", size=10)
BOLD_FONT     = Font(name="Arial", bold=True, size=10)
CENTER        = Alignment(horizontal="center", vertical="center")
LEFT          = Alignment(horizontal="left",   vertical="center")
THIN          = Side(style="thin", color="BBBBBB")
THIN_BORDER   = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def style_header_row(ws, row: int, num_cols: int) -> None:
    for col in range(1, num_cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.font   = HEADER_FONT
        cell.fill   = HEADER_FILL
        cell.alignment = CENTER
        cell.border = THIN_BORDER


def style_data_row(ws, row: int, num_cols: int, fill: PatternFill = None) -> None:
    for col in range(1, num_cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.font      = BODY_FONT
        cell.alignment = LEFT
        cell.border    = THIN_BORDER
        if fill:
            cell.fill = fill


def set_col_widths(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def freeze_top_row(ws) -> None:
    ws.freeze_panes = "A2"


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------

def build_standings_sheet(wb: Workbook, standings: list[dict], title: str) -> None:
    ws = wb.create_sheet(title=title[:31])  # Excel sheet name limit

    headers = ["Rank", "Username", "Wins", "Losses", "Win %", "Points For", "Points Against", "Weeks Played", "Seasons"]
    ws.append(headers)
    style_header_row(ws, 1, len(headers))
    freeze_top_row(ws)

    for i, t in enumerate(standings):
        row_num = i + 2
        total   = t["wins"] + t["losses"]
        win_pct = f'=C{row_num}/(C{row_num}+D{row_num})' if total > 0 else 0
        seasons_str = ", ".join(str(s) for s in t["seasons"])

        ws.append([
            t["rank"],
            t["display_name"],
            t["wins"],
            t["losses"],
            win_pct,
            t["points_for"],
            t["points_against"],
            t["weeks_played"],
            seasons_str,
        ])

        fill = ALT_FILL if i % 2 == 0 else None
        style_data_row(ws, row_num, len(headers), fill)
        ws.cell(row=row_num, column=5).number_format  = "0.0%"
        ws.cell(row=row_num, column=6).number_format  = "#,##0.00"
        ws.cell(row=row_num, column=7).number_format  = "#,##0.00"
        ws.cell(row=row_num, column=1).alignment = CENTER
        ws.cell(row=row_num, column=3).alignment = CENTER
        ws.cell(row=row_num, column=4).alignment = CENTER
        ws.cell(row=row_num, column=5).alignment = CENTER
        ws.cell(row=row_num, column=8).alignment = CENTER

    set_col_widths(ws, [6, 22, 7, 7, 8, 13, 15, 13, 20])


def build_matchups_sheet(wb: Workbook, weeks: list[dict]) -> None:
    ws = wb.create_sheet(title="Matchups")

    headers = [
        "Season", "Week", "Week Type", "Matchup Type",
        "Winner / Team", "Winner Pts", "Loser / Opponent", "Loser Pts", "Margin"
    ]
    ws.append(headers)
    style_header_row(ws, 1, len(headers))
    freeze_top_row(ws)

    row_num = 2
    for week in weeks:
        season    = week["season"]
        week_num  = week["week"]
        week_type = week["week_type"]

        # Head-to-head matchups
        for m in week.get("matchups", []):
            matchup_status = m.get("playoff_status", week_type)
            ws.append([
                season,
                week_num,
                week_type.title(),
                matchup_status.title(),
                m["home"]["display_name"],
                m["home"]["points"],
                m["away"]["display_name"],
                m["away"]["points"],
                m["margin"],
            ])

            if matchup_status == "playoff":
                fill = PLAYOFF_FILL
            elif matchup_status == "eliminated":
                fill = ELIM_FILL
            else:
                fill = ALT_FILL if row_num % 2 == 0 else None

            style_data_row(ws, row_num, len(headers), fill)
            for col in (1, 2, 6, 8, 9):
                ws.cell(row=row_num, column=col).alignment = CENTER
            for col in (6, 8, 9):
                ws.cell(row=row_num, column=col).number_format = "#,##0.00"
            row_num += 1

        # Bye teams appended at the bottom of the same sheet
        for b in week.get("byes", []):
            bye_status = b.get("playoff_status", "regular")
            ws.append([
                season,
                week_num,
                week_type.title(),
                bye_status.title(),
                b["display_name"],
                b["points"],
                "— BYE —",
                "",
                "",
            ])

            if bye_status == "bye":
                fill = PLAYOFF_FILL
            elif bye_status == "eliminated":
                fill = ELIM_FILL
            else:
                fill = ALT_FILL if row_num % 2 == 0 else None

            style_data_row(ws, row_num, len(headers), fill)
            for col in (1, 2, 6):
                ws.cell(row=row_num, column=col).alignment = CENTER
            ws.cell(row=row_num, column=6).number_format = "#,##0.00"
            row_num += 1

    set_col_widths(ws, [8, 7, 12, 14, 22, 12, 22, 12, 10])





AWARD_DESCRIPTIONS = {
    "Highest Score": "Highest points scored by a single team in a week",
    "Lowest Score":  "Lowest points scored by a single team in a week",
    "Biggest Win":   "Largest margin of victory in a single matchup",
    "Closest Game":  "Smallest margin of victory in a single matchup",
    "Highest Loss":  "Highest score that still resulted in a loss (unlucky award)",
    "Lowest Win":    "Lowest score that still resulted in a win (lucky award)",
}

GOLD_FILL   = PatternFill("solid", start_color="FFD700")
SILVER_FILL = PatternFill("solid", start_color="C0C0C0")
BRONZE_FILL = PatternFill("solid", start_color="CD7F32")
RECORD_FONT = Font(name="Arial", bold=True, size=10, color="1F4E79")


def build_awards_sheets(
    wb: Workbook,
    top_n: dict,
    scope: str,
    week_type: str,
) -> None:
    """
    Add one sheet per award category to the workbook, each showing
    the top N results with rank, username, value, opponent, season, week.
    The #1 entry is highlighted gold, #2 silver, #3 bronze.
    """
    # Score awards with W/L: result isn't implied so include W/L column
    wl_score_awards = {"Highest Score", "Lowest Score"}
    # Score awards without W/L: result is implied by the award name
    no_wl_score_awards = {"Highest Loss", "Lowest Win"}
    score_awards   = wl_score_awards | no_wl_score_awards
    # Margin awards: show winner name + winner score + loser name + loser score + margin
    margin_awards  = {"Biggest Win", "Closest Game"}

    for award_name, entries in top_n.items():
        if not entries:
            continue

        sheet_title = award_name[:31]
        ws = wb.create_sheet(title=sheet_title)

        is_margin = award_name in margin_awards
        num_cols  = 9 if is_margin else 8

        # Title and description rows
        ws.merge_cells(f"A1:{get_column_letter(num_cols)}1")
        ws.merge_cells(f"A2:{get_column_letter(num_cols)}2")
        title_cell = ws["A1"]
        title_cell.value     = f"{award_name} — {scope} ({week_type.title()})"
        title_cell.font      = Font(name="Arial", bold=True, size=12, color="1F4E79")
        title_cell.alignment = CENTER
        desc_cell = ws["A2"]
        desc_cell.value     = AWARD_DESCRIPTIONS.get(award_name, "")
        desc_cell.font      = Font(name="Arial", italic=True, size=9, color="666666")
        desc_cell.alignment = LEFT

        # Headers differ by award type
        if is_margin:
            # Biggest Win / Closest Game: no W/L column, show both scores + margin
            headers = ["Rank", "Winner", "Winner Score", "Loser", "Loser Score", "Margin", "Season", "Week", "Matchup Type"]
            col_widths = [6, 22, 14, 22, 14, 10, 8, 7, 14]
        elif award_name in wl_score_awards:
            # Highest Score / Lowest Score: include W/L since result isn't implied
            headers = ["Rank", "Username", "Score", "Opponent", "Opp Score", "W/L", "Season", "Week", "Week Type", "Matchup Type"]
            col_widths = [6, 22, 12, 22, 12, 6, 8, 7, 12, 14]
        else:
            # Highest Loss / Lowest Win: no W/L since result is implied by award name
            headers = ["Rank", "Username", "Score", "Opponent", "Opp Score", "Season", "Week", "Week Type", "Matchup Type"]
            col_widths = [6, 22, 12, 22, 12, 8, 7, 12, 14]

        ws.append(headers)
        style_header_row(ws, 3, len(headers))
        ws.freeze_panes = "A4"

        for i, entry in enumerate(entries):
            rank    = i + 1
            row_num = i + 4

            if is_margin:
                row_data = [
                    rank,
                    entry.winner,
                    entry.winner_score if entry.winner_score is not None else "—",
                    entry.opponent if entry.opponent else "—",
                    entry.loser_score if entry.loser_score is not None else "—",
                    entry.value,
                    entry.season,
                    entry.week,
                    entry.matchup_type.title(),
                ]
                score_cols = (3, 5, 6)
            elif award_name in wl_score_awards:
                row_data = [
                    rank,
                    entry.winner,
                    entry.value,
                    entry.opponent if entry.opponent else "—",
                    entry.opponent_score if entry.opponent_score is not None else "—",
                    entry.result if entry.result else "—",
                    entry.season,
                    entry.week,
                    entry.week_type.title(),
                    entry.matchup_type.title(),
                ]
                score_cols = (3, 5)
            else:
                row_data = [
                    rank,
                    entry.winner,
                    entry.value,
                    entry.opponent if entry.opponent else "—",
                    entry.opponent_score if entry.opponent_score is not None else "—",
                    entry.season,
                    entry.week,
                    entry.week_type.title(),
                    entry.matchup_type.title(),
                ]
                score_cols = (3, 5)

            ws.append(row_data)

            if rank == 1:
                fill = GOLD_FILL
                font = RECORD_FONT
            elif rank == 2:
                fill = SILVER_FILL
                font = BOLD_FONT
            elif rank == 3:
                fill = BRONZE_FILL
                font = BOLD_FONT
            else:
                fill = ALT_FILL if rank % 2 == 0 else None
                font = BODY_FONT

            for col in range(1, len(headers) + 1):
                cell = ws.cell(row=row_num, column=col)
                cell.font      = font
                cell.border    = THIN_BORDER
                cell.alignment = CENTER if col != 2 else LEFT
                if fill:
                    cell.fill = fill

            for col in score_cols:
                ws.cell(row=row_num, column=col).number_format = "#,##0.00"

        set_col_widths(ws, col_widths)



def build_alt_standings_sheet(
    wb: Workbook,
    standings: list[dict],
    title: str,
    has_points_against: bool = False,
) -> None:
    """Build an alternate standings sheet (Beat the Average or Schedules Against Everyone)."""
    ws = wb.create_sheet(title=title[:31])

    if has_points_against:
        headers = ["Rank", "Username", "Wins", "Losses", "Win %", "Points For", "Points Against", "Weeks Played", "Seasons"]
    else:
        headers = ["Rank", "Username", "Wins", "Losses", "Win %", "Points For", "Weeks Played", "Seasons"]

    ws.append(headers)
    style_header_row(ws, 1, len(headers))
    freeze_top_row(ws)

    for i, t in enumerate(standings):
        row_num  = i + 2
        total    = t["wins"] + t["losses"]
        win_pct  = f'=C{row_num}/(C{row_num}+D{row_num})' if total > 0 else 0
        seasons_str = ", ".join(str(s) for s in t["seasons"])

        if has_points_against:
            row = [t["rank"], t["display_name"], t["wins"], t["losses"],
                   win_pct, t["points_for"], t.get("points_against", ""), t["weeks_played"], seasons_str]
        else:
            row = [t["rank"], t["display_name"], t["wins"], t["losses"],
                   win_pct, t["points_for"], t["weeks_played"], seasons_str]

        ws.append(row)
        fill = ALT_FILL if i % 2 == 0 else None
        style_data_row(ws, row_num, len(headers), fill)
        ws.cell(row=row_num, column=5).number_format = "0.0%"
        ws.cell(row=row_num, column=6).number_format = "#,##0.00"
        if has_points_against:
            ws.cell(row=row_num, column=7).number_format = "#,##0.00"
        for col in (1, 3, 4, 5, len(headers) - 1):
            ws.cell(row=row_num, column=col).alignment = CENTER

    if has_points_against:
        set_col_widths(ws, [6, 22, 7, 7, 8, 13, 15, 13, 20])
    else:
        set_col_widths(ws, [6, 22, 7, 7, 8, 13, 13, 20])



def build_count_standings_sheet(
    wb: Workbook,
    standings: list[dict],
    title: str,
) -> None:
    """Build a count-based alternate standings sheet."""
    ws = wb.create_sheet(title=title[:31])
    headers = ["Rank", "Username", "Count", "Points For", "Weeks Played", "Seasons"]
    ws.append(headers)
    style_header_row(ws, 1, len(headers))
    freeze_top_row(ws)

    for i, t in enumerate(standings):
        row_num     = i + 2
        seasons_str = ", ".join(str(s) for s in t["seasons"])
        ws.append([
            t["rank"],
            t["display_name"],
            t["count"],
            t["points_for"],
            t["weeks_played"],
            seasons_str,
        ])
        fill = ALT_FILL if i % 2 == 0 else None
        style_data_row(ws, row_num, len(headers), fill)
        ws.cell(row=row_num, column=4).number_format = "#,##0.00"
        for col in (1, 3, 5):
            ws.cell(row=row_num, column=col).alignment = CENTER

    set_col_widths(ws, [6, 22, 8, 13, 13, 20])



def _template_title(ws, row, col, text, size=14, num_cols=9):
    """Write a dark-blue title cell merged across num_cols columns."""
    end_col = col + num_cols - 1
    ws.merge_cells(
        start_row=row, start_column=col,
        end_row=row,   end_column=end_col
    )
    cell = ws.cell(row=row, column=col, value=text)
    cell.font      = Font(name="Arial", size=size, bold=True, color="FFFFFF")
    cell.fill      = HEADER_FILL
    cell.alignment = Alignment(horizontal="center", vertical="center")


def _template_header_row(ws, row, start_col, headers):
    for i, h in enumerate(headers):
        cell = ws.cell(row=row, column=start_col + i, value=h)
        cell.font      = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        cell.fill      = HEADER_FILL
        cell.alignment = CENTER if i != 1 else LEFT


def _template_data_row(ws, row, start_col, values, alt):
    fill = ALT_FILL if alt else None
    for i, v in enumerate(values):
        cell = ws.cell(row=row, column=start_col + i, value=v)
        cell.font      = BODY_FONT
        cell.alignment = CENTER if i != 1 else LEFT
        if fill:
            cell.fill = fill


def _template_note(ws, row, col, season, week):
    cell = ws.cell(row=row, column=col,
                   value=f"*Update using regular season games through Week {week} {season}")
    cell.font      = Font(name="Arial", size=11)
    cell.alignment = LEFT


def build_stacked_standings_sheet(
    wb: Workbook,
    ws_name: str,
    standard: list,
    beat_avg: list,
    vs_everyone: list,
    scope: str,
    report_season: int,
    report_week: int,
    highlight_season: Optional[int] = None,
    highlight_week: Optional[int] = None,
) -> None:
    """
    Stacked standings sheet: Standard / Beat the Average / Everyone vs Everyone.
    Matches template: narrow spacer cols A & K, data in B-J, one blank row
    between tables, asterisk note one row below last data row.
    """
    ws = wb.create_sheet(title=ws_name[:31])
    ws.sheet_view.showGridLines = False

    for letter, width in {"A": 2, "B": 6, "C": 22, "D": 7, "E": 7,
                           "F": 8, "G": 13, "H": 15, "I": 14, "J": 36, "K": 2}.items():
        ws.column_dimensions[letter].width = width

    S = 2   # data starts in column B
    r = 1

    for tname, data, has_pa in [
        ("Standard",             standard,    True),
        ("Beat the Average",     beat_avg,    False),
        ("Everyone vs Everyone", vs_everyone, False),
    ]:
        r += 1   # blank spacer row
        # Merged title across B-J (columns 2-10)
        ws.merge_cells(start_row=r, start_column=S, end_row=r, end_column=S + 8)
        _template_title(ws, r, S, tname, size=14)
        ws.cell(row=r, column=S).alignment = Alignment(horizontal="center", vertical="center")
        r += 1

        if has_pa:
            hdrs = ["Rank", "Username", "Wins", "Losses", "Win %",
                    "Points For", "Points Against", "Weeks Played", "Seasons"]
        else:
            hdrs = ["Rank", "Username", "Wins", "Losses", "Win %",
                    "Points For", "", "Weeks Played", "Seasons"]
        _template_header_row(ws, r, S, hdrs)
        r += 1

        for i, t in enumerate(data):
            seasons_str = ", ".join(str(s) for s in t["seasons"])
            total   = t["wins"] + t["losses"]
            wc      = get_column_letter(S + 2)
            lc      = get_column_letter(S + 3)
            win_pct = f"={wc}{r}/({wc}{r}+{lc}{r})" if total > 0 else 0
            pa_val  = t.get("points_against", "") if has_pa else ""
            values  = [t["rank"], t["display_name"], t["wins"], t["losses"],
                       win_pct, t["points_for"], pa_val, t["weeks_played"], seasons_str]
            _template_data_row(ws, r, S, values, i % 2 == 0)
            ws.cell(row=r, column=S + 4).number_format = "0.0%"
            ws.cell(row=r, column=S + 5).number_format = "#,##0.00"
            if has_pa:
                ws.cell(row=r, column=S + 6).number_format = "#,##0.00"
            r += 1

    r += 1
    _template_note(ws, r, S, report_season, report_week)
    ws.print_area  = f"A1:K{r}"
    ws.page_margins = PageMargins(left=0.25, right=0.25, top=0.75, bottom=0.75)


def build_second_high_low_sheet(
    wb: Workbook,
    ws_name: str,
    slw: list,
    shl: list,
    report_season: int,
    report_week: int,
) -> None:
    """
    Two stacked count tables: Second Lowest Winner + Second Highest Loser.
    Matches template: spacers A & E, data in B-D, title size 10.
    """
    ws = wb.create_sheet(title=ws_name[:31])
    ws.sheet_view.showGridLines = False

    for letter, width in {"A": 2, "B": 6, "C": 22, "D": 8, "E": 2}.items():
        ws.column_dimensions[letter].width = width

    S = 2
    r = 1

    for tname, data in [("Second Lowest Winner", slw), ("Second Highest Loser", shl)]:
        r += 1
        # Merged title across B-D (columns 2-4)
        ws.merge_cells(start_row=r, start_column=S, end_row=r, end_column=S + 2)
        _template_title(ws, r, S, tname, size=10)
        ws.cell(row=r, column=S).alignment = Alignment(horizontal="center", vertical="center")
        r += 1
        _template_header_row(ws, r, S, ["Rank", "Username", "Count"])
        r += 1
        for i, t in enumerate(data):
            _template_data_row(ws, r, S, [t["rank"], t["display_name"], t["count"]], i % 2 == 0)
            r += 1

    r += 1
    _template_note(ws, r, S, report_season, report_week)
    ws.print_area  = f"A1:E{r}"
    ws.page_margins = PageMargins(left=0.25, right=0.25, top=0.75, bottom=0.75)


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------

def export_to_excel(
    history: dict,
    season: Optional[int] = None,
    week_type: str = "all",
    include_awards: bool = False,
    top_n: int = 15,
    report_season: Optional[int] = None,
    report_week: Optional[int] = None,
    export_dir: str = EXPORT_DIR,
) -> str:
    """
    Export history, standings, and optionally awards to a formatted Excel workbook.

    Args:
        history:         Full history dict (already cleaned via data_quality if needed)
        season:          Single season year or None for all seasons
        week_type:       "regular", "playoff", or "all"
        include_awards:  If True, add one sheet per award category with top N results
        top_n:           Number of top results per award (default 15)
        report_season:   Season for the asterisk note (defaults to most recent)
        report_week:     Week for the asterisk note (defaults to most recent)
        export_dir:      Folder to save the file in

    Returns:
        Path to the saved Excel file
    """
    # Resolve report season/week for asterisk notes
    if report_season is None or report_week is None:
        seasons = get_seasons_list(history)
        if seasons:
            rs = seasons[-1]
            weeks = sorted(int(w) for w in history.get(str(rs), {}).get("weeks", {}).keys())
            report_season = report_season or rs
            report_week   = report_week   or (weeks[-1] if weeks else 1)
        else:
            report_season = report_season or 0
            report_week   = report_week   or 0
    os.makedirs(export_dir, exist_ok=True)

    # Build filtered weeks list
    # For regular+playoff, fetch all weeks then filter consolation matchups out at row level
    if week_type == "all":
        wt_filter = None
    elif week_type == "regular+playoff":
        wt_filter = None  # fetch all, filter per matchup below
    else:
        wt_filter = week_type
    weeks = get_all_weeks(history, season=season, week_type=wt_filter)

    # Compute standings
    standings = compute_standings(history, season=season, week_type=week_type)

    # Build workbook
    wb = Workbook()
    wb.remove(wb.active)  # remove default blank sheet

    # Standings sheet title
    scope     = f"Season {season}" if season else "All-Time"
    wt_label  = week_type.title()
    standings_title = f"Standings ({scope}, {wt_label})"[:31]

    # Remove old simple standings sheet; stacked sheet replaces it
    beat_avg    = compute_beat_average_standings(history, season=season, week_type=week_type)
    vs_everyone = compute_schedules_against_everyone(history, season=season, week_type=week_type)
    slw         = compute_second_lowest_winner(history, season=season, week_type=week_type)
    shl         = compute_second_highest_loser(history, season=season, week_type=week_type)

    build_stacked_standings_sheet(
        wb,
        ws_name      = f"Standings ({scope}, {wt_label})"[:31],
        standard     = standings,
        beat_avg     = beat_avg,
        vs_everyone  = vs_everyone,
        scope        = scope,
        report_season= report_season,
        report_week  = report_week,
    )

    build_second_high_low_sheet(
        wb,
        ws_name      = f"Second High-Low ({scope})"[:31],
        slw          = slw,
        shl          = shl,
        report_season= report_season,
        report_week  = report_week,
    )

    build_matchups_sheet(wb, weeks)

    # Add a legend sheet
    ws_legend = wb.create_sheet(title="Legend")
    legend_rows = [
        ("Color",             "Meaning"),
        ("Green background",  "True playoff matchup or bye-week team still in winners bracket"),
        ("Orange background", "Eliminated team matchup or eliminated team on bye"),
        ("Blue background",   "Regular season / alternating row"),
        ("— BYE —",          "Team had no opponent this week (bye week entry)"),
    ]
    for i, (label, meaning) in enumerate(legend_rows):
        ws_legend.append([label, meaning])
        if i == 0:
            style_header_row(ws_legend, 1, 2)
        else:
            ws_legend.cell(row=i+1, column=1).font = BOLD_FONT
            ws_legend.cell(row=i+1, column=2).font = BODY_FONT
    ws_legend.column_dimensions["A"].width = 22
    ws_legend.column_dimensions["B"].width = 55

    # Awards sheets (optional)
    if include_awards:
        wt_filter = None if week_type == "all" else week_type
        all_wa    = compute_all_awards(history)
        top       = find_top_n(all_wa, n=top_n, week_type_filter=wt_filter if wt_filter != "regular+playoff" else "regular+playoff")
        scope     = f"Season {season}" if season else "All-Time"
        build_awards_sheets(wb, top, scope=scope, week_type=week_type)

    # Filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    season_tag = str(season) if season else "all"
    filename = f"sleeper_export_{season_tag}_{week_type}_{timestamp}.xlsx"
    filepath = os.path.join(export_dir, filename)

    wb.save(filepath)
    return filepath


# ---------------------------------------------------------------------------
# Main: interactive runner
# ---------------------------------------------------------------------------

def main():
    print("\n--- Sleeper Fantasy Football | Export to Excel ---\n")

    raw_history = load_history()
    if not raw_history:
        print("  No history found. Run history.py first.")
        return

    seasons = get_seasons_list(raw_history)
    rules = load_rules()
    print(f"  Available seasons: {seasons}")

    while True:
        print("\n  Season filter:")
        print("    [1] All seasons")
        for i, s in enumerate(seasons, start=2):
            print(f"    [{i}] {s}")
        print("    [q] Quit")

        choice = input("\n  Select: ").strip().lower()
        if choice == "q":
            print("  Exiting.")
            break

        if choice == "1":
            season_filter = None
        elif choice.isdigit() and 2 <= int(choice) <= len(seasons) + 1:
            season_filter = seasons[int(choice) - 2]
        else:
            print("  Invalid selection.")
            continue

        print("\n  Week type:")
        print("    [1] Regular season only")
        print("    [2] True playoffs only")
        print("    [3] Regular season + true playoffs")
        print("    [4] All weeks (including consolation)")

        wt_choice = input("  Select: ").strip()
        wt_map = {"1": "regular", "2": "playoff", "3": "regular+playoff", "4": "all"}
        if wt_choice not in wt_map:
            print("  Invalid selection.")
            continue
        week_type = wt_map[wt_choice]

        print("\n  Include awards sheets (top 15 per category)?")
        print("    [1] Yes")
        print("    [2] No")
        inc_choice = input("  Select: ").strip()
        include_awards = inc_choice == "1"

        # Always apply rules to raw_history, never to a previously corrected copy
        clean_history, _ = apply_all_rules(raw_history, rules)
        print("\n  Exporting...")
        filepath = export_to_excel(
            clean_history,
            season=season_filter,
            week_type=week_type,
            include_awards=include_awards,
        )
        print(f"  Saved: {filepath}")


if __name__ == "__main__":
    main()
