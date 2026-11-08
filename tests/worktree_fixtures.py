"""为同步与恢复测试提供独立的临时 Git 仓库，不包含测试用例。"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class WorktreeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="worktree sync synthetic ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def git(
        self, cwd: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
        )
        if check and result.returncode:
            self.fail(f"git {' '.join(args)} failed: {result.stderr}")
        return result

    def commit_file(self, repo: Path, name: str, content: str, message: str) -> str:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.git(repo, "add", "--", name)
        self.git(repo, "commit", "-m", message)
        return self.oid(repo, "HEAD")

    def oid(self, repo: Path, ref: str) -> str:
        return self.git(
            repo, "rev-parse", "--verify", f"{ref}^{{commit}}"
        ).stdout.strip()

    def init_remote(self) -> tuple[Path, Path, Path, str]:
        suffix = len(list(self.root.iterdir()))
        bare = self.root / f"origin-{suffix}.git"
        seed = self.root / f"main checkout {suffix}"
        topic = self.root / f"topic linked checkout {suffix}"
        bare.mkdir()
        seed.mkdir()
        topic.parent.mkdir(exist_ok=True)
        self.git(self.root, "init", "--bare", "-q", str(bare))
        self.git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
        self.git(seed, "init", "-q")
        self.git(seed, "config", "user.name", "Synthetic Fixture")
        self.git(seed, "config", "user.email", "fixture@example.invalid")
        baseline = self.commit_file(seed, "shared.txt", "baseline\n", "baseline")
        self.git(seed, "branch", "-M", "main")
        self.git(seed, "remote", "add", "origin", str(bare))
        self.git(seed, "push", "-u", "origin", "main")
        self.git(seed, "worktree", "add", "-b", "feat/topic", str(topic), "main")
        return bare, seed, topic, baseline

    def advance_main(
        self, seed: Path, *, name: str = "base.txt", content: str = "base update\n"
    ) -> str:
        self.git(seed, "checkout", "main")
        oid = self.commit_file(seed, name, content, "advance base")
        self.git(seed, "push", "origin", "main")
        return oid

    def add_topic_commit(
        self, topic: Path, *, name: str = "topic.txt", content: str = "topic work\n"
    ) -> str:
        return self.commit_file(topic, name, content, "topic work")
