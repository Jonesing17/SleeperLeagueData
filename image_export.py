"""
image_export.py
---------------
Phase 4 (partial): Sleeper Fantasy Football - Image Export

Generates one PNG image per award category showing the top N results
in a clean, shareable table format suitable for group chats.

Images are saved to data/exports/images/ with a timestamp.

Column layouts:
    Score awards (Highest Score, Lowest Score):
        Rank | Username | Score | Opponent | Opp Score | W/L | Season & Week | Matchup Type
    Loss/Win awards (Highest Loss, Lowest Win):
        Rank | Username | Score | Opponent | Opp Score | Season & Week | Matchup Type
    Margin awards (Biggest Win, Closest Game):
        Rank | Winner | Winner Score | Loser | Loser Score | Margin | Season & Week | Matchup Type

Usage:
    python image_export.py
"""

import os
from datetime import datetime
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from data_quality import load_rules, apply_all_rules
from history import (
    load_history, get_seasons_list,
    compute_standings, compute_beat_average_standings,
    compute_schedules_against_everyone,
    compute_second_lowest_winner, compute_second_highest_loser,
)
from awards import compute_all_awards, find_top_n

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

IMAGE_DIR    = os.path.join(os.path.dirname(__file__), "data", "exports", "images")
FONT_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONT_BOLD    = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

C_BG          = (255, 255, 255)       # white background
C_HEADER_BG   = (31,  78,  121)       # dark blue header
C_HEADER_TEXT = (255, 255, 255)       # white header text
C_TITLE_TEXT  = (31,  78,  121)       # dark blue title
C_GOLD        = (255, 215,   0)       # rank 1
C_SILVER      = (192, 192, 192)       # rank 2
C_BRONZE      = (205, 127,  50)       # rank 3
C_ALT_ROW     = (214, 228, 240)       # alternating row tint
C_ROW_TEXT    = ( 30,  30,  30)       # body text
C_NEW_WEEK    = (255, 255, 153)       # yellow highlight for new week
C_BORDER      = (180, 180, 180)       # subtle cell border
C_DESC_TEXT   = (100, 100, 100)       # description subtitle

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

PADDING       = 24   # outer padding
TITLE_H       = 44   # title row height
DESC_H        = 28   # description row height
HEADER_H      = 32   # column header row height
ROW_H         = 30   # data row height
CORNER_RADIUS = 12   # rounded corners on the card

# ---------------------------------------------------------------------------
# Column definitions per award type
# ---------------------------------------------------------------------------

def get_columns(award_name: str) -> list[dict]:
    """
    Return column definitions for a given award.
    Each dict has: key, label, width, align ("l" or "c")
    """
    season_week = {"key": "season_week", "label": "Season & Week", "width": 110, "align": "c"}
    matchup_type = {"key": "matchup_type", "label": "Type",         "width": 90,  "align": "c"}

    if award_name in ("Biggest Win", "Closest Game"):
        return [
            {"key": "rank",         "label": "#",             "width": 36,  "align": "c"},
            {"key": "winner",       "label": "Winner",        "width": 150, "align": "l"},
            {"key": "winner_score", "label": "W Score",       "width": 80,  "align": "c"},
            {"key": "opponent",     "label": "Loser",         "width": 150, "align": "l"},
            {"key": "loser_score",  "label": "L Score",       "width": 80,  "align": "c"},
            {"key": "value",        "label": "Margin",        "width": 80,  "align": "c"},
            season_week,
            matchup_type,
        ]
    elif award_name in ("Highest Score", "Lowest Score"):
        return [
            {"key": "rank",           "label": "#",         "width": 36,  "align": "c"},
            {"key": "winner",         "label": "Username",  "width": 150, "align": "l"},
            {"key": "value",          "label": "Score",     "width": 80,  "align": "c"},
            {"key": "opponent",       "label": "Opponent",  "width": 150, "align": "l"},
            {"key": "opponent_score", "label": "Opp Score", "width": 80,  "align": "c"},
            {"key": "result",         "label": "W/L",       "width": 46,  "align": "c"},
            season_week,
            matchup_type,
        ]
    else:
        # Highest Loss, Lowest Win
        return [
            {"key": "rank",           "label": "#",         "width": 36,  "align": "c"},
            {"key": "winner",         "label": "Username",  "width": 150, "align": "l"},
            {"key": "value",          "label": "Score",     "width": 80,  "align": "c"},
            {"key": "opponent",       "label": "Opponent",  "width": 150, "align": "l"},
            {"key": "opponent_score", "label": "Opp Score", "width": 80,  "align": "c"},
            season_week,
            matchup_type,
        ]


