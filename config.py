"""
config.py
---------
Shared paths and run-mode helpers used by every module.

Run modes
    Interactive (default when you run things by hand): missing inputs are
    asked for with prompts, exactly as before.
    Non-interactive (GitHub Actions): any missing input raises an error
    instead of waiting for someone to type. Triggered by either
        - the CI environment variable (GitHub Actions sets CI=true), or
        - SLEEPER_NONINTERACTIVE=1, or
        - the --non-interactive flag on weekly_runner.py

Paths
    data/  stays next to the scripts (unchanged from before).
    docs/  is created at the REPO ROOT (the folder containing .git), so
           GitHub Pages can serve it. Override with SLEEPER_DOCS_DIR.
"""

import os
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def _find_repo_root() -> Path:
    for p in (SCRIPT_DIR, *SCRIPT_DIR.parents):
        if (p / ".git").exists():
            return p
    return SCRIPT_DIR


REPO_ROOT  = _find_repo_root()
DATA_DIR   = SCRIPT_DIR / "data"
DOCS_DIR   = Path(os.environ.get("SLEEPER_DOCS_DIR", REPO_ROOT / "docs"))
IMAGES_DIR = DOCS_DIR / "images"
FONT_DIR   = SCRIPT_DIR / "fonts"          # optional: drop .ttf files here

HISTORY_PATH = str(DATA_DIR / "history.json")
RULES_PATH   = str(DATA_DIR / "quality_rules.json")

_force_non_interactive = False


def set_non_interactive(value: bool = True) -> None:
    global _force_non_interactive
    _force_non_interactive = value


def is_interactive() -> bool:
    if _force_non_interactive:
        return False
    if os.environ.get("CI") or os.environ.get("SLEEPER_NONINTERACTIVE"):
        return False
    return True


def ask(prompt: str) -> str:
    """input() when running by hand; a clear error when running unattended."""
    if not is_interactive():
        raise RuntimeError(
            f"Input required but running non-interactively: {prompt.strip()!r}. "
            "Supply it via a command-line argument or environment variable."
        )
    return input(prompt)


def stamp() -> str:
    """
    Timestamp used in output filenames. With SLEEPER_STABLE_NAMES=1 (set by
    weekly_runner when it publishes to docs/) this returns 'latest', so each
    week's files overwrite last week's instead of piling up in the repo.
    """
    if os.environ.get("SLEEPER_STABLE_NAMES"):
        return "latest"
    return datetime.now().strftime("%Y%m%d_%H%M%S")
