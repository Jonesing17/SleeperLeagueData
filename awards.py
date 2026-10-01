"""
awards.py
---------
Phase 2: Sleeper Fantasy Football - Awards Engine

Calculates weekly awards from parsed matchup results and compares
them against all-time league history records.

Awards tracked:
    - Highest team score
    - Lowest team score
    - Biggest win margin
    - Closest game (smallest margin)
    - Highest losing score (unlucky award)

Each award is tagged with week_type: "regular" | "playoff"
so results can be filtered by season type at display time.
The playoff start week is retrieved dynamically from league settings
via sleeper_api.get_playoff_start_week() so it correctly handles
seasons with non-standard schedules (e.g. the 2020 17-week NFL season).
"""

from dataclasses import dataclass, asdict
from typing import Optional

from data_quality import load_rules, apply_all_rules
from history import load_history, get_all_weeks, get_seasons_list


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AwardEntry:
    """A single award result for a given week."""
    award: str               # e.g. "Highest Score"
    winner: str              # display_name of the recipient
    value: float             # the numeric value (points or margin)
    opponent: Optional[str]  # opponent display_name, if applicable
    season: int
    week: int
    week_type: str           # "regular" or "playoff"
    matchup_type: str = "regular"      # "regular", "playoff", "eliminated", "bye"
    result: str = ""                   # "Win", "Loss", or "" for margin-based awards
    opponent_score: Optional[float] = None  # opponent's score, if applicable
    winner_score: Optional[float] = None    # team 1 score (for margin awards)
    loser_score: Optional[float] = None     # team 2 score (for margin awards)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "AwardEntry":
        return AwardEntry(**d)


@dataclass
class WeeklyAwards:
    """All awards for a single week, plus metadata."""
    season: int
    week: int
    week_type: str           # "regular" or "playoff"
    highest_score: AwardEntry
    lowest_score: AwardEntry
    biggest_win: AwardEntry
    closest_game: AwardEntry
    highest_loss: Optional[AwardEntry]   # Highest score that still lost
    lowest_win: Optional[AwardEntry]     # Lowest score that still won
    score_entries: list = None           # All individual team scores this week

    def to_dict(self) -> dict:
        return {
            "season": self.season,
            "week": self.week,
            "week_type": self.week_type,
            "highest_score": self.highest_score.to_dict(),
            "lowest_score": self.lowest_score.to_dict(),
            "biggest_win": self.biggest_win.to_dict(),
            "closest_game": self.closest_game.to_dict(),
            "highest_loss": self.highest_loss.to_dict() if self.highest_loss else None,
            "lowest_win": self.lowest_win.to_dict() if self.lowest_win else None,
        }

    @staticmethod
    def from_dict(d: dict) -> "WeeklyAwards":
        return WeeklyAwards(
            season=d["season"],
            week=d["week"],
            week_type=d["week_type"],
            highest_score=AwardEntry.from_dict(d["highest_score"]),
            lowest_score=AwardEntry.from_dict(d["lowest_score"]),
            biggest_win=AwardEntry.from_dict(d["biggest_win"]),
            closest_game=AwardEntry.from_dict(d["closest_game"]),
            highest_loss=AwardEntry.from_dict(d["highest_loss"]) if d.get("highest_loss") else None,
            lowest_win=AwardEntry.from_dict(d["lowest_win"]) if d.get("lowest_win") else None,
        )

    def all_awards(self) -> list[AwardEntry]:
        """Return all awards, excluding any that are None (e.g. highest_loss on a bye-heavy week)."""
        return [
            a for a in [
                self.highest_score,
                self.lowest_score,
                self.biggest_win,
                self.closest_game,
                self.highest_loss,
                self.lowest_win,
            ] if a is not None
        ]

    def all_score_entries(self) -> list[AwardEntry]:
        """
        Return one AwardEntry per team per week covering all score-based awards.
        Every team gets an entry in Highest Score and Lowest Score.
        Winners get a Lowest Win entry, losers get a Highest Loss entry.
        This allows both teams from the same high-scoring matchup to appear
        independently in the all-time Highest Score rankings.
        """
        return self.score_entries or []


# ---------------------------------------------------------------------------
# Week type helper
# ---------------------------------------------------------------------------

def get_week_type(week: int, playoff_start_week: int) -> str:
    """Return 'playoff' if week >= playoff_start_week, else 'regular'."""
    return "playoff" if week >= playoff_start_week else "regular"