def entry_to_row(entry, rank: int) -> dict:
    """Convert an AwardEntry to a flat dict for rendering."""
    return {
        "rank":           str(rank),
        "winner":         entry.winner,
        "value":          f"{entry.value:.2f}",
        "opponent":       entry.opponent or "—",
        "opponent_score": f"{entry.opponent_score:.2f}" if entry.opponent_score is not None else "—",
        "result":         entry.result or "—",
        "winner_score":   f"{entry.winner_score:.2f}" if entry.winner_score is not None else "—",
        "loser_score":    f"{entry.loser_score:.2f}"  if entry.loser_score  is not None else "—",
        "season_week":    f"{entry.season} Wk{entry.week}",
        "matchup_type":   entry.matchup_type.title(),
    }


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def load_fonts(size_body: int = 13, size_header: int = 13, size_title: int = 18):
    try:
        f_regular = ImageFont.truetype(FONT_REGULAR, size_body)
        f_bold    = ImageFont.truetype(FONT_BOLD,    size_header)
        f_title   = ImageFont.truetype(FONT_BOLD,    size_title)
        f_desc    = ImageFont.truetype(FONT_REGULAR, 11)
    except Exception:
        f_regular = ImageFont.load_default()
        f_bold    = f_regular
        f_title   = f_regular
        f_desc    = f_regular
    return f_regular, f_bold, f_title, f_desc


def draw_rounded_rect(draw, xy, radius, fill, outline=None):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill, outline=outline)


def draw_text_in_cell(draw, text, x, y, w, h, font, color, align="c"):
    bbox = font.getbbox(text)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]
    if align == "c":
        tx = x + (w - tw) // 2
    else:
        tx = x + 8
    ty = y + (h - th) // 2
    draw.text((tx, ty), text, font=font, fill=color)


# ---------------------------------------------------------------------------
# Main image generator
# ---------------------------------------------------------------------------

