"""
sleeper_api.py
--------------
Phase 1: Sleeper Fantasy Football API - Data Foundation
Fetches league info, rosters, users, and matchups from the Sleeper API.

Usage:
    python sleeper_api.py
"""

import requests
from typing import Optional

BASE_URL = "https://api.sleeper.app/v1"


# ---------------------------------------------------------------------------
# Core API helpers
# ---------------------------------------------------------------------------

def _get(endpoint: str) -> Optional[dict | list]:
    """Make a GET request to the Sleeper API. Returns parsed JSON or None on error."""
    url = f"{BASE_URL}{endpoint}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"  [ERROR] {response.status_code} fetching: {url}")
        return None


# ---------------------------------------------------------------------------
# User & League fetching
# ---------------------------------------------------------------------------

def get_user(username: str) -> Optional[dict]:
    """Fetch Sleeper user info by username."""
    return _get(f"/user/{username}")


def get_leagues_for_user(user_id: str, season: int) -> Optional[list]:
    """Fetch all NFL leagues for a user in a given season year."""
    return _get(f"/user/{user_id}/leagues/nfl/{season}")


def get_league(league_id: str) -> Optional[dict]:
    """Fetch metadata for a specific league."""
    return _get(f"/league/{league_id}")


def get_playoff_start_week(league_id: str) -> int:
    """
    Fetch the playoff start week directly from league settings.
    If the field is unavailable, prompts the user to enter it manually
    rather than silently defaulting to a potentially wrong value.

    Sleeper exposes this as 'playoff_week_start' in the league object.
    This varies by season -- e.g. the 2020 season used a 17-week schedule
    which shifted playoff timing for many leagues.
    """
    league = get_league(league_id)
    if league:
        psw = league.get("settings", {}).get("playoff_week_start")
        if psw is not None:
            return int(psw)
    print("  [WARN] Could not retrieve playoff_week_start from league settings.")
    while True:
        user_input = input("  Enter the playoff start week manually: ").strip()
        if user_input.isdigit() and int(user_input) > 0:
            return int(user_input)
        print("  Please enter a valid week number (e.g. 14, 15, 16).")

# ---------------------------------------------------------------------------
# Rosters, Users & Matchups
# ---------------------------------------------------------------------------

def get_rosters(league_id: str) -> Optional[list]:
    """Fetch all rosters in a league."""
    return _get(f"/league/{league_id}/rosters")


def get_users(league_id: str) -> Optional[list]:
    """Fetch all users/managers in a league."""
    return _get(f"/league/{league_id}/users")


def get_matchups(league_id: str, week: int) -> Optional[list]:
    """Fetch matchup data for a specific week."""
    return _get(f"/league/{league_id}/matchups/{week}")


def get_league_state() -> Optional[dict]:
    """Fetch the current NFL season state (current week, season, etc.)."""
    return _get("/state/nfl")



# ---------------------------------------------------------------------------
# Bracket fetching & playoff status classification
# ---------------------------------------------------------------------------

def get_winners_bracket(league_id: str) -> Optional[list]:
    """Fetch the winners (playoff) bracket for a league."""
    return _get(f"/league/{league_id}/winners_bracket")


def get_losers_bracket(league_id: str) -> Optional[list]:
    """Fetch the losers (consolation) bracket for a league."""
    return _get(f"/league/{league_id}/losers_bracket")


# Matches with these p values (or no p field) count as true playoff matches.
# p:1 = championship, p:3 = 3rd place, no p = early rounds.
# p:5 and higher = consolation bracket (eliminated teams).
PLAYOFF_PLACE_CUTOFF = 4  # p <= 4 or no p = playoff; p >= 5 = eliminated


def get_playoff_status(
    league_id: str,
    week: int,
    playoff_start_week: int,
    all_roster_ids: list[int],
) -> dict[int, str]:
    """
    Determine each team's playoff status for a given week.

    Status values:
        "playoff"    -- Playing in a true playoff match this round
                        (no p field, or p:1 / p:3)
        "bye"        -- In the true playoff bracket but not playing this round
        "eliminated" -- Playing in a consolation match (p:5+) or already out
        "regular"    -- Not a playoff week

    Uses the p field (place being contested) to distinguish true playoff
    matches from consolation matches. Early rounds have no p field.
    Championship = p:1, 3rd place = p:3, consolation = p:5+.
    The w and l fields (winner/loser roster IDs) are used directly rather
    than trying to resolve t1_from/t2_from references.
    """
    if week < playoff_start_week:
        return {rid: "regular" for rid in all_roster_ids}

    winners_bracket = get_winners_bracket(league_id) or []
    current_round = week - playoff_start_week + 1

    # Separate true playoff matches from consolation matches using p field
    def is_playoff_match(match: dict) -> bool:
        p = match.get("p")
        return p is None or p <= PLAYOFF_PLACE_CUTOFF

    # Collect all roster_ids that appear in true playoff matches (w, l, t1, t2)
    playoff_ids = set()
    for match in winners_bracket:
        if is_playoff_match(match):
            for key in ("t1", "t2", "w", "l"):
                val = match.get(key)
                if val is not None:
                    playoff_ids.add(val)

    # Teams playing in a true playoff match this round
    playing_playoff_this_round = set()
    for match in winners_bracket:
        if match.get("r") == current_round and is_playoff_match(match):
            for key in ("t1", "t2", "w", "l"):
                val = match.get(key)
                if val is not None:
                    playing_playoff_this_round.add(val)

    # Teams playing in a consolation match this round
    playing_consolation_this_round = set()
    for match in winners_bracket:
        if match.get("r") == current_round and not is_playoff_match(match):
            for key in ("t1", "t2", "w", "l"):
                val = match.get(key)
                if val is not None:
                    playing_consolation_this_round.add(val)

    # Classify each roster
    status_map = {}
    for rid in all_roster_ids:
        if rid in playing_playoff_this_round:
            status_map[rid] = "playoff"
        elif rid in playing_consolation_this_round:
            status_map[rid] = "eliminated"
        elif rid in playoff_ids:
            # In the true playoff bracket but not playing this round — bye
            status_map[rid] = "bye"
        else:
            status_map[rid] = "eliminated"

    return status_map


