from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass

from runtime_paths import get_repo_root

_GIT_TIMEOUT_SECONDS = 6


def _run_git(args: list[str], timeout: int = _GIT_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.run(
        ["git", *args],
        cwd=str(get_repo_root()),
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=creationflags,
    )


@dataclass
class UpdateCheckResult:
    update_available: bool
    branch: str = ""
    local_sha: str = ""
    remote_sha: str = ""
    error: str = ""


def is_git_checkout() -> bool:
    return (get_repo_root() / ".git").exists()


def check_for_update() -> UpdateCheckResult:
    """Read-only check: compares local HEAD against the remote branch tip.

    Never mutates the local checkout (no fetch/pull here) so it is safe to
    call from a background thread at startup.
    """
    if not is_git_checkout():
        return UpdateCheckResult(update_available=False, error="not a git checkout")

    try:
        branch_proc = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        if branch_proc.returncode != 0:
            return UpdateCheckResult(update_available=False, error=branch_proc.stderr.strip())
        branch = branch_proc.stdout.strip()
        if not branch or branch == "HEAD":
            return UpdateCheckResult(update_available=False, error="detached HEAD")

        local_proc = _run_git(["rev-parse", "HEAD"])
        if local_proc.returncode != 0:
            return UpdateCheckResult(update_available=False, error=local_proc.stderr.strip())
        local_sha = local_proc.stdout.strip()

        remote_proc = _run_git(["ls-remote", "origin", f"refs/heads/{branch}"])
        if remote_proc.returncode != 0:
            return UpdateCheckResult(update_available=False, error=remote_proc.stderr.strip())
        remote_line = remote_proc.stdout.strip()
        if not remote_line:
            return UpdateCheckResult(update_available=False, error="branch not found on origin")
        remote_sha = remote_line.split()[0]

        return UpdateCheckResult(
            update_available=remote_sha != local_sha,
            branch=branch,
            local_sha=local_sha,
            remote_sha=remote_sha,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return UpdateCheckResult(update_available=False, error=str(exc))


@dataclass
class UpdateResult:
    success: bool
    message: str
    requirements_changed: bool = False


def apply_update(branch: str) -> UpdateResult:
    """Pulls the latest changes and reinstalls requirements if they changed."""
    repo_root = get_repo_root()
    req_path = repo_root / "requirements.txt"
    req_before = str(req_path.read_text(encoding="utf-8")) if req_path.exists() else None

    try:
        status_proc = _run_git(["status", "--porcelain"])
        if status_proc.returncode == 0 and status_proc.stdout.strip():
            return UpdateResult(
                success=False,
                message="Local changes detected in the bot folder. Update aborted to avoid overwriting them.",
            )

        pull_proc = _run_git(["pull", "--ff-only", "origin", branch], timeout=60)
        if pull_proc.returncode != 0:
            return UpdateResult(success=False, message=pull_proc.stderr.strip() or pull_proc.stdout.strip())

        req_after = str(req_path.read_text(encoding="utf-8")) if req_path.exists() else None
        requirements_changed = req_before != req_after

        if requirements_changed and req_path.exists():
            pip_proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(req_path)],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=300,
            )
            if pip_proc.returncode != 0:
                return UpdateResult(
                    success=False,
                    message="Update pulled, but installing new dependencies failed:\n"
                    + (pip_proc.stderr.strip() or pip_proc.stdout.strip()),
                    requirements_changed=True,
                )

        return UpdateResult(success=True, message="Update installed successfully.", requirements_changed=requirements_changed)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return UpdateResult(success=False, message=str(exc))


def restart_application() -> None:
    python = sys.executable
    os.execv(python, [python] + sys.argv)