def generate_award_image(
    award_name: str,
    entries: list,
    season_filter: Optional[int],
    week_type: str,
    highlight_season: Optional[int] = None,
    highlight_week: Optional[int] = None,
    n: int = 10,
) -> Image.Image:
    """
    Generate a PIL Image for a single award table.

    Args:
        award_name:       e.g. "Highest Score"
        entries:          List of AwardEntry objects (already sorted, top N)
        season_filter:    Season year or None for all-time
        week_type:        Filter label for subtitle
        highlight_season: Season of the new week to highlight in yellow
        highlight_week:   Week number to highlight in yellow
        n:                Max rows to show

    Returns:
        PIL Image object
    """
    entries  = entries[:n]
    cols     = get_columns(award_name)
    f_reg, f_bold, f_title, f_desc = load_fonts()

    scope    = f"Season {season_filter}" if season_filter else "All-Time"
    subtitle = f"{scope}  •  {week_type.replace('+', ' + ').title()}"

    total_w  = PADDING * 2 + sum(c["width"] for c in cols)
    total_h  = (PADDING * 2 + TITLE_H + DESC_H + HEADER_H
                + ROW_H * len(entries) + 8)

    img  = Image.new("RGB", (total_w, total_h), C_BG)
    draw = ImageDraw.Draw(img)

    # Outer card background
    draw_rounded_rect(draw, [0, 0, total_w - 1, total_h - 1],
                      CORNER_RADIUS, fill=C_BG, outline=C_BORDER)

    y = PADDING

    # Title
    draw.text((PADDING, y), award_name, font=f_title, fill=C_TITLE_TEXT)
    y += TITLE_H

    # Subtitle / description
    draw.text((PADDING, y), subtitle, font=f_desc, fill=C_DESC_TEXT)
    y += DESC_H

    # Column headers
    x = PADDING
    draw_rounded_rect(draw, [PADDING, y, total_w - PADDING, y + HEADER_H],
                      4, fill=C_HEADER_BG)
    for col in cols:
        draw_text_in_cell(draw, col["label"], x, y, col["width"],
                          HEADER_H, f_bold, C_HEADER_TEXT, align="c")
        x += col["width"]
    y += HEADER_H

    # Data rows
    for i, entry in enumerate(entries):
        rank    = i + 1
        row     = entry_to_row(entry, rank)
        is_new  = (
            highlight_season is not None
            and highlight_week is not None
            and entry.season == highlight_season
            and entry.week   == highlight_week
        )

        # Row background
        if is_new:
            row_bg = C_NEW_WEEK
        elif rank == 1:
            row_bg = C_GOLD
        elif rank == 2:
            row_bg = C_SILVER
        elif rank == 3:
            row_bg = C_BRONZE
        else:
            row_bg = C_ALT_ROW if i % 2 == 0 else C_BG

        draw.rectangle([PADDING, y, total_w - PADDING, y + ROW_H], fill=row_bg)

        # Subtle bottom border
        draw.line([PADDING, y + ROW_H, total_w - PADDING, y + ROW_H],
                  fill=C_BORDER, width=1)

        x    = PADDING
        font = f_bold if rank <= 3 else f_reg
        for col in cols:
            text = row.get(col["key"], "—")
            draw_text_in_cell(draw, text, x, y, col["width"],
                              ROW_H, font, C_ROW_TEXT, align=col["align"])
            x += col["width"]

        y += ROW_H

    return img


# ---------------------------------------------------------------------------
# Save all award images
# ---------------------------------------------------------------------------

def save_award_images(
    top_n_data: dict,
    season_filter: Optional[int],
    week_type: str,
    highlight_season: Optional[int] = None,
    highlight_week: Optional[int] = None,
    n: int = 10,
    image_dir: str = IMAGE_DIR,
) -> list[str]:
    """
    Generate and save one PNG per award. Returns list of saved file paths.
    """
    os.makedirs(image_dir, exist_ok=True)
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    season_tag  = str(season_filter) if season_filter else "all"
    saved_paths = []

    for award_name, entries in top_n_data.items():
        if not entries:
            continue

        img  = generate_award_image(
            award_name      = award_name,
            entries         = entries,
            season_filter   = season_filter,
            week_type       = week_type,
            highlight_season= highlight_season,
            highlight_week  = highlight_week,
            n               = n,
        )

        safe_name = award_name.lower().replace(" ", "_")
        filename  = f"{safe_name}_{season_tag}_{week_type}_{timestamp}.png"
        filepath  = os.path.join(image_dir, filename)
        img.save(filepath, "PNG")
        saved_paths.append(filepath)
        print(f"  Saved: {filepath}")

    return saved_paths



# ---------------------------------------------------------------------------
# Standings image generators
# ---------------------------------------------------------------------------

STANDINGS_COLS_WIDE = [
    {"key": "rank",        "label": "#",       "width": 36,  "align": "c"},
    {"key": "display_name","label": "Username", "width": 150, "align": "l"},
    {"key": "wins",        "label": "W",        "width": 50,  "align": "c"},
    {"key": "losses",      "label": "L",        "width": 50,  "align": "c"},
    {"key": "win_pct",     "label": "Win %",    "width": 65,  "align": "c"},
]

STANDINGS_COLS_COUNT = [
    {"key": "rank",        "label": "#",       "width": 36,  "align": "c"},
    {"key": "display_name","label": "Username", "width": 150, "align": "l"},
    {"key": "count",       "label": "Count",    "width": 70,  "align": "c"},
]