# ---------------------------------------------------------------------------
# Core awards computation
# ---------------------------------------------------------------------------

def compute_weekly_awards(
    parsed: dict,
    season: int,
    week: int,
    playoff_start_week: int,
) -> WeeklyAwards:
    """
    Compute all awards for a single week from parsed matchup results.

    Args:
        parsed: Output of sleeper_api.parse_matchups() -- dict with
                "matchups" (head-to-head) and "byes" (bye week teams) keys.
                Bye teams are included in score-based awards but excluded
                from margin-based awards (biggest win, closest game).
        season: NFL season year (e.g. 2024)
        week: Week number (e.g. 7)
        playoff_start_week: Retrieved via sleeper_api.get_playoff_start_week()

    Returns:
        WeeklyAwards dataclass with all five awards populated
    """
    matchup_results = parsed["matchups"]
    bye_teams = parsed.get("byes", [])

    if not matchup_results and not bye_teams:
        raise ValueError("No matchup results provided.")

    week_type = get_week_type(week, playoff_start_week)

    # Flatten all individual team scores (including bye teams for score awards)
    all_scores = []
    for m in matchup_results:
        matchup_type = m.get("playoff_status", week_type)
        all_scores.append({
            "display_name": m["home"]["display_name"],
            "points": m["home"]["points"],
            "opponent": m["away"]["display_name"],
            "opponent_score": m["away"]["points"],
            "won": True,
            "matchup_type": matchup_type,
        })
        all_scores.append({
            "display_name": m["away"]["display_name"],
            "points": m["away"]["points"],
            "opponent": m["home"]["display_name"],
            "opponent_score": m["home"]["points"],
            "won": False,
            "matchup_type": matchup_type,
        })

    # Bye teams included in score ranking but marked as no result (won=None)
    for b in bye_teams:
        all_scores.append({
            "display_name": b["display_name"],
            "points": b["points"],
            "opponent": None,
            "opponent_score": None,
            "won": None,
            "matchup_type": b.get("playoff_status", "bye"),
        })

    # --- Highest Score ---
    # Picks the single highest scorer regardless of result.
    # result is derived from won field so a high-scoring loss shows correctly.
    best = max(all_scores, key=lambda x: x["points"])
    highest_score = AwardEntry(
        award="Highest Score",
        winner=best["display_name"],
        value=best["points"],
        opponent=best["opponent"],
        season=season,
        week=week,
        week_type=week_type,
        matchup_type=best.get("matchup_type", week_type),
        result="Win" if best["won"] else ("Loss" if best["won"] is False else ""),
        opponent_score=best.get("opponent_score"),
    )

    # --- Lowest Score ---
    worst = min(all_scores, key=lambda x: x["points"])
    lowest_score = AwardEntry(
        award="Lowest Score",
        winner=worst["display_name"],
        value=worst["points"],
        opponent=worst["opponent"],
        season=season,
        week=week,
        week_type=week_type,
        matchup_type=worst.get("matchup_type", week_type),
        result="Win" if worst["won"] else ("Loss" if worst["won"] is False else ""),
        opponent_score=worst.get("opponent_score"),
    )

    # --- Biggest Win (largest margin) ---
    big_win_matchup = max(matchup_results, key=lambda x: x["margin"])
    biggest_win = AwardEntry(
        award="Biggest Win",
        winner=big_win_matchup["home"]["display_name"],
        value=big_win_matchup["margin"],
        opponent=big_win_matchup["away"]["display_name"],
        season=season,
        week=week,
        week_type=week_type,
        matchup_type=big_win_matchup.get("playoff_status", week_type),
        winner_score=big_win_matchup["home"]["points"],
        loser_score=big_win_matchup["away"]["points"],
    )

    # --- Closest Game (smallest margin) ---
    close_matchup = min(matchup_results, key=lambda x: x["margin"])
    closest_game = AwardEntry(
        award="Closest Game",
        winner=close_matchup["home"]["display_name"],
        value=close_matchup["margin"],
        opponent=close_matchup["away"]["display_name"],
        season=season,
        week=week,
        week_type=week_type,
        matchup_type=close_matchup.get("playoff_status", week_type),
        winner_score=close_matchup["home"]["points"],
        loser_score=close_matchup["away"]["points"],
    )

    # --- Highest Losing Score (unlucky: highest score that still lost) ---
    # Excludes bye teams (won=None) since they have no opponent to lose to.
    # Guard against edge case where no losers exist (e.g. all non-bye teams won,
    # which can't happen in practice but keeps the code safe).
    losers = [s for s in all_scores if s["won"] is False]
    if losers:
        unlucky = max(losers, key=lambda x: x["points"])
        highest_loss = AwardEntry(
            award="Highest Loss",
            winner=unlucky["display_name"],
            value=unlucky["points"],
            opponent=unlucky["opponent"],
            season=season,
            week=week,
            week_type=week_type,
            matchup_type=unlucky.get("matchup_type", week_type),
            result="Loss",
            opponent_score=unlucky.get("opponent_score"),
        )
    else:
        highest_loss = None

    # --- Lowest Winning Score (lucky: lowest score that still won) ---
    winners = [s for s in all_scores if s["won"] is True]
    if winners:
        lucky = min(winners, key=lambda x: x["points"])
        lowest_win = AwardEntry(
            award="Lowest Win",
            winner=lucky["display_name"],
            value=lucky["points"],
            opponent=lucky["opponent"],
            season=season,
            week=week,
            week_type=week_type,
            matchup_type=lucky.get("matchup_type", week_type),
            result="Win",
            opponent_score=lucky.get("opponent_score"),
        )
    else:
        lowest_win = None

    # Build individual score entries for every team this week so
    # find_top_n can rank all teams independently rather than just
    # the single weekly award winner.
    score_entries = []
    for s in all_scores:
        if s["won"] is None:
            # Bye team — only appears in Highest/Lowest Score, not win/loss awards
            awards_for_team = ["Highest Score", "Lowest Score"]
            result = ""
        elif s["won"]:
            awards_for_team = ["Highest Score", "Lowest Score", "Lowest Win"]
            result = "Win"
        else:
            awards_for_team = ["Highest Score", "Lowest Score", "Highest Loss"]
            result = "Loss"

        for award_name in awards_for_team:
            score_entries.append(AwardEntry(
                award=award_name,
                winner=s["display_name"],
                value=s["points"],
                opponent=s.get("opponent"),
                season=season,
                week=week,
                week_type=week_type,
                matchup_type=s.get("matchup_type", week_type),
                result=result,
                opponent_score=s.get("opponent_score"),
            ))

    return WeeklyAwards(
        season=season,
        week=week,
        week_type=week_type,
        highest_score=highest_score,
        lowest_score=lowest_score,
        biggest_win=biggest_win,
        closest_game=closest_game,
        highest_loss=highest_loss,
        lowest_win=lowest_win,
        score_entries=score_entries,
    )


