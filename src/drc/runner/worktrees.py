"""Isolated Git worktree lanes for speculative agent candidates."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import subprocess


@dataclass(frozen=True)
class WorkspaceLane:
    model: str
    path: Path
    revision: str


class WorktreeLaneManager:
    """Create read/write candidate lanes without sharing a checkout.

    The manager never applies a candidate patch to the source checkout.  The
    caller elects a model, retrieves its patch, verifies it, and explicitly
    decides how to apply it. Cleanup is limited to worktrees created by this
    manager under its configured root.
    """

    def __init__(self, repo: Path, root: Path, revision: str = "HEAD"):
        self.repo = repo.resolve()
        self.root = root.resolve()
        self.revision = revision
        self._lanes: dict[str, WorkspaceLane] = {}
        if not (self.repo / ".git").exists():
            raise ValueError(f"not a Git repository: {self.repo}")

    @staticmethod
    def _slug(model: str) -> str:
        readable = re.sub(r"[^a-z0-9]+", "-", model.casefold()).strip("-")[:36]
        digest = hashlib.sha256(model.encode()).hexdigest()[:8]
        return f"{readable or 'candidate'}-{digest}"

    def prepare(self, model: str) -> WorkspaceLane:
        if model in self._lanes:
            return self._lanes[model]
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / self._slug(model)
        if path.exists():
            raise RuntimeError(f"candidate lane already exists: {path}")
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(path), self.revision],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        )
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=path, text=True
        ).strip()
        lane = WorkspaceLane(model=model, path=path, revision=revision)
        self._lanes[model] = lane
        return lane

    def patch(self, model: str) -> str:
        lane = self._lanes.get(model)
        if lane is None:
            raise KeyError(f"unknown candidate lane: {model}")
        return subprocess.check_output(
            ["git", "diff", "--binary", "--no-ext-diff"],
            cwd=lane.path,
            text=True,
        )

    def cleanup(self, model: str) -> None:
        lane = self._lanes.pop(model, None)
        if lane is None:
            return
        try:
            lane.path.relative_to(self.root)
        except ValueError as exc:
            raise RuntimeError("refusing to remove a lane outside the managed root") from exc
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(lane.path)],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        )

    def cleanup_all(self) -> None:
        for model in list(self._lanes):
            self.cleanup(model)