def generate_standings_image(
    title: str,
    subtitle: str,
    rows: list[dict],
    columns: list[dict],
    highlight_note: Optional[str] = None,
) -> Image.Image:
    """
    Generate a standings PNG image.

    Args:
        title:     Table title (e.g. "Standard Standings")
        subtitle:  Scope/filter label
        rows:      List of team dicts
        columns:   Column definition list
        highlight_note: Optional asterisk note text
    """
    f_reg, f_bold, f_title, f_desc = load_fonts()

    total_w = PADDING * 2 + sum(c["width"] for c in columns)
    n_rows  = len(rows)
    note_h  = 24 if highlight_note else 0
    total_h = PADDING * 2 + TITLE_H + DESC_H + HEADER_H + ROW_H * n_rows + note_h + 8

    img  = Image.new("RGB", (total_w, total_h), C_BG)
    draw = ImageDraw.Draw(img)

    draw_rounded_rect(draw, [0, 0, total_w - 1, total_h - 1],
                      CORNER_RADIUS, fill=C_BG, outline=C_BORDER)

    y = PADDING

    # Title
    draw.text((PADDING, y), title, font=f_title, fill=C_TITLE_TEXT)
    y += TITLE_H

    # Subtitle
    draw.text((PADDING, y), subtitle, font=f_desc, fill=C_DESC_TEXT)
    y += DESC_H

    # Header
    x = PADDING
    draw_rounded_rect(draw, [PADDING, y, total_w - PADDING, y + HEADER_H], 4, fill=C_HEADER_BG)
    for col in columns:
        draw_text_in_cell(draw, col["label"], x, y, col["width"], HEADER_H,
                          f_bold, C_HEADER_TEXT, align="c")
        x += col["width"]
    y += HEADER_H

    # Data rows
    for i, row in enumerate(rows):
        rank   = row.get("rank", i + 1)
        if rank == 1:
            row_bg, font = C_GOLD,   f_bold
        elif rank == 2:
            row_bg, font = C_SILVER, f_bold
        elif rank == 3:
            row_bg, font = C_BRONZE, f_bold
        else:
            row_bg = C_ALT_ROW if i % 2 == 0 else C_BG
            font   = f_reg

        draw.rectangle([PADDING, y, total_w - PADDING, y + ROW_H], fill=row_bg)
        draw.line([PADDING, y + ROW_H, total_w - PADDING, y + ROW_H],
                  fill=C_BORDER, width=1)

        x = PADDING
        for col in columns:
            val = row.get(col["key"], "")
            if col["key"] == "win_pct":
                total = row.get("wins", 0) + row.get("losses", 0)
                val   = f"{row['wins'] / total:.1%}" if total > 0 else "—"
            elif isinstance(val, float):
                val = f"{val:.2f}"
            else:
                val = str(val)
            draw_text_in_cell(draw, val, x, y, col["width"], ROW_H,
                              font, C_ROW_TEXT, align=col["align"])
            x += col["width"]
        y += ROW_H

    # Asterisk note
    if highlight_note:
        draw.text((PADDING, y + 6), f"*{highlight_note}", font=f_desc, fill=C_DESC_TEXT)

    return img


def stack_images_vertically(images: list, gap: int = 16) -> Image.Image:
    """
    Stack a list of PIL images vertically with a white gap between them.
    All images are padded to the same width.
    """
    max_w  = max(img.width for img in images)
    total_h = sum(img.height for img in images) + gap * (len(images) - 1)
    result  = Image.new("RGB", (max_w, total_h), C_BG)
    y = 0
    for img in images:
        # Centre narrower images
        x = (max_w - img.width) // 2
        result.paste(img, (x, y))
        y += img.height + gap
    return result


