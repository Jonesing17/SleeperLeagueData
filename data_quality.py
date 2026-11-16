"""
data_quality.py
---------------
Phase 3.5: Sleeper Fantasy Football - Data Quality

A collection of data cleaning and correction rules applied to the
history dict before it is used for awards or standings.

Rules are applied in sequence via apply_all_rules(). Each rule is
a standalone function that takes the history dict and returns a
modified copy, along with a summary of what changed.

Current rules:
    - merge_usernames: Consolidate multiple usernames for the same person

Usage:
    from data_quality import apply_all_rules, load_rules, save_rules
    history = apply_all_rules(history, rules)

Rules are stored separately in data/quality_rules.json so they can
be edited and re-applied without modifying history.json directly.
"""

import json
import os
from typing import Optional
from copy import deepcopy

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

from config import RULES_PATH as DEFAULT_RULES_PATH, HISTORY_PATH as DEFAULT_HISTORY_PATH


# ---------------------------------------------------------------------------
# Rules file: load & save
# ---------------------------------------------------------------------------

def load_rules(path: str = DEFAULT_RULES_PATH) -> dict:
    """
    Load quality rules from disk. Returns default empty structure if not found.

    Rules structure:
    {
        "merge_usernames": [
            {
                "canonical": "preferred_username",
                "aliases": ["old_name_1", "old_name_2"]
            }
        ],
        "score_corrections": [
            {
                "season": 2024,
                "week": 7,
                "display_name": "username",
                "corrected_score": 134.56,
                "note": "optional reason"
            }
        ]
    }
    """
    if not os.path.exists(path):
        return {"merge_usernames": [], "score_corrections": []}
    with open(path, "r") as f:
        return json.load(f)


