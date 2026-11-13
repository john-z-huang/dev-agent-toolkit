"""使用临时 Git 仓库验证共享清理的精确 OID 门禁，不访问网络。"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dev_workflow_standards_tools.infrastructure import gitlab_cli
from dev_workflow_standards_tools.services import gitlab_repository, validation


class GitLabCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Synthetic")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.root / "base").write_text("baseline\n")
        self.git("add", "base")
        self.git("commit", "-qm", "baseline")
        self.git("switch", "-qc", "feat/demo")
        (self.root / "feature").write_text("feature\n")
        self.git("add", "feature")
        self.git("commit", "-qm", "feature")
        self.head = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("switch", "-q", "main")
        self.git("merge", "--squash", "feat/demo")
        self.git("commit", "-qm", "squashed")
        self.git("remote", "add", "origin", "git@gitlab.example.com:team/project.git")
        self.original_run = validation._run_fixed

    def git(self, *arguments):
        return subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        )

    def command(self, args, **kwargs):
        if args[:2] == ["git", "pull"]:
            self.assertEqual(args, ["git", "pull", "--ff-only", "origin", "main"])
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "glab":
            self.assertEqual(args[4:6], ["--method", "GET"])
            project = {"id": 10}
            mr = {
                "iid": 8,
                "state": "merged",
                "merged_at": "2026-01-01",
                "target_branch": "main",
                "source_branch": "feat/demo",
                "source_project_id": 10,
                "target_project_id": 10,
            }
            value = mr if args[6].endswith("/merge_requests/8") else project
            return subprocess.CompletedProcess(args, 0, json.dumps(value), "")
        return self.original_run(args, **kwargs)

    def cleanup(self, oid):
        with (
            patch.object(gitlab_cli, "_run_fixed", side_effect=self.command),
            patch.object(validation, "_run_fixed", side_effect=self.command),
        ):
            return gitlab_repository.cleanup_merged_mr_local_branch(
                str(self.root),
                "gitlab.example.com/team/project",
                8,
                merged_head_oid=oid,
            )

    def test_squash_cleanup_requires_exact_premerge_oid(self):
        result = self.cleanup(self.head)
        self.assertTrue(result["completed"], result)
        remaining = self.git("branch", "--list", "feat/demo").stdout
        self.assertEqual(remaining, "")
        self.assertIn("exact OID verification", result["actions"][-1])

    def test_missing_oid_keeps_squashed_source_branch(self):
        result = self.cleanup(None)
        self.assertFalse(result["completed"], result)
        self.assertEqual(
            self.git("rev-parse", "refs/heads/feat/demo").stdout.strip(), self.head
        )

    def test_wrong_oid_keeps_squashed_source_branch(self):
        result = self.cleanup("b" * 40)
        self.assertFalse(result["completed"], result)
        self.assertEqual(
            self.git("rev-parse", "refs/heads/feat/demo").stdout.strip(), self.head
        )

    def test_github_cleanup_preserves_existing_success_fields(self):
        info = {"state": "MERGED", "baseRefName": "main", "headRefName": "feat/demo"}
        with (
            patch.object(
                validation,
                "_cleanup_pr_preflight",
                return_value=(str(self.root), info, None),
            ),
            patch.object(validation, "_run_fixed", side_effect=self.command),
        ):
            result = validation.cleanup_merged_pr_local_branch(
                str(self.root), 8, "owner/project", merged_head_oid=self.head
            )
        self.assertTrue(result["completed"], result)
        self.assertEqual((result["repo"], result["pr_number"]), ("owner/project", 8))


if __name__ == "__main__":
    unittest.main()