# ---------------------------------------------------------------------------
# All-time record comparison
# ---------------------------------------------------------------------------

AWARD_SORT = {
    "Highest Score": ("value", True),   # higher is better
    "Lowest Score":  ("value", False),  # lower is "worse" / more notable
    "Biggest Win":   ("value", True),
    "Closest Game":  ("value", False),  # smaller margin = more notable
    "Highest Loss":  ("value", True),   # higher losing score = more unlucky
    "Lowest Win":    ("value", False),  # lower winning score = luckier
}



def _apply_week_filter(awards: list, week_type_filter: Optional[str]) -> list:
    """
    Filter a list of WeeklyAwards by week type.
    "regular+playoff" includes both regular and playoff weeks
    but consolation matchups are excluded at the entry level.
    """
    if not week_type_filter or week_type_filter == "regular+playoff":
        return awards
    return [w for w in awards if w.week_type == week_type_filter]


def find_all_time_records(
    history: list[WeeklyAwards],
    week_type_filter: Optional[str] = None,
) -> dict[str, AwardEntry]:
    """
    Scan all stored WeeklyAwards to find the all-time record holder for each award.

    Args:
        history: List of WeeklyAwards from all past weeks
        week_type_filter: "regular", "playoff", or None (all weeks)

    Returns:
        Dict mapping award name -> best-ever AwardEntry
    """
    history = _apply_week_filter(history, week_type_filter)

    records: dict[str, AwardEntry] = {}

    for week_awards in history:
        for entry in week_awards.all_awards():
            # Exclude consolation matchups when filter is "regular+playoff"
            if week_type_filter == "regular+playoff" and entry.matchup_type == "eliminated":
                continue
            award = entry.award
            _, higher_is_better = AWARD_SORT[award]

            if award not in records:
                records[award] = entry
            else:
                current_best = records[award].value
                if higher_is_better and entry.value > current_best:
                    records[award] = entry
                elif not higher_is_better and entry.value < current_best:
                    records[award] = entry

    return records