def save_rules(rules: dict, path: str = DEFAULT_RULES_PATH) -> None:
    """Save quality rules to disk."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(rules, f, indent=2)
    print(f"  Rules saved to {path}")


# ---------------------------------------------------------------------------
# Rule: merge_usernames
# ---------------------------------------------------------------------------

def merge_usernames(history: dict, merge_rules: list[dict]) -> tuple[dict, list[str]]:
    """
    Rename any alias username to its canonical name throughout all history.

    Args:
        history:      Full history dict (not modified in place — returns a copy)
        merge_rules:  List of {"canonical": str, "aliases": [str, ...]} dicts

    Returns:
        (updated history dict, list of change log strings)
    """
    if not merge_rules:
        return history, []

    # Build a flat alias -> canonical lookup
    alias_map: dict[str, str] = {}
    for rule in merge_rules:
        canonical = rule["canonical"]
        for alias in rule.get("aliases", []):
            if alias != canonical:
                alias_map[alias] = canonical

    if not alias_map:
        return history, []

    history = deepcopy(history)
    change_log = []

    def remap(name: str) -> str:
        return alias_map.get(name, name)

    for season_key, season_data in history.items():
        for week_key, week_data in season_data.get("weeks", {}).items():

            # Remap matchups
            for m in week_data.get("matchups", []):
                for side in ("home", "away"):
                    old = m[side].get("display_name")
                    new = remap(old)
                    if old != new:
                        m[side]["display_name"] = new
                        m[side]["team_name"] = new
                        change_log.append(
                            f"  Season {season_key} Week {week_key} "
                            f"[{side}]: '{old}' -> '{new}'"
                        )
                # Remap winner field
                old_winner = m.get("winner")
                if old_winner:
                    m["winner"] = remap(old_winner)

            # Remap byes
            for b in week_data.get("byes", []):
                old = b.get("display_name")
                new = remap(old)
                if old != new:
                    b["display_name"] = new
                    b["team_name"] = new
                    change_log.append(
                        f"  Season {season_key} Week {week_key} "
                        f"[bye]: '{old}' -> '{new}'"
                    )

    return history, change_log



# ---------------------------------------------------------------------------
# Rule: score_corrections
# ---------------------------------------------------------------------------

def apply_score_corrections(history: dict, correction_rules: list[dict]) -> tuple[dict, list[str]]:
    """
    Apply manual score corrections to stored matchup data.

    Corrections update the team's points value and recalculate the matchup
    margin. The winner field is also updated if the correction changes the
    outcome of the game.

    Args:
        history:          Full history dict (not modified in place)
        correction_rules: List of correction dicts:
                          {
                              "season": int,
                              "week": int,
                              "display_name": str,
                              "corrected_score": float,
                              "note": str (optional)
                          }

    Returns:
        (updated history dict, list of change log strings)
    """
    if not correction_rules:
        return history, []

    history = deepcopy(history)
    change_log = []

    for rule in correction_rules:
        season_key = str(rule["season"])
        week_key   = str(rule["week"])
        name       = rule["display_name"]
        new_score  = float(rule["corrected_score"])
        note       = rule.get("note", "")

        week_data = (
            history
            .get(season_key, {})
            .get("weeks", {})
            .get(week_key)
        )
        if not week_data:
            change_log.append(
                f"  [WARN] Season {season_key} Week {week_key}: "
                f"week not found in history — skipping correction for '{name}'"
            )
            continue

        corrected = False
        for m in week_data.get("matchups", []):
            for side, other_side in (("home", "away"), ("away", "home")):
                if m[side]["display_name"] == name:
                    old_score = m[side]["points"]
                    m[side]["points"] = old_score+new_score

                    # Recalculate margin and winner
                    home_pts = m["home"]["points"]
                    away_pts = m["away"]["points"]
                    m["margin"] = round(abs(home_pts - away_pts), 2)

                    # Swap home/away if score order changed
                    if away_pts > home_pts:
                        m["home"], m["away"] = m["away"], m["home"]

                    m["winner"] = m["home"]["display_name"]

                    note_str = f" ({note})" if note else ""
                    change_log.append(
                        f"  Season {season_key} Week {week_key} "
                        f"'{name}': {old_score:.2f} + {new_score:.2f} = {old_score + new_score:.2f}{note_str}"
                    )
                    corrected = True
                    break
            if corrected:
                break

        # Check byes too
        if not corrected:
            for b in week_data.get("byes", []):
                if b["display_name"] == name:
                    old_score = b["points"]
                    b["points"] = old_score + new_score
                    note_str = f" ({note})" if note else ""
                    change_log.append(
                        f"  Season {season_key} Week {week_key} "
                        f"'{name}' [bye]: {old_score:.2f} + {new_score:.2f} = {old_score + new_score:.2f}{note_str}"
                    )
                    corrected = True
                    break

        if not corrected:
            change_log.append(
                f"  [WARN] Season {season_key} Week {week_key}: "
                f"'{name}' not found in matchups or byes — skipping"
            )

    return history, change_log


def add_score_correction(
    rules: dict,
    season: int,
    week: int,
    display_name: str,
    corrected_score: float,
    note: str = "",
) -> dict:
    """
    Add a score correction rule. If a correction for the same
    season/week/user already exists, it will be overwritten.
    """
    corrections = rules.setdefault("score_corrections", [])

    # Remove any existing correction for same season/week/user
    rules["score_corrections"] = [
        c for c in corrections
        if not (c["season"] == season and c["week"] == week and c["display_name"] == display_name)
    ]

    rules["score_corrections"].append({
        "season": season,
        "week": week,
        "display_name": display_name,
        "corrected_score": corrected_score,
        "note": note,
    })
    return rules


def list_score_corrections(rules: dict) -> None:
    """Print all current score correction rules to console."""
    corrections = rules.get("score_corrections", [])
    if not corrections:
        print("  No score corrections defined.")
        return
    print()
    print(f"  {'Season':<8} {'Week':<6} {'Username':<22} {'Corrected Score':<18} Note")
    print(f"  {'-'*8} {'-'*6} {'-'*22} {'-'*18} {'-'*20}")
    for c in sorted(corrections, key=lambda x: (x["season"], x["week"])):
        print(
            f"  {c['season']:<8} {c['week']:<6} {c['display_name']:<22} "
            f"{c['corrected_score']:<18.2f} {c.get('note', '')}"
        )
    print()



# ---------------------------------------------------------------------------
# Rule: purge_zero_weeks
# ---------------------------------------------------------------------------

def purge_zero_weeks(history: dict) -> tuple[dict, list[str]]:
    """
    Remove any stored weeks where all scores are 0.
    These are weeks that were fetched before games were played.
    This rule runs automatically as part of apply_all_rules.
    """
    from copy import deepcopy
    history    = deepcopy(history)
    change_log = []

    for season_key, season_data in history.items():
        weeks_to_remove = []
        for week_key, week_data in season_data.get("weeks", {}).items():
            all_points = []
            for m in week_data.get("matchups", []):
                all_points.append(m["home"].get("points") or 0)
                all_points.append(m["away"].get("points") or 0)
            for b in week_data.get("byes", []):
                all_points.append(b.get("points") or 0)

            if all_points and all(p == 0 for p in all_points):
                weeks_to_remove.append(week_key)

        for week_key in weeks_to_remove:
            del season_data["weeks"][week_key]
            change_log.append(
                f"  Season {season_key} Week {week_key}: removed (all scores were 0)"
            )

    return history, change_log


# ---------------------------------------------------------------------------
# Apply all rules
# ---------------------------------------------------------------------------

def apply_all_rules(history: dict, rules: dict) -> tuple[dict, dict[str, list[str]]]:
    """
    Apply all quality rules in sequence and return the cleaned history.

    Args:
        history:  Full history dict
        rules:    Rules dict from load_rules()

    Returns:
        (cleaned history dict, dict mapping rule_name -> list of changes made)
    """
    all_changes: dict[str, list[str]] = {}

    # Rule 1: merge usernames
    merge_rules = rules.get("merge_usernames", [])
    history, changes = merge_usernames(history, merge_rules)
    all_changes["merge_usernames"] = changes

    # Rule 2: score corrections
    correction_rules = rules.get("score_corrections", [])
    history, changes = apply_score_corrections(history, correction_rules)
    all_changes["score_corrections"] = changes

    # Rule 3: purge zero-score weeks (games not yet played)
    history, changes = purge_zero_weeks(history)
    all_changes["purge_zero_weeks"] = changes

    return history, all_changes


# ---------------------------------------------------------------------------
# Rule management helpers
# ---------------------------------------------------------------------------

def add_merge_rule(
    rules: dict,
    canonical: str,
    aliases: list[str],
) -> dict:
    """
    Add or update a merge rule for a canonical username.
    If a rule for this canonical already exists, merges the alias lists.

    Args:
        rules:      Existing rules dict
        canonical:  The username to keep
        aliases:    List of old usernames to map to canonical

    Returns:
        Updated rules dict
    """
    existing = rules.setdefault("merge_usernames", [])

    # Find existing rule for this canonical if any
    for rule in existing:
        if rule["canonical"] == canonical:
            merged = list(set(rule["aliases"]) | set(aliases) - {canonical})
            rule["aliases"] = sorted(merged)
            return rules

    # No existing rule — add new one
    existing.append({
        "canonical": canonical,
        "aliases": sorted(set(aliases) - {canonical}),
    })
    return rules


def list_merge_rules(rules: dict) -> None:
    """Print all current merge rules to console."""
    merge_rules = rules.get("merge_usernames", [])
    if not merge_rules:
        print("  No merge rules defined.")
        return
    print()
    print(f"  {'Canonical':<25} Aliases")
    print(f"  {'-'*25} {'-'*35}")
    for rule in merge_rules:
        aliases = ", ".join(rule.get("aliases", []))
        print(f"  {rule['canonical']:<25} {aliases}")
    print()


def scan_usernames(history: dict) -> list[str]:
    """
    Scan all history and return a sorted list of every unique username found.
    Useful for spotting duplicates or old aliases before writing merge rules.
    """
    names = set()
    for season_data in history.values():
        for week_data in season_data.get("weeks", {}).values():
            for m in week_data.get("matchups", []):
                names.add(m["home"]["display_name"])
                names.add(m["away"]["display_name"])
            for b in week_data.get("byes", []):
                names.add(b["display_name"])
    return sorted(names)


# ---------------------------------------------------------------------------
# Load & save cleaned history
# ---------------------------------------------------------------------------

def load_history(path: str = DEFAULT_HISTORY_PATH) -> dict:
    """Load raw history from disk."""
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)





# ---------------------------------------------------------------------------
# Main: interactive runner
# ---------------------------------------------------------------------------

def main():
    print("\n--- Sleeper Fantasy Football | Phase 3.5: Data Quality ---\n")

    history = load_history()
    rules = load_rules()

    if not history:
        print("  No history found. Run history.py first.")
        return

    while True:
        print("  What would you like to do?")
        print("    [1] Scan all usernames in history")
        print("    [2] Add a username merge rule")
        print("    [3] View current merge rules")
        print("    [4] Add a score correction")
        print("    [5] View current score corrections")
        print("    [6] Preview what rules would change")
        print("    [q] Quit")
        print()
        print("  Note: rules are applied automatically at runtime by all")
        print("  other modules — history.json is never modified directly.")

        choice = input("\n  Select option: ").strip().lower()

        if choice == "1":
            names = scan_usernames(history)
            print(f"\n  {len(names)} unique usernames found:\n")
            for name in names:
                print(f"    {name}")

        elif choice == "2":
            canonical = input("  Canonical username (the one to keep): ").strip()
            aliases_input = input("  Aliases to merge in (comma separated): ").strip()
            aliases = [a.strip() for a in aliases_input.split(",") if a.strip()]
            if not aliases:
                print("  No aliases entered.")
            else:
                rules = add_merge_rule(rules, canonical, aliases)
                save_rules(rules)
                print(f"  Rule added: {aliases} -> '{canonical}'")

        elif choice == "3":
            list_merge_rules(rules)

        elif choice == "4":
            season_input = input("  Season: ").strip()
            week_input   = input("  Week: ").strip()
            name         = input("  Username: ").strip()
            score_input  = input("  Corrected score: ").strip()
            note         = input("  Note (optional): ").strip()
            if not (season_input.isdigit() and week_input.isdigit() and name and score_input):
                print("  Invalid input — season, week, username and score are required.")
            else:
                try:
                    rules = add_score_correction(
                        rules,
                        season=int(season_input),
                        week=int(week_input),
                        display_name=name,
                        corrected_score=float(score_input),
                        note=note,
                    )
                    save_rules(rules)
                    print(f"  Correction added: {name} Season {season_input} Week {week_input} -> {float(score_input):.2f}")
                except ValueError:
                    print("  Invalid score value.")

        elif choice == "5":
            list_score_corrections(rules)

        elif choice in ("6", "7"):
            _, all_changes = apply_all_rules(history, rules)
            total = sum(len(v) for v in all_changes.values())

            if total == 0:
                print("  No changes to apply.")
            else:
                print(f"\n  {total} change(s) would be made:\n")
                for rule_name, changes in all_changes.items():
                    if changes:
                        print(f"  [{rule_name}]")
                        for c in changes:
                            print(c)

                if choice == "5":
                    confirm = input(f"\n  Apply and save {total} change(s)? [y/N]: ").strip().lower()
                    if confirm == "y":
                        cleaned_history, _ = apply_all_rules(history, rules)
                        save_history(cleaned_history)
                        print("  Done — cleaned history saved.")
                    else:
                        print("  Cancelled.")

        elif choice == "q":
            print("  Exiting.")
            break

        else:
            print("  Invalid option.")
        
        print()


if __name__ == "__main__":
    main()