# ---------------------------------------------------------------------------
# Helper: Build a unified team lookup {roster_id -> team_name, display_name}
# ---------------------------------------------------------------------------

def build_team_map(rosters: list, users: list) -> dict:
    """
    Combine rosters and users into a lookup dict keyed by roster_id.

    Returns:
        {
            roster_id (int): {
                "roster_id": int,
                "owner_id": str,
                "display_name": str,   # Sleeper username (used as stable identifier)
                "team_name": str,      # Same as display_name — consistent across seasons
            }
        }
    """
    user_map = {u["user_id"]: u for u in users}

    team_map = {}
    for roster in rosters:
        owner_id = roster.get("owner_id")
        user = user_map.get(owner_id, {})
        display_name = user.get("display_name", "Unknown")
        team_map[roster["roster_id"]] = {
            "roster_id": roster["roster_id"],
            "owner_id": owner_id,
            "display_name": display_name,
            "team_name": display_name,   # Always use username for consistency
        }

    return team_map


# ---------------------------------------------------------------------------
# Helper: Parse matchups into head-to-head results
# ---------------------------------------------------------------------------

def parse_matchups(
    matchups: list,
    team_map: dict,
    status_map: Optional[dict] = None,
) -> dict:
    """
    Convert raw matchup list into structured head-to-head results.

    Separates teams by their playoff status when status_map is provided
    (built via get_playoff_status()). Without it, all non-bye teams are
    grouped under "matchups" as normal.

    Status values per team: "playoff", "bye", "eliminated", "regular"
    Bye teams (matchup_id=None) are always separated regardless of status_map.

    Returns a dict:
        {
            "matchups": [
                {
                    "matchup_id": int,
                    "home": {"roster_id", "display_name", "points", "playoff_status"},
                    "away": {"roster_id", "display_name", "points", "playoff_status"},
                    "winner": display_name of winner,
                    "margin": float,
                    "playoff_status": "playoff" | "eliminated" | "regular"
                      -- reflects the matchup type based on both teams' statuses:
                      "playoff" only if both teams are active playoff competitors,
                      "eliminated" if either team is eliminated,
                      "regular" during regular season weeks
                }
            ],
            "byes": [
                {
                    "display_name": str,
                    "roster_id": int,
                    "points": float,
                    "playoff_status": "bye" | "regular"
                }
            ]
        }
    """
    groups: dict[int, list] = {}
    byes = []

    for entry in matchups:
        mid = entry["matchup_id"]
        if mid is None:
            team = team_map.get(entry["roster_id"], {})
            roster_id = entry["roster_id"]
            playoff_status = (status_map or {}).get(roster_id, "regular")
            byes.append({
                **team,
                "points": entry.get("points", 0) or 0,
                "playoff_status": playoff_status,
            })
        else:
            groups.setdefault(mid, []).append(entry)

    results = []
    for mid, pair in groups.items():
        if len(pair) != 2:
            continue

        a, b = pair
        team_a = team_map.get(a["roster_id"], {})
        team_b = team_map.get(b["roster_id"], {})
        pts_a = a.get("points", 0) or 0
        pts_b = b.get("points", 0) or 0
        status_a = (status_map or {}).get(a["roster_id"], "regular")
        status_b = (status_map or {}).get(b["roster_id"], "regular")

        if pts_a >= pts_b:
            home, away, pts_home, pts_away = team_a, team_b, pts_a, pts_b
            status_home, status_away = status_a, status_b
        else:
            home, away, pts_home, pts_away = team_b, team_a, pts_b, pts_a
            status_home, status_away = status_b, status_a

        # Matchup is only a true playoff matchup if both teams are active
        if status_home == "playoff" and status_away == "playoff":
            matchup_status = "playoff"
        elif status_home == "regular" or status_away == "regular":
            matchup_status = "regular"
        else:
            matchup_status = "eliminated"

        results.append({
            "matchup_id": mid,
            "home": {**home, "points": pts_home, "playoff_status": status_home},
            "away": {**away, "points": pts_away, "playoff_status": status_away},
            "winner": home.get("display_name", "?"),
            "margin": round(pts_home - pts_away, 2),
            "playoff_status": matchup_status,
        })

    return {
        "matchups": sorted(results, key=lambda x: x["matchup_id"]),
        "byes": byes,
    }


