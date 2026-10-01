"""
history.py
----------
Phase 3: Sleeper Fantasy Football - History Manager

Handles persistent storage of weekly matchup data across all seasons.
Data is stored in a local history.json file organized by season.

Storage structure:
{
    "2019": {
        "league_id": "...",
        "league_name": "...",
        "playoff_start_week": 14,
        "weeks": {
            "1": { "matchups": [...], "byes": [...] },
            "2": { ... },
            ...
        }
    },
    "2020": { ... },
    ...
}

Usage:
    python history.py
    (runs the interactive backfill / weekly update flow)
"""

import json
import os
from typing import Optional

from data_quality import load_rules, apply_all_rules
from sleeper_api import (
    get_user,
    get_leagues_for_user,
    get_league_state,
    get_rosters,
    get_users,
    get_matchups,
    get_playoff_start_week,
    get_playoff_status,
    build_team_map,
    parse_matchups,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_HISTORY_PATH = os.path.join(os.path.dirname(__file__), "data", "history.json")


# ---------------------------------------------------------------------------
# Load & Save
# ---------------------------------------------------------------------------

def load_history(path: str = DEFAULT_HISTORY_PATH) -> dict:
    """Load history from disk. Returns empty dict if file doesn't exist yet."""
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def save_history(history: dict, path: str = DEFAULT_HISTORY_PATH) -> None:
    """Save history to disk, creating the directory if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(history, f, indent=2)
    print(f"  History saved to {path}")


# ---------------------------------------------------------------------------
# Single week fetch & store
# ---------------------------------------------------------------------------

def fetch_and_store_week(
    history: dict,
    league_id: str,
    league_name: str,
    season: int,
    week: int,
    playoff_start_week: int,
    rosters: list,
    users: list,
    overwrite: bool = False,
) -> tuple[dict, bool]:
    """
    Fetch a single week from the Sleeper API and store it in the history dict.

    Args:
        history:             The current history dict (modified in place)
        league_id:           Sleeper league ID for this season
        league_name:         Human-readable league name
        season:              NFL season year (e.g. 2024)
        week:                Week number to fetch
        playoff_start_week:  Playoff start week for this season
        rosters:             Pre-fetched rosters (avoids redundant API calls)
        users:               Pre-fetched users
        overwrite:           If True, overwrite existing week data

    Returns:
        (updated history dict, success bool)
    """
    season_key = str(season)
    week_key = str(week)

    # Check for existing data
    existing_week = (
        history
        .get(season_key, {})
        .get("weeks", {})
        .get(week_key)
    )
    if existing_week and not overwrite:
        print(f"  [SKIP] Season {season} Week {week} already exists in history.")
        return history, False

    # Fetch matchup data
    matchups = get_matchups(league_id, week)
    if not matchups:
        print(f"  [WARN] No matchup data returned for Season {season} Week {week} — skipping.")
        return history, False

    # Skip weeks where all scores are 0 — games haven't been played yet
    all_points = [m.get("points") or 0 for m in matchups]
    if all(p == 0 for p in all_points):
        print(f"  [SKIP] Season {season} Week {week} — all scores are 0, week not yet played.")
        return history, False

    # Build playoff status map for playoff weeks
    status_map = None
    if week >= playoff_start_week:
        all_roster_ids = [r["roster_id"] for r in rosters]
        status_map = get_playoff_status(league_id, week, playoff_start_week, all_roster_ids)

    team_map = build_team_map(rosters, users)
    parsed = parse_matchups(matchups, team_map, status_map=status_map)

    # Ensure season entry exists
    if season_key not in history:
        history[season_key] = {
            "league_id": league_id,
            "league_name": league_name,
            "playoff_start_week": playoff_start_week,
            "weeks": {},
        }

    history[season_key]["weeks"][week_key] = parsed
    return history, True


# ---------------------------------------------------------------------------
# Determine how many weeks to fetch for a season
# ---------------------------------------------------------------------------

def get_weeks_to_fetch(league_id: str, season: int, current_season: int, current_week: int) -> list[int]:
    """
    Return the list of week numbers to fetch for a given season.

    For past seasons: fetch all 18 weeks (Sleeper returns empty for weeks
    that didn't happen, which fetch_and_store_week handles gracefully).
    For the current season: only fetch up to the current week.
    """
    if season < current_season:
        return list(range(1, 19))  # weeks 1-18, Sleeper skips non-existent ones
    else:
        return list(range(1, current_week + 1))


# ---------------------------------------------------------------------------
# Backfill: pull all seasons linked to a user
# ---------------------------------------------------------------------------

def backfill(
    username: str,
    history: dict,
    start_season: int,
    end_season: int,
    current_week: int,
    path: str = DEFAULT_HISTORY_PATH,
) -> dict:
    """
    Backfill all seasons between start_season and end_season (inclusive).
    Skips any week already present in history.
    Saves history to disk after each season completes.

    Args:
        username:      Sleeper username (used to find league each season)
        history:       Existing history dict
        start_season:  First season year to pull (e.g. 2019)
        end_season:    Last season year to pull (e.g. 2024)
        current_week:  Current NFL week (to avoid fetching future weeks)
        path:          Path to history.json

    Returns:
        Updated history dict
    """
    user = get_user(username)
    if not user:
        print(f"  [ERROR] Could not find Sleeper user '{username}'.")
        return history

    user_id = user["user_id"]
    current_season = end_season

    for season in range(start_season, end_season + 1):
        print(f"\n{'=' * 60}")
        print(f"  Backfilling season {season}...")
        print(f"{'=' * 60}")

        leagues = get_leagues_for_user(user_id, season)
        if not leagues:
            print(f"  [WARN] No leagues found for season {season} — skipping.")
            continue

        # If multiple leagues, pick the one already in history or prompt
        league = _select_league(leagues, history, season)
        if not league:
            continue

        league_id = league["league_id"]
        league_name = league["name"]
        playoff_start_week = get_playoff_start_week(league_id)

        print(f"  League: {league_name} (playoff from week {playoff_start_week})")

        rosters = get_rosters(league_id)
        users_data = get_users(league_id)
        if not rosters or not users_data:
            print(f"  [ERROR] Could not fetch rosters/users for season {season} — skipping.")
            continue

        weeks = get_weeks_to_fetch(league_id, season, current_season, current_week)
        stored = 0
        skipped = 0

        for week in weeks:
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
                stored += 1
                print(f"    Stored: Season {season} Week {week}")
            else:
                skipped += 1

        print(f"\n  Season {season} complete — {stored} weeks stored, {skipped} skipped.")
        save_history(history, path)

    return history


def _select_league(leagues: list, history: dict, season: int) -> Optional[dict]:
    """
    Select the correct league for a season.
    If there's only one, use it. If multiple, check history first,
    then prompt the user.
    """
    if len(leagues) == 1:
        return leagues[0]

    # Check if we already have a league stored for this season
    season_key = str(season)
    if season_key in history:
        stored_league_id = history[season_key].get("league_id")
        for lg in leagues:
            if lg["league_id"] == stored_league_id:
                return lg

    # Prompt user to pick
    print(f"  Multiple leagues found for {season}:")
    for i, lg in enumerate(leagues):
        print(f"    [{i}] {lg['name']}  (ID: {lg['league_id']})")
    idx = input("  Select league number: ").strip()
    if idx.isdigit() and int(idx) < len(leagues):
        return leagues[int(idx)]

    print("  [ERROR] Invalid selection — skipping season.")
    return None


# ---------------------------------------------------------------------------
# Weekly update: add just the latest week
# ---------------------------------------------------------------------------

def weekly_update(
    username: str,
    history: dict,
    season: int,
    week: int,
    path: str = DEFAULT_HISTORY_PATH,
) -> dict:
    """
    Fetch and store a single week. Skips if already present (with warning).
    Saves history to disk on success.
    """
    user = get_user(username)
    if not user:
        print(f"  [ERROR] Could not find Sleeper user '{username}'.")
        return history

    user_id = user["user_id"]
    leagues = get_leagues_for_user(user_id, season)
    if not leagues:
        print(f"  [ERROR] No leagues found for season {season}.")
        return history

    league = _select_league(leagues, history, season)
    if not league:
        return history

    league_id = league["league_id"]
    league_name = league["name"]
    playoff_start_week = get_playoff_start_week(league_id)
    rosters = get_rosters(league_id)
    users_data = get_users(league_id)

    if not rosters or not users_data:
        print(f"  [ERROR] Could not fetch rosters/users for season {season}.")
        return history

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
        print(f"  Stored Season {season} Week {week}.")
        save_history(history, path)
    
    return history


# ---------------------------------------------------------------------------
# Query helpers (used by awards.py and dashboard)
# ---------------------------------------------------------------------------

def get_season(history: dict, season: int) -> Optional[dict]:
    """Return all data for a given season, or None if not in history."""
    return history.get(str(season))


def get_week(history: dict, season: int, week: int) -> Optional[dict]:
    """Return parsed matchup data for a specific season and week."""
    return (
        history
        .get(str(season), {})
        .get("weeks", {})
        .get(str(week))
    )


def get_all_weeks(
    history: dict,
    season: Optional[int] = None,
    week_type: Optional[str] = None,
    playoff_start_week_override: Optional[int] = None,
) -> list[dict]:
    """
    Return a flat list of all stored weeks, optionally filtered.

    Each entry is the parsed week dict plus injected metadata:
        { "season": int, "week": int, "week_type": str, "matchups": [...], "byes": [...] }

    Args:
        history:                    Full history dict
        season:                     Filter to a single season (None = all seasons)
        week_type:                  "regular", "playoff", or None (all)
        playoff_start_week_override: Override per-season playoff_start_week if needed
    """
    results = []
    seasons = [str(season)] if season else sorted(history.keys())

    for season_key in seasons:
        season_data = history.get(season_key, {})
        psw = playoff_start_week_override or season_data.get("playoff_start_week", 15)

        for week_key, week_data in sorted(
            season_data.get("weeks", {}).items(), key=lambda x: int(x[0])
        ):
            w = int(week_key)
            wt = "playoff" if w >= psw else "regular"

            if week_type and wt != week_type:
                continue

            results.append({
                "season": int(season_key),
                "week": w,
                "week_type": wt,
                **week_data,
            })

    return results


def get_seasons_list(history: dict) -> list[int]:
    """Return sorted list of all season years present in history."""
    return sorted(int(k) for k in history.keys())



# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------

def compute_standings(
    history: dict,
    season: Optional[int] = None,
    week_type: str = "regular",
) -> list[dict]:
    """
    Compute team standings from stored history.

    Only counts head-to-head matchups with playoff_status matching week_type
    filter. Bye and eliminated matchups are excluded from W/L records but
    their scores still count toward Points For.

    Args:
        history:    Full history dict
        season:     Single season year, or None for all-time
        week_type:  "regular", "playoff", or "all"

    Returns:
        List of team dicts sorted by wins desc, then points_for desc:
        [
            {
                "display_name": str,
                "wins": int,
                "losses": int,
                "points_for": float,
                "points_against": float,
                "weeks_played": int,
                "seasons": list[int],   # seasons this team appeared in
            }
        ]
    """
    teams: dict[str, dict] = {}

    seasons = [str(season)] if season else sorted(history.keys())

    for season_key in seasons:
        season_data = history.get(season_key, {})
        psw = season_data.get("playoff_start_week", 15)

        for week_key, week_data in season_data.get("weeks", {}).items():
            w = int(week_key)
            wt = "playoff" if w >= psw else "regular"

            # Apply week_type filter
            if week_type != "all" and wt != week_type:
                continue

            def ensure_team(name: str):
                if name not in teams:
                    teams[name] = {
                        "display_name": name,
                        "wins": 0,
                        "losses": 0,
                        "points_for": 0.0,
                        "points_against": 0.0,
                        "weeks_played": 0,
                        "seasons": [],
                    }
                s = int(season_key)
                if s not in teams[name]["seasons"]:
                    teams[name]["seasons"].append(s)

            # Process head-to-head matchups
            for m in week_data.get("matchups", []):
                h = m["home"]
                a = m["away"]
                matchup_status = m.get("playoff_status", "regular")

                # Only count W/L for true matchups (not eliminated vs eliminated)
                count_record = (
                    week_type == "all"
                    or matchup_status == week_type
                    or (week_type == "regular" and matchup_status == "regular")
                    or (week_type == "playoff" and matchup_status == "playoff")
                )

                for team, pts, opp_pts, won in [
                    (h["display_name"], h["points"], a["points"], True),
                    (a["display_name"], a["points"], h["points"], False),
                ]:
                    ensure_team(team)
                    teams[team]["points_for"] = round(teams[team]["points_for"] + pts, 2)
                    teams[team]["points_against"] = round(teams[team]["points_against"] + opp_pts, 2)
                    teams[team]["weeks_played"] += 1
                    if count_record:
                        if won:
                            teams[team]["wins"] += 1
                        else:
                            teams[team]["losses"] += 1

            # Include bye team scores in points_for (no W/L)
            for b in week_data.get("byes", []):
                name = b["display_name"]
                ensure_team(name)
                teams[name]["points_for"] = round(teams[name]["points_for"] + b["points"], 2)
                teams[name]["weeks_played"] += 1

    # Sort by wins desc, then points_for desc
    standings = sorted(
        teams.values(),
        key=lambda x: (x["wins"], x["points_for"]),
        reverse=True,
    )
    for i, team in enumerate(standings):
        team["seasons"] = sorted(team["seasons"])
        team["rank"] = i + 1

    return standings


def print_standings(standings: list[dict], title: str = "Standings") -> None:
    """Print standings table to console."""
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)
    print(f"  {'#':<4} {'Team':<20} {'W':<5} {'L':<5} {'PF':<10} {'PA':<10} {'Wks'}")
    print(f"  {'-'*4} {'-'*20} {'-'*5} {'-'*5} {'-'*10} {'-'*10} {'-'*4}")
    for t in standings:
        print(
            f"  {t['rank']:<4} {t['display_name']:<20} "
            f"{t['wins']:<5} {t['losses']:<5} "
            f"{t['points_for']:<10.2f} {t['points_against']:<10.2f} "
            f"{t['weeks_played']}"
        )
    print("=" * 72)
    print()



# ---------------------------------------------------------------------------
# Alternate Standings 1: Beat the Average
# ---------------------------------------------------------------------------

def compute_beat_average_standings(
    history: dict,
    season: Optional[int] = None,
    week_type: str = "regular",
) -> list[dict]:
    """
    Alternate standings where a win is awarded if a team scored above
    the weekly average, and a loss if below. Ties (exact average) count
    as half a win and half a loss.

    All teams in a week (including bye teams) are included in the average
    calculation since their score is real regardless of having an opponent.

    Args:
        history:    Full history dict
        season:     Single season year, or None for all-time
        week_type:  "regular", "playoff", or "all"

    Returns:
        List of team dicts sorted by wins desc, then points_for desc
    """
    teams: dict[str, dict] = {}
    seasons = [str(season)] if season else sorted(history.keys())

    def ensure_team(name: str, season_key: str):
        if name not in teams:
            teams[name] = {
                "display_name": name,
                "wins": 0.0,
                "losses": 0.0,
                "points_for": 0.0,
                "weeks_played": 0,
                "seasons": [],
            }
        s = int(season_key)
        if s not in teams[name]["seasons"]:
            teams[name]["seasons"].append(s)

    for season_key in seasons:
        season_data = history.get(season_key, {})
        psw = season_data.get("playoff_start_week", 15)

        for week_key, week_data in season_data.get("weeks", {}).items():
            w  = int(week_key)
            wt = "playoff" if w >= psw else "regular"
            if week_type != "all" and wt != week_type:
                continue

            # Collect all scores for the week
            week_scores: list[tuple[str, float]] = []
            for m in week_data.get("matchups", []):
                week_scores.append((m["home"]["display_name"], m["home"]["points"]))
                week_scores.append((m["away"]["display_name"], m["away"]["points"]))
            for b in week_data.get("byes", []):
                week_scores.append((b["display_name"], b["points"]))

            if not week_scores:
                continue

            avg = sum(pts for _, pts in week_scores) / len(week_scores)

            for name, pts in week_scores:
                ensure_team(name, season_key)
                teams[name]["points_for"]   = round(teams[name]["points_for"] + pts, 2)
                teams[name]["weeks_played"] += 1
                if pts > avg:
                    teams[name]["wins"]   += 1
                elif pts < avg:
                    teams[name]["losses"] += 1
                else:
                    # Exact tie with average — split
                    teams[name]["wins"]   += 0.5
                    teams[name]["losses"] += 0.5

    standings = sorted(
        teams.values(),
        key=lambda x: (x["wins"], x["points_for"]),
        reverse=True,
    )
    for i, team in enumerate(standings):
        team["seasons"] = sorted(team["seasons"])
        team["rank"]    = i + 1
        team["wins"]    = round(team["wins"],   1)
        team["losses"]  = round(team["losses"], 1)

    return standings


# ---------------------------------------------------------------------------
# Alternate Standings 2: Schedules Against Everyone
# ---------------------------------------------------------------------------

def compute_schedules_against_everyone(
    history: dict,
    season: Optional[int] = None,
    week_type: str = "regular",
) -> list[dict]:
    """
    Alternate standings where every team plays every other team each week.
    A team earns a win for each team they outscored and a loss for each
    team that outscored them. Ties split as half a win / half a loss.

    In a 10-team league each team plays 9 virtual matchups per week,
    so records could range from 9-0 (top scorer) to 0-9 (bottom scorer).

    Args:
        history:    Full history dict
        season:     Single season year, or None for all-time
        week_type:  "regular", "playoff", or "all"

    Returns:
        List of team dicts sorted by wins desc, then points_for desc
    """
    teams: dict[str, dict] = {}
    seasons = [str(season)] if season else sorted(history.keys())

    def ensure_team(name: str, season_key: str):
        if name not in teams:
            teams[name] = {
                "display_name": name,
                "wins": 0.0,
                "losses": 0.0,
                "points_for": 0.0,
                "weeks_played": 0,
                "seasons": [],
            }
        s = int(season_key)
        if s not in teams[name]["seasons"]:
            teams[name]["seasons"].append(s)

    for season_key in seasons:
        season_data = history.get(season_key, {})
        psw = season_data.get("playoff_start_week", 15)

        for week_key, week_data in season_data.get("weeks", {}).items():
            w  = int(week_key)
            wt = "playoff" if w >= psw else "regular"
            if week_type != "all" and wt != week_type:
                continue

            # Collect all scores for the week
            week_scores: list[tuple[str, float]] = []
            for m in week_data.get("matchups", []):
                week_scores.append((m["home"]["display_name"], m["home"]["points"]))
                week_scores.append((m["away"]["display_name"], m["away"]["points"]))
            for b in week_data.get("byes", []):
                week_scores.append((b["display_name"], b["points"]))

            if not week_scores:
                continue

            for i, (name, pts) in enumerate(week_scores):
                ensure_team(name, season_key)
                teams[name]["points_for"]   = round(teams[name]["points_for"] + pts, 2)
                teams[name]["weeks_played"] += 1

                # Compare against every other team this week
                for j, (other_name, other_pts) in enumerate(week_scores):
                    if i == j:
                        continue
                    if pts > other_pts:
                        teams[name]["wins"]   += 1
                    elif pts < other_pts:
                        teams[name]["losses"] += 1
                    else:
                        teams[name]["wins"]   += 0.5
                        teams[name]["losses"] += 0.5

    standings = sorted(
        teams.values(),
        key=lambda x: (x["wins"], x["points_for"]),
        reverse=True,
    )
    for i, team in enumerate(standings):
        team["seasons"] = sorted(team["seasons"])
        team["rank"]    = i + 1
        team["wins"]    = round(team["wins"],   1)
        team["losses"]  = round(team["losses"], 1)

    return standings


def print_alt_standings(standings: list[dict], title: str) -> None:
    """Print alternate standings to console (shared format for both alt standings)."""
    print()
    print("=" * 65)
    print(f"  {title}")
    print("=" * 65)
    print(f"  {'#':<4} {'Team':<20} {'W':<7} {'L':<7} {'PF':<10} {'Wks'}")
    print(f"  {'-'*4} {'-'*20} {'-'*7} {'-'*7} {'-'*10} {'-'*4}")
    for t in standings:
        print(
            f"  {t['rank']:<4} {t['display_name']:<20} "
            f"{t['wins']:<7} {t['losses']:<7} "
            f"{t['points_for']:<10.2f} {t['weeks_played']}"
        )
    print("=" * 65)
    print()


# ---------------------------------------------------------------------------
# Alternate Standings 3: Second Lowest Winner
# ---------------------------------------------------------------------------

def compute_second_lowest_winner(
    history: dict,
    season: Optional[int] = None,
    week_type: str = "regular",
) -> list[dict]:
    """
    Count how many times each team won with the second lowest score
    of all teams that week. Only head-to-head matchup winners are
    considered — bye teams are excluded since they have no result.

    Args:
        history:    Full history dict
        season:     Single season year, or None for all-time
        week_type:  "regular", "playoff", or "all"

    Returns:
        List of team dicts sorted by count desc, then points_for desc
    """
    teams: dict[str, dict] = {}
    seasons = [str(season)] if season else sorted(history.keys())

    def ensure_team(name: str, season_key: str):
        if name not in teams:
            teams[name] = {
                "display_name": name,
                "count": 0,
                "points_for": 0.0,
                "weeks_played": 0,
                "seasons": [],
            }
        s = int(season_key)
        if s not in teams[name]["seasons"]:
            teams[name]["seasons"].append(s)

    for season_key in seasons:
        season_data = history.get(season_key, {})
        psw = season_data.get("playoff_start_week", 15)

        for week_key, week_data in season_data.get("weeks", {}).items():
            w  = int(week_key)
            wt = "playoff" if w >= psw else "regular"
            if week_type != "all" and wt != week_type:
                continue

            # Collect all scores from head-to-head matchups only
            week_scores: list[tuple[str, float, bool]] = []  # (name, pts, won)
            for m in week_data.get("matchups", []):
                week_scores.append((m["home"]["display_name"], m["home"]["points"], True))
                week_scores.append((m["away"]["display_name"], m["away"]["points"], False))

            if len(week_scores) < 2:
                continue

            # Ensure all teams are tracked
            for name, pts, won in week_scores:
                ensure_team(name, season_key)
                teams[name]["points_for"]   = round(teams[name]["points_for"] + pts, 2)
                teams[name]["weeks_played"] += 1

            # Find the second lowest score among all teams this week
            sorted_scores = sorted(week_scores, key=lambda x: x[1])
            second_lowest_score = sorted_scores[1][1]

            # Award count to any winner whose score equals the second lowest
            for name, pts, won in week_scores:
                if won and pts == second_lowest_score:
                    teams[name]["count"] += 1

    standings = sorted(
        teams.values(),
        key=lambda x: (x["count"], x["points_for"]),
        reverse=True,
    )
    for i, team in enumerate(standings):
        team["seasons"] = sorted(team["seasons"])
        team["rank"]    = i + 1

    return standings


# ---------------------------------------------------------------------------
# Alternate Standings 4: Second Highest Loser
# ---------------------------------------------------------------------------

def compute_second_highest_loser(
    history: dict,
    season: Optional[int] = None,
    week_type: str = "regular",
) -> list[dict]:
    """
    Count how many times each team lost with the second highest score
    of all teams that week. Only head-to-head matchup losers are
    considered — bye teams are excluded since they have no result.

    Args:
        history:    Full history dict
        season:     Single season year, or None for all-time
        week_type:  "regular", "playoff", or "all"

    Returns:
        List of team dicts sorted by count desc, then points_for desc
    """
    teams: dict[str, dict] = {}
    seasons = [str(season)] if season else sorted(history.keys())

    def ensure_team(name: str, season_key: str):
        if name not in teams:
            teams[name] = {
                "display_name": name,
                "count": 0,
                "points_for": 0.0,
                "weeks_played": 0,
                "seasons": [],
            }
        s = int(season_key)
        if s not in teams[name]["seasons"]:
            teams[name]["seasons"].append(s)

    for season_key in seasons:
        season_data = history.get(season_key, {})
        psw = season_data.get("playoff_start_week", 15)

        for week_key, week_data in season_data.get("weeks", {}).items():
            w  = int(week_key)
            wt = "playoff" if w >= psw else "regular"
            if week_type != "all" and wt != week_type:
                continue

            # Collect all scores from head-to-head matchups only
            week_scores: list[tuple[str, float, bool]] = []  # (name, pts, won)
            for m in week_data.get("matchups", []):
                week_scores.append((m["home"]["display_name"], m["home"]["points"], True))
                week_scores.append((m["away"]["display_name"], m["away"]["points"], False))

            if len(week_scores) < 2:
                continue

            # Ensure all teams are tracked
            for name, pts, won in week_scores:
                ensure_team(name, season_key)
                teams[name]["points_for"]   = round(teams[name]["points_for"] + pts, 2)
                teams[name]["weeks_played"] += 1

            # Find the second highest score among all teams this week
            sorted_scores = sorted(week_scores, key=lambda x: x[1], reverse=True)
            second_highest_score = sorted_scores[1][1]

            # Award count to any loser whose score equals the second highest
            for name, pts, won in week_scores:
                if not won and pts == second_highest_score:
                    teams[name]["count"] += 1

    standings = sorted(
        teams.values(),
        key=lambda x: (x["count"], x["points_for"]),
        reverse=True,
    )
    for i, team in enumerate(standings):
        team["seasons"] = sorted(team["seasons"])
        team["rank"]    = i + 1

    return standings


def print_count_standings(standings: list[dict], title: str) -> None:
    """Print count-based alternate standings (Second Lowest Winner / Second Highest Loser)."""
    print()
    print("=" * 62)
    print(f"  {title}")
    print("=" * 62)
    print(f"  {'#':<4} {'Team':<20} {'Count':<8} {'PF':<10} {'Wks'}")
    print(f"  {'-'*4} {'-'*20} {'-'*8} {'-'*10} {'-'*4}")
    for t in standings:
        print(
            f"  {t['rank']:<4} {t['display_name']:<20} "
            f"{t['count']:<8} {t['points_for']:<10.2f} {t['weeks_played']}"
        )
    print("=" * 62)
    print()

# ---------------------------------------------------------------------------
# Main: interactive runner
# ---------------------------------------------------------------------------

def main():
    print("\n--- Sleeper Fantasy Football | Phase 3: History Manager ---\n")

    history = load_history()
    existing_seasons = get_seasons_list(history)
    if existing_seasons:
        print(f"  Existing history: seasons {existing_seasons[0]}–{existing_seasons[-1]}")
    else:
        print("  No history found — starting fresh.")

    username = input("\n  Enter your Sleeper username: ").strip()

    state = get_league_state()
    current_season = int(state["season"]) if state else 2024
    current_week = int(state["week"]) if state else 1

    print(f"\n  Current NFL state: Season {current_season}, Week {current_week}")
    print("\n  What would you like to do?")
    print("    [1] Backfill all seasons")
    print("    [2] Add / update a single week")
    print("    [3] View standings")

    choice = input("\n  Select option: ").strip()

    if choice == "1":
        start_input = input(f"  Start season [{current_season - 5}]: ").strip()
        start_season = int(start_input) if start_input else current_season - 5
        history = backfill(
            username=username,
            history=history,
            start_season=start_season,
            end_season=current_season,
            current_week=current_week,
        )

    elif choice == "2":
        season_input = input(f"  Season [{current_season}]: ").strip()
        season = int(season_input) if season_input else current_season
        week_input = input(f"  Week [{current_week}]: ").strip()
        week = int(week_input) if week_input else current_week
        history = weekly_update(
            username=username,
            history=history,
            season=season,
            week=week,
        )

    elif choice == "3":
        rules = load_rules()
        clean_history, _ = apply_all_rules(history, rules)
        while True:
            season_input = input("  Season (leave blank for all-time, q to go back): ").strip()
            if season_input.lower() == "q":
                break
            season_filter = int(season_input) if season_input else None

            print("  Week type: [1] Regular season  [2] Playoffs  [3] All")
            wt_choice = input("  Select: ").strip()
            wt_map = {"1": "regular", "2": "playoff", "3": "all"}
            week_type = wt_map.get(wt_choice, "regular")

            print("  Standings type:")
            print("    [1] Actual (head-to-head)")
            print("    [2] Beat the Average")
            print("    [3] Schedules Against Everyone")
            print("    [4] Second Lowest Winner (lucky count)")
            print("    [5] Second Highest Loser (unlucky count)")
            print("    [6] All")
            st_choice = input("  Select: ").strip()

            scope = f"Season {season_filter}" if season_filter else "All-Time"

            if st_choice in ("1", "6"):
                standings = compute_standings(clean_history, season=season_filter, week_type=week_type)
                print_standings(standings, title=f"{scope} Standings — Actual ({week_type.title()})")

            if st_choice in ("2", "6"):
                standings = compute_beat_average_standings(clean_history, season=season_filter, week_type=week_type)
                print_alt_standings(standings, title=f"{scope} Standings — Beat the Average ({week_type.title()})")

            if st_choice in ("3", "6"):
                standings = compute_schedules_against_everyone(clean_history, season=season_filter, week_type=week_type)
                print_alt_standings(standings, title=f"{scope} Standings — Schedules Against Everyone ({week_type.title()})")

            if st_choice in ("4", "6"):
                standings = compute_second_lowest_winner(clean_history, season=season_filter, week_type=week_type)
                print_count_standings(standings, title=f"{scope} — Second Lowest Winner ({week_type.title()})")

            if st_choice in ("5", "6"):
                standings = compute_second_highest_loser(clean_history, season=season_filter, week_type=week_type)
                print_count_standings(standings, title=f"{scope} — Second Highest Loser ({week_type.title()})")

            if st_choice not in ("1", "2", "3", "4", "5", "6"):
                print("  Invalid selection.")

            print()

    else:
        print("  Invalid option.")

    print("\n  Done.")


if __name__ == "__main__":
    main()
