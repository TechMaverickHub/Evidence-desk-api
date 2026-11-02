"""Where a run came from: the code version and the machine, recorded with every result."""

import os
import platform
import subprocess

from app.evaluation.records import GitState

# Reports are written by runs, so their own changes must not mark the code as dirty.
_IGNORED_FOR_DIRTY = ":(exclude)eval/reports"


def git_state() -> GitState:
    try:
        sha = _git("rev-parse", "HEAD")
        changes = _git(
            "status", "--porcelain", "--untracked-files=no", "--", ".", _IGNORED_FOR_DIRTY
        )
    except (OSError, subprocess.CalledProcessError):
        return GitState(sha="unknown", dirty=None)
    return GitState(sha=sha, dirty=bool(changes))


def environment(postgres_version: str) -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "os": platform.platform(terse=True),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": str(os.cpu_count()),
        "postgres": postgres_version,
    }


def _git(*args: str) -> str:
    # Fixed arguments only; nothing from user input reaches the command line.
    completed = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
    return completed.stdout.strip()
