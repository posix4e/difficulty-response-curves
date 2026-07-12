import subprocess

import pytest

from drc.runner.worktrees import WorktreeLaneManager


def run(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def test_candidate_worktrees_are_isolated_and_only_winner_patch_is_read(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run(repo, "init", "-q")
    run(repo, "config", "user.email", "test@example.com")
    run(repo, "config", "user.name", "Test")
    (repo / "answer.txt").write_text("base\n")
    run(repo, "add", "answer.txt")
    run(repo, "commit", "-qm", "base")

    manager = WorktreeLaneManager(repo, tmp_path / "lanes")
    glm = manager.prepare("or/glm-5")
    grok = manager.prepare("or/grok-4-fast")
    assert glm.path != grok.path
    assert glm.revision == grok.revision

    (glm.path / "answer.txt").write_text("glm\n")
    (grok.path / "answer.txt").write_text("grok\n")
    winner_patch = manager.patch("or/grok-4-fast")
    assert "+grok" in winner_patch
    assert "+glm" not in winner_patch
    assert (repo / "answer.txt").read_text() == "base\n"

    manager.cleanup_all()
    assert not glm.path.exists() and not grok.path.exists()


def test_worktree_manager_rejects_non_repo(tmp_path):
    with pytest.raises(ValueError, match="not a Git repository"):
        WorktreeLaneManager(tmp_path, tmp_path / "lanes")