def is_all_time_record(
    entry: AwardEntry,
    records: dict[str, AwardEntry],
) -> bool:
    """Return True if this AwardEntry matches the all-time record for its award."""
    record = records.get(entry.award)
    if record is None:
        return False
    return entry.value == record.value and entry.winner == record.winner


# ---------------------------------------------------------------------------
# Pretty printer
# ---------------------------------------------------------------------------

def print_weekly_awards(
    weekly_awards: WeeklyAwards,
    all_time_records: Optional[dict[str, AwardEntry]] = None,
):
    """Print a formatted summary of weekly awards to the console."""
    tag = f"[{weekly_awards.week_type.upper()}]"
    print()
    print("=" * 60)
    print(
        f"  AWARDS  |  Season {weekly_awards.season}  "
        f"|  Week {weekly_awards.week}  {tag}"
    )
    print("=" * 60)

    for entry in weekly_awards.all_awards():
        record_flag = ""
        if all_time_records and is_all_time_record(entry, all_time_records):
            record_flag = "  *** ALL-TIME RECORD ***"

        if entry.award in ("Biggest Win", "Closest Game"):
            print(
                f"  {entry.award:<20} {entry.winner} by {entry.value:.2f} pts"
                f" (vs {entry.opponent}){record_flag}"
            )
        else:
            print(
                f"  {entry.award:<20} {entry.winner} — {entry.value:.2f} pts"
                f" (vs {entry.opponent}){record_flag}"
            )

    print("=" * 60)
    print()



def find_top_n(
    all_weekly_awards: list["WeeklyAwards"],
    n: int = 15,
    week_type_filter: Optional[str] = None,
) -> dict[str, list["AwardEntry"]]:
    """
    Return the top N entries for each award category across all history.

    For awards where higher is better (Highest Score, Biggest Win, Highest Loss),
    returns the N highest values. For awards where lower is more notable
    (Lowest Score, Closest Game), returns the N lowest values.

    Args:
        all_weekly_awards:  Output of compute_all_awards()
        n:                  Number of results to return per award (default 15)
        week_type_filter:   "regular", "playoff", or None (all weeks)

    Returns:
        Dict mapping award name -> sorted list of up to N AwardEntry objects
    """
    all_weekly_awards = _apply_week_filter(all_weekly_awards, week_type_filter)

    # Collect all entries per award type.
    # For score-based awards (Highest Score, Lowest Score, Highest Loss, Lowest Win)
    # we want ALL individual team scores across all matchups — not just the weekly
    # winner of that award — so both teams from a high-scoring matchup can
    # independently appear in the all-time top 15.
    # Margin-based awards (Biggest Win, Closest Game) keep one entry per week
    # since the matchup itself is the unit of measurement.
    score_awards  = {"Highest Score", "Lowest Score", "Highest Loss", "Lowest Win"}
    margin_awards = {"Biggest Win", "Closest Game"}
    buckets: dict[str, list[AwardEntry]] = {name: [] for name in AWARD_SORT}

    for week_awards in all_weekly_awards:
        psw = week_awards.week
        season_str = str(week_awards.season)

        # For score awards, build individual entries from raw matchup data
        # stored on the week_awards object so we capture every team's score
        for entry in week_awards.all_awards():
            if entry.award in margin_awards:
                if week_type_filter == "regular+playoff" and entry.matchup_type == "eliminated":
                    continue
                buckets[entry.award].append(entry)

        # Reconstruct individual score entries from the weekly award data
        # by pulling all teams' scores from highest_score context
        # We do this by storing all scores on WeeklyAwards directly
        for score_entry in week_awards.all_score_entries():
            if week_type_filter == "regular+playoff" and score_entry.matchup_type == "eliminated":
                continue
            if score_entry.award in score_awards:
                buckets[score_entry.award].append(score_entry)

    # Sort each bucket and take top N
    top_n: dict[str, list[AwardEntry]] = {}
    for award_name, entries in buckets.items():
        _, higher_is_better = AWARD_SORT[award_name]
        sorted_entries = sorted(entries, key=lambda e: e.value, reverse=higher_is_better)
        top_n[award_name] = sorted_entries[:n]

    return top_n