# ---------------------------------------------------------------------------
# Weekly summary printer
# ---------------------------------------------------------------------------

def print_weekly_summary(
    league_name: str,
    season: int,
    week: int,
    parsed: dict,
):
    """
    Print a readable summary of a week's matchups to the console.
    Accepts the dict returned by parse_matchups(), which contains
    separate 'matchups' and 'byes' keys.
    """
    matchup_results = parsed["matchups"]
    bye_teams = parsed["byes"]

    print()
    print("=" * 60)
    print(f"  {league_name}  |  Season {season}  |  Week {week}")
    print("=" * 60)

    STATUS_LABELS = {
        "playoff":    "[PLAYOFF]   ",
        "eliminated": "[ELIM]      ",
        "regular":    "            ",
    }

    all_scores = []
    for m in matchup_results:
        h = m["home"]
        a = m["away"]
        all_scores.extend([
            (h["display_name"], h["points"]),
            (a["display_name"], a["points"]),
        ])
        label = STATUS_LABELS.get(m.get("playoff_status", "regular"), "            ")
        print(
            f"  {label} [{m['matchup_id']}]  "
            f"{h['display_name']} {h['points']:.2f}  vs  "
            f"{a['display_name']} {a['points']:.2f}  "
            f"(margin: {m['margin']:.2f})"
        )

    if bye_teams:
        print()
        print("  Byes / Waiting:")
        for b in bye_teams:
            all_scores.append((b["display_name"], b["points"]))
            status = b.get("playoff_status", "regular")
            bye_label = "[BYE]" if status == "bye" else "[ELIM]"
            print(f"    {bye_label}  {b['display_name']} -- {b['points']:.2f} pts")

    if all_scores:
        print()
        sorted_scores = sorted(all_scores, key=lambda x: x[1], reverse=True)
        highest = sorted_scores[0]
        lowest = sorted_scores[-1]
        biggest_win = max(matchup_results, key=lambda x: x["margin"]) if matchup_results else None

        print(f"  Highest Score : {highest[0]} -- {highest[1]:.2f} pts")
        print(f"  Lowest Score  : {lowest[0]} -- {lowest[1]:.2f} pts")
        if biggest_win:
            print(
                f"  Biggest Win   : {biggest_win['home']['display_name']} "
                f"by {biggest_win['margin']:.2f} pts"
            )

    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# Main: Interactive runner
# ---------------------------------------------------------------------------

def main():
    print("\n--- Sleeper Fantasy Football | Phase 1: Data Foundation ---\n")

    username = input("Enter your Sleeper username: ").strip()

    user = get_user(username)
    if not user:
        print("Could not find that user. Check your username and try again.")
        return
    user_id = user["user_id"]
    print(f"  Found user: {user.get('display_name')} (ID: {user_id})")

    # Get current NFL state to suggest defaults
    state = get_league_state()
    current_season = int(state["season"]) if state else 2024
    current_week = int(state["week"]) if state else 1

    season_input = input(f"  Enter season year [{current_season}]: ").strip()
    season = int(season_input) if season_input else current_season

    leagues = get_leagues_for_user(user_id, season)
    if not leagues:
        print(f"  No leagues found for season {season}.")
        return

    print(f"\n  Leagues found for {season}:")
    for i, lg in enumerate(leagues):
        print(f"    [{i}] {lg['name']}  (ID: {lg['league_id']})")

    if len(leagues) == 1:
        league = leagues[0]
    else:
        idx = input("  Select league number: ").strip()
        league = leagues[int(idx)]

    league_id = league["league_id"]
    league_name = league["name"]
    print(f"\n  Selected: {league_name} (ID: {league_id})")

    week_input = input(f"  Enter week to fetch [{current_week}]: ").strip()
    week = int(week_input) if week_input else current_week

    print("\n  Fetching rosters, users, and matchups...")
    rosters = get_rosters(league_id)
    users = get_users(league_id)
    matchups = get_matchups(league_id, week)

    if not all([rosters, users, matchups]):
        print("  Failed to fetch some data. Check league ID and week number.")
        return

    playoff_start_week = get_playoff_start_week(league_id)
    team_map = build_team_map(rosters, users)

    # Build playoff status map for playoff weeks, otherwise pass None
    status_map = None
    if week >= playoff_start_week:
        all_roster_ids = [r["roster_id"] for r in rosters]
        status_map = get_playoff_status(league_id, week, playoff_start_week, all_roster_ids)

    parsed = parse_matchups(matchups, team_map, status_map=status_map)

    print_weekly_summary(league_name, season, week, parsed)


if __name__ == "__main__":
    main()