def save_standings_images(
    clean_history: dict,
    week_type: str,
    report_season: int,
    report_week: int,
    image_dir: str = IMAGE_DIR,
) -> list[str]:
    """
    Generate and save two combined standings images:
      1. Three stacked standings (Standard / Beat the Average / Everyone vs Everyone)
      2. Second Lowest Winner + Second Highest Loser stacked
    """
    os.makedirs(image_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    note_text = f"Regular season games through Week {report_week} {report_season}"
    subtitle  = f"All-Time  •  {week_type.replace('+', ' + ').title()}"
    saved     = []

    # Image 1: Three standings stacked
    wide_tables = [
        ("Standard Standings",   compute_standings(clean_history, week_type=week_type)),
        ("Beat the Average",     compute_beat_average_standings(clean_history, week_type=week_type)),
        ("Everyone vs Everyone", compute_schedules_against_everyone(clean_history, week_type=week_type)),
    ]
    wide_imgs = [
        generate_standings_image(title, subtitle, data, STANDINGS_COLS_WIDE,
                                 note_text if i == len(wide_tables) - 1 else None)
        for i, (title, data) in enumerate(wide_tables)
    ]
    combined_wide = stack_images_vertically(wide_imgs)
    path1 = os.path.join(image_dir, f"standings_combined_{timestamp}.png")
    combined_wide.save(path1, "PNG")
    saved.append(path1)
    print(f"  Saved: {path1}")

    # Image 2: Second Lowest Winner + Second Highest Loser stacked
    count_tables = [
        ("Second Lowest Winner", compute_second_lowest_winner(clean_history, week_type=week_type)),
        ("Second Highest Loser", compute_second_highest_loser(clean_history, week_type=week_type)),
    ]
    count_imgs = [
        generate_standings_image(title, subtitle, data, STANDINGS_COLS_COUNT,
                                 note_text if i == len(count_tables) - 1 else None)
        for i, (title, data) in enumerate(count_tables)
    ]
    combined_count = stack_images_vertically(count_imgs)
    path2 = os.path.join(image_dir, f"second_high_low_combined_{timestamp}.png")
    combined_count.save(path2, "PNG")
    saved.append(path2)
    print(f"  Saved: {path2}")

    return saved


# ---------------------------------------------------------------------------
# Main: interactive runner
# ---------------------------------------------------------------------------

def main():
    print("\n--- Sleeper Fantasy Football | Image Export ---\n")

    raw_history = load_history()
    if not raw_history:
        print("  No history found. Run history.py first.")
        return

    rules         = load_rules()
    clean_history, _ = apply_all_rules(raw_history, rules)
    seasons       = get_seasons_list(clean_history)
    print(f"  Available seasons: {seasons}")

    # Season filter
    print("\n  Season filter:")
    print("    [1] All seasons")
    for i, s in enumerate(seasons, start=2):
        print(f"    [{i}] {s}")
    choice = input("\n  Select: ").strip()
    if choice == "1":
        season_filter = None
    elif choice.isdigit() and 2 <= int(choice) <= len(seasons) + 1:
        season_filter = seasons[int(choice) - 2]
    else:
        print("  Invalid selection.")
        return

    # Week type filter
    print("\n  Week type:")
    print("    [1] Regular season only")
    print("    [2] True playoffs only")
    print("    [3] Regular season + true playoffs")
    print("    [4] All weeks")
    wt_choice = input("  Select [4]: ").strip()
    wt_map    = {"1": "regular", "2": "playoff", "3": "regular+playoff", "4": "all"}
    week_type = wt_map.get(wt_choice, "all")

    # Number of rows
    n_input = input("\n  Rows per award [10]: ").strip()
    n       = int(n_input) if n_input.isdigit() else 10

    # Optional: highlight a specific week
    print("\n  Highlight a specific week? (leave blank to skip)")
    hl_season_input = input("  Highlight season: ").strip()
    hl_week_input   = input("  Highlight week: ").strip()
    highlight_season = int(hl_season_input) if hl_season_input.isdigit() else None
    highlight_week   = int(hl_week_input)   if hl_week_input.isdigit()   else None

    # Compute and export
    print("\n  Computing awards...")
    wt_filter = None if week_type == "all" else week_type
    all_wa    = compute_all_awards(clean_history)
    top       = find_top_n(all_wa, n=n, week_type_filter=wt_filter)

    print("  Generating images...")
    paths = save_award_images(
        top_n_data       = top,
        season_filter    = season_filter,
        week_type        = week_type,
        highlight_season = highlight_season,
        highlight_week   = highlight_week,
        n                = n,
    )

    print(f"\n  {len(paths)} image(s) saved to data/exports/images/")


if __name__ == "__main__":
    main()