# ---------------------------------------------------------------------------
# Main: interactive runner
# ---------------------------------------------------------------------------

def compute_all_awards(clean_history: dict) -> list[WeeklyAwards]:
    """
    Compute WeeklyAwards for every week stored in clean_history.
    Returns a flat list of WeeklyAwards sorted by season and week.
    """
    all_awards = []
    for season_key, season_data in sorted(clean_history.items()):
        psw = season_data.get("playoff_start_week", 15)
        for week_key, week_data in sorted(season_data.get("weeks", {}).items(), key=lambda x: int(x[0])):
            try:
                wa = compute_weekly_awards(
                    parsed=week_data,
                    season=int(season_key),
                    week=int(week_key),
                    playoff_start_week=psw,
                )
                all_awards.append(wa)
            except ValueError:
                pass  # skip empty weeks
    return all_awards


if __name__ == "__main__":
    print("\n--- Sleeper Fantasy Football | Awards Engine ---\n")

    raw_history = load_history()
    if not raw_history:
        print("  No history found. Run history.py first.")
        exit()

    # Apply quality rules to raw history — never modifies history.json
    rules = load_rules()
    clean_history, _ = apply_all_rules(raw_history, rules)

    seasons = get_seasons_list(clean_history)
    print(f"  Available seasons: {seasons}")

    while True:
        print("\n  What would you like to view?")
        print("    [1] Awards for a specific week")
        print("    [2] Awards for a full season")
        print("    [3] All-time records")
        print("    [q] Quit")

        choice = input("\n  Select: ").strip().lower()

        if choice == "q":
            print("  Exiting.")
            break

        print("  Week type: [1] Regular season  [2] Playoffs  [3] Regular + True Playoffs  [4] All")
        wt_choice = input("  Select: ").strip()
        wt_map = {"1": "regular", "2": "playoff", "3": "regular+playoff", "4": None}
        if wt_choice not in wt_map:
            print("  Invalid selection.")
            continue
        wt_filter = wt_map[wt_choice]

        if choice == "1":
            season_input = input("  Season: ").strip()
            week_input   = input("  Week: ").strip()
            if not (season_input.isdigit() and week_input.isdigit()):
                print("  Invalid input.")
                continue
            season, week = int(season_input), int(week_input)
            week_data = (
                clean_history.get(str(season), {})
                .get("weeks", {})
                .get(str(week))
            )
            if not week_data:
                print(f"  No data found for Season {season} Week {week}.")
                continue
            psw = clean_history[str(season)].get("playoff_start_week", 15)
            wa  = compute_weekly_awards(week_data, season=season, week=week, playoff_start_week=psw)

            # Build all-time records for record flag context
            all_wa      = compute_all_awards(clean_history)
            all_records = find_all_time_records(all_wa, week_type_filter=wt_filter)
            print_weekly_awards(wa, all_time_records=all_records)

        elif choice == "2":
            season_input = input("  Season: ").strip()
            if not season_input.isdigit():
                print("  Invalid input.")
                continue
            season   = int(season_input)
            all_wa   = compute_all_awards(clean_history)
            season_wa = [w for w in all_wa if w.season == season and (wt_filter is None or w.week_type == wt_filter)]
            if not season_wa:
                print(f"  No award data found for season {season}.")
                continue
            all_records = find_all_time_records(all_wa, week_type_filter=wt_filter)
            for wa in season_wa:
                print_weekly_awards(wa, all_time_records=all_records)

        elif choice == "3":
            all_wa      = compute_all_awards(clean_history)
            all_records = find_all_time_records(all_wa, week_type_filter=wt_filter)
            scope = {"regular": "Regular Season", "playoff": "Playoffs", "regular+playoff": "Regular + True Playoffs", None: "All-Time"}[wt_filter]
            print()
            print("=" * 60)
            print(f"  {scope} All-Time Records")
            print("=" * 60)
            for award_name, entry in all_records.items():
                if award_name in ("Biggest Win", "Closest Game"):
                    print(
                        f"  {award_name:<20} {entry.winner} by {entry.value:.2f} pts"
                        f"  (S{entry.season} W{entry.week}, vs {entry.opponent})"
                    )
                else:
                    print(
                        f"  {award_name:<20} {entry.winner} — {entry.value:.2f} pts"
                        f"  (S{entry.season} W{entry.week}, vs {entry.opponent})"
                    )
            print("=" * 60)
            print()

        else:
            print("  Invalid option.")
