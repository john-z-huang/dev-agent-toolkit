import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from dev_agent_toolkit_tools.services import workflows

from codex_session_fixtures import ROOT

SKILL = ROOT / "skills" / "dev-agent-toolkit"


class GitHubDraftFilesTests(unittest.TestCase):
    def test_create_and_check_title_with_body_for_issue_and_pr(self):
        with tempfile.TemporaryDirectory(prefix="draft files ") as temp:
            for kind in ("issue", "pr"):
                with self.subTest(kind=kind):
                    body = Path(temp) / f"{kind}.md"
                    title = body.with_suffix(".title.txt")
                    command = [sys.executable, str(SKILL / "scripts" / "github_draft.py")]
                    create = [*command, "create", kind, str(body)]
                    check = [*command, "check", kind, str(body)]
                    result = subprocess.run(create, capture_output=True, text=True, check=True)
                    self.assertEqual(result.stdout.splitlines(), [str(body), str(title)])
                    self.assertEqual(title.read_bytes(), b"")
                    template = (SKILL / "assets" / f"{kind}.md").read_bytes()
                    self.assertEqual(body.read_bytes(), template)
                    body.write_text(
                        "\n\n".join(
                            f"{line}\n\n{'Closes #12' if line == '## 关联 Issue' else '已核对的说明。'}"
                            for line in template.decode("utf-8").splitlines()
                            if line.startswith("## ")
                        ),
                        encoding="utf-8",
                    )
                    result = subprocess.run(check, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("标题文件", result.stderr)
                    title.write_text("定稿标题\n", encoding="utf-8")
                    subprocess.run(check, capture_output=True, check=True)

                    body.unlink()
                    result = subprocess.run(create, capture_output=True)
                    self.assertEqual(result.returncode, 1)
                    self.assertFalse(body.exists())
                    self.assertEqual(title.read_text(encoding="utf-8"), "定稿标题\n")


class GitHubBodyFileTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory(prefix="草稿 with spaces "))
        self.root = Path(directory)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.enterContext(
            patch.object(
                workflows, "_validated_repo_path", return_value=(str(self.repo), None)
            )
        )
        self.title = self.root / "reviewed title.txt"
        self.title.write_bytes("已审阅的标题\r\n".encode("utf-8"))
        self.create_args = {
            "repo_path": str(self.repo),
            "repo": "owner/repo",
            "title_file": str(self.title),
        }

    def test_issue_and_pr_send_exact_bytes_from_the_draft(self):
        body = "## 变更说明\r\n正文有中文。\r\n\r\nCloses #12\r\n".encode("utf-8")
        draft = self.root / "reviewed draft.md"
        draft.write_bytes(body)
        uploads = {}

        def run(args, *, cwd):
            self.assertEqual(cwd, str(self.repo))
            if args[0] == "git":
                return CompletedProcess(args, 0, "")
            self.assertEqual(args[2], "create")
            self.assertEqual(args[args.index("--title") + 1], "已审阅的标题")
            self.assertNotIn("--body", args)
            upload = Path(args[args.index("--body-file") + 1])
            self.assertEqual(upload.read_bytes(), body)
            uploads[args[1]] = upload
            resource = "issues/12" if args[1] == "issue" else "pull/13"
            return CompletedProcess(args, 0, f"https://github.com/owner/repo/{resource}")

        issue = {
            "state": "OPEN",
            "labels": [{"name": "bug"}],
            "assignees": [{"login": "tester"}],
        }
        pr = {
            "state": "OPEN",
            "baseRefName": "main",
            "headRefName": "fix/synthetic",
            "body": body.decode("utf-8"),
            "assignees": issue["assignees"],
        }
        with (
            patch.object(workflows, "_issue_label_error", return_value=None),
            patch.object(workflows, "_gh_current_login", return_value=("tester", None)),
            patch.object(
                workflows, "_gh_object", side_effect=[(issue, None), (issue, None), (pr, None)]
            ),
            patch.object(workflows, "_run_fixed", side_effect=run),
        ):
            result = workflows.create_github_issue(
                **self.create_args, body_file=str(draft), labels=["bug"]
            )
            self.assertTrue(result["ok"], result)
            result = workflows.create_github_pull_request(
                **self.create_args,
                body_file=str(draft),
                base_branch="main",
                head_branch="fix/synthetic",
                issue_number=12,
            )
            self.assertTrue(result["ok"], result)

        self.assertEqual(set(uploads), {"issue", "pr"})
        self.assertTrue(all(not path.exists() for path in uploads.values()))
        self.assertEqual(draft.read_bytes(), body)

    def test_invalid_drafts_and_wrong_issue_reference_stop_before_gh(self):
        draft = self.root / "reviewed.md"
        empty = self.root / "empty.md"
        empty.write_bytes(b" \r\n")
        bad_encoding = self.root / "bad-encoding.md"
        bad_encoding.write_bytes(b"\xff")
        with (
            patch.object(workflows, "_issue_label_error") as labels,
            patch.object(workflows, "_gh_current_login") as login,
            patch.object(workflows, "_gh_object") as gh,
            patch.object(workflows, "_run_fixed") as run,
        ):
            for invalid in ("relative.md", str(draft), str(empty), str(bad_encoding)):
                with self.subTest(body_file=invalid):
                    result = workflows.create_github_issue(
                        **self.create_args, body_file=invalid, labels=["bug"]
                    )
                    self.assertFalse(result["created"])
                    self.assertIn("body_file", result["error"])
            draft.write_text("Closes #21", encoding="utf-8")
            result = workflows.create_github_pull_request(
                **self.create_args,
                body_file=str(draft),
                base_branch="main",
                head_branch="fix/synthetic",
                issue_number=12,
            )
            self.assertFalse(result["created"])
            self.assertIn("Closes/Fixes/Resolves #12", result["error"])
            self.title.write_text("第一行\n第二行", encoding="utf-8")
            result = workflows.create_github_issue(
                **self.create_args, body_file=str(draft), labels=["bug"]
            )
            self.assertFalse(result["created"])
            self.assertIn("title_file", result["error"])
        labels.assert_not_called()
        login.assert_not_called()
        gh.assert_not_called()
        run.assert_not_called()
