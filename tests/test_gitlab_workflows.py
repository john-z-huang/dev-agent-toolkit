"""固定 glab API 的工作流与失败关闭测试，不访问真实远端。"""

import json
import subprocess
import unittest
from unittest.mock import patch

from dev_workflow_standards_tools.infrastructure import gitlab_cli as cli
from dev_workflow_standards_tools.services import gitlab_issues as issues
from dev_workflow_standards_tools.services import gitlab_merge_requests as mrs
from dev_workflow_standards_tools.services import gitlab_repository as repos

REPO = "gitlab.example.com/team/sub/project"
ROOT = "/workspace/repo"
SHA = "a" * 40
USER = {"id": 5, "username": "fixture"}
ISSUE = {"iid": 7, "state": "opened", "labels": ["feature"], "assignees": [USER]}
MR = {
    "iid": 8,
    "state": "opened",
    "source_branch": "feat/demo",
    "target_branch": "main",
    "description": "Closes #7",
    "assignees": [USER],
    "sha": SHA,
    "draft": False,
    "has_conflicts": False,
    "detailed_merge_status": "mergeable",
    "head_pipeline": {"status": "success", "sha": SHA},
    "source_project_id": 10,
    "target_project_id": 10,
}
PROJECT = {"id": 10, "merge_method": "merge", "squash_option": "default_off"}


def completed(output="", code=0):
    return subprocess.CompletedProcess([], code, output, "")


class GitLabWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.path_patch = patch.object(
            cli, "_validated_repo_path", return_value=(ROOT, None)
        )
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.calls = []
        self.responses = {}
        self.cli_patch = patch.object(cli, "_run_fixed", side_effect=self.command)
        self.cli_patch.start()
        self.addCleanup(self.cli_patch.stop)

    def command(self, args, **kwargs):
        if args[:2] == ["git", "remote"]:
            return completed("git@gitlab.example.com:team/sub/project.git\n")
        self.assertEqual(args[:4], ["glab", "api", "--hostname", "gitlab.example.com"])
        self.calls.append((args[5], args[6], kwargs.get("input_text")))
        key = (args[5], args[6])
        value = self.responses.get(key)
        if value is None:
            self.fail(f"unexpected glab request: {key}")
        if isinstance(value, subprocess.CompletedProcess):
            return value
        return completed(json.dumps(value))

    def response(self, suffix, value, method="GET"):
        self.responses[(method, "projects/team%2Fsub%2Fproject" + suffix)] = value

    def setup_creation(self):
        self.responses[("GET", "user")] = USER
        self.response(
            "/labels?per_page=100&include_ancestor_groups=true", [{"name": "feature"}]
        )
        self.response("/issues/7", ISSUE)

    def setup_merge(self, mr=None, project=None):
        self.response("/merge_requests/8", MR if mr is None else mr)
        self.response("", PROJECT if project is None else project)

    def test_issue_create_assigns_current_user_and_reads_back(self):
        self.setup_creation()
        self.response("/issues", {"iid": 7}, "POST")
        result = issues.create_gitlab_issue(
            ROOT, REPO, "合成需求", "目标与验收\n$(secret)", ["feature"]
        )
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["created"])
        self.assertEqual(result["issue"]["assignees"], ["fixture"])
        post = next(call for call in self.calls if call[0] == "POST")
        self.assertEqual(json.loads(post[2])["assignee_ids"], [5])
        self.assertEqual(
            self.calls[-1][:2], ("GET", "projects/team%2Fsub%2Fproject/issues/7")
        )

    def test_issue_unknown_write_result_is_not_reported_as_not_created(self):
        self.setup_creation()
        self.response("/issues", completed("synthetic-secret", 1), "POST")
        result = issues.create_gitlab_issue(ROOT, REPO, "需求", "验收", ["feature"])
        self.assertFalse(result["ok"])
        self.assertIsNone(result["created"])
        self.assertTrue(result["write_attempted"])
        self.assertNotIn("synthetic-secret", json.dumps(result))
        self.assertEqual(sum(call[0] == "POST" for call in self.calls), 1)

    def test_unknown_label_stops_before_write(self):
        self.setup_creation()
        result = issues.create_gitlab_issue(ROOT, REPO, "需求", "验收", ["missing"])
        self.assertFalse(result["ok"])
        self.assertFalse(result["created"])
        self.assertTrue(all(call[0] == "GET" for call in self.calls))

    def test_issue_created_but_readback_fails_keeps_created_flag(self):
        self.setup_creation()
        self.response("/issues", {"iid": 7}, "POST")
        self.response("/issues/7", completed("", 1))
        result = issues.create_gitlab_issue(ROOT, REPO, "需求", "验收", ["feature"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["created"])
        self.assertEqual(result["issue_number"], 7)

    def test_malformed_assignees_fail_closed_after_creation(self):
        self.setup_creation()
        self.response("/issues", {"iid": 7}, "POST")
        self.response("/issues/7", {**ISSUE, "assignees": None})
        result = issues.create_gitlab_issue(ROOT, REPO, "需求", "验收", ["feature"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["created"])

    def test_mr_write_failure_is_unknown_and_not_retried(self):
        self.setup_creation()
        self.response("/merge_requests", completed("", 1), "POST")
        with patch.object(mrs, "_run_fixed", return_value=completed()):
            result = mrs.create_gitlab_merge_request(
                ROOT, REPO, "交付", "Closes #7", "main", "feat/demo", 7
            )
        self.assertFalse(result["ok"])
        self.assertIsNone(result["created"])
        self.assertEqual(sum(call[0] == "POST" for call in self.calls), 1)

    def test_mr_create_preserves_source_target_issue_and_assignee(self):
        self.setup_creation()
        self.response("/merge_requests", {"iid": 8}, "POST")
        self.response("/merge_requests/8", MR)
        with patch.object(mrs, "_run_fixed", return_value=completed()):
            result = mrs.create_gitlab_merge_request(
                ROOT, REPO, "交付", "Closes #7", "main", "feat/demo", 7
            )
        self.assertTrue(result["ok"], result)
        post = json.loads(next(call[2] for call in self.calls if call[0] == "POST"))
        self.assertEqual(
            (post["target_branch"], post["source_branch"]), ("main", "feat/demo")
        )
        self.assertFalse(post["remove_source_branch"])

    def test_created_mr_with_wrong_target_is_not_success(self):
        self.setup_creation()
        self.response("/merge_requests", {"iid": 8}, "POST")
        self.response("/merge_requests/8", {**MR, "target_branch": "other"})
        with patch.object(mrs, "_run_fixed", return_value=completed()):
            result = mrs.create_gitlab_merge_request(
                ROOT, REPO, "交付", "Closes #7", "main", "feat/demo", 7
            )
        self.assertFalse(result["ok"])
        self.assertTrue(result["created"])

    def test_audit_scopes_and_gitlab_state_fields(self):
        self.response("/issues/7", ISSUE)
        self.response("/merge_requests/8", MR)
        self.assertTrue(
            repos.audit_issue_mr_policy(ROOT, REPO, issue_number=7)["passed"]
        )
        self.assertTrue(
            repos.audit_issue_mr_policy(ROOT, REPO, 7, 8, "main", "feat/demo")["passed"]
        )
        self.assertFalse(
            repos.audit_issue_mr_policy(ROOT, REPO, 7, 8, "release")["passed"]
        )
        self.response("/merge_requests/8", {**MR, "description": "Closes #70"})
        self.assertFalse(repos.audit_issue_mr_policy(ROOT, REPO, 7, 8)["passed"])
        self.assertTrue(all(call[0] == "GET" for call in self.calls))

    def test_invalid_audit_request_makes_no_network_request(self):
        for kwargs in (
            {},
            {"mr_number": 0},
            {"issue_number": 7, "expected_base": "main"},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(
                    repos.audit_issue_mr_policy(ROOT, REPO, **kwargs)["passed"]
                )
        self.assertEqual(self.calls, [])

    def test_merge_guards_stop_before_any_write(self):
        cases = [
            ({"draft": True}, {}),
            ({"detailed_merge_status": "not_approved"}, {}),
            ({"has_conflicts": True}, {}),
            ({"head_pipeline": None}, {}),
            ({"head_pipeline": {"status": "failed", "sha": SHA}}, {}),
            ({"head_pipeline": {"status": "success", "sha": "b" * 40}}, {}),
            ({}, {"squash_option": "never"}),
            ({"sha": "invalid"}, {}),
        ]
        for changes, project_changes in cases:
            with self.subTest(changes=changes, project_changes=project_changes):
                self.setup_merge({**MR, **changes}, {**PROJECT, **project_changes})
                result = mrs.merge_gitlab_merge_request(ROOT, REPO, 8, "squash")
                self.assertFalse(result["ok"], result)
                self.assertFalse(result["write_attempted"])
        self.assertTrue(all(call[0] == "GET" for call in self.calls))

    def test_merge_binds_head_sha_and_reads_back_merged_state(self):
        self.setup_merge()
        self.response("/merge_requests/8/merge", {"state": "merged"}, "PUT")
        original_command = self.command

        def merging(args, **kwargs):
            value = original_command(args, **kwargs)
            if "PUT" in args:
                self.response(
                    "/merge_requests/8",
                    {**MR, "state": "merged", "merged_at": "2026-01-01"},
                )
            return value

        with patch.object(cli, "_run_fixed", side_effect=merging):
            result = mrs.merge_gitlab_merge_request(ROOT, REPO, 8, "squash")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["pre_merge_head_oid"], SHA)
        payload = json.loads(next(call[2] for call in self.calls if call[0] == "PUT"))
        self.assertEqual(
            payload,
            {
                "sha": SHA,
                "squash": True,
                "should_remove_source_branch": False,
                "auto_merge": False,
            },
        )

    def test_main_merge_and_project_method_conflicts_are_rejected(self):
        self.setup_merge()
        self.assertFalse(mrs.merge_gitlab_merge_request(ROOT, REPO, 8, "merge")["ok"])
        self.setup_merge({**MR, "target_branch": "release"})
        self.assertFalse(mrs.merge_gitlab_merge_request(ROOT, REPO, 8, "rebase")["ok"])
        self.assertTrue(all(call[0] == "GET" for call in self.calls))

    def test_failed_merge_is_unknown_and_not_retried(self):
        self.setup_merge()
        self.response("/merge_requests/8/merge", completed("", 1), "PUT")
        result = mrs.merge_gitlab_merge_request(ROOT, REPO, 8, "squash")
        self.assertFalse(result["ok"])
        self.assertIsNone(result["merged"])
        self.assertEqual(sum(call[0] == "PUT" for call in self.calls), 1)

    def test_issue_push_and_fork_push_keep_non_force_commands(self):
        self.setup_creation()
        with (
            patch.object(issues, "_current_branch", return_value="feat/demo"),
            patch.object(issues, "_require_clean_worktree", return_value=None),
            patch.object(issues, "_run_fixed", return_value=completed()) as run,
        ):
            result = issues.push_gitlab_issue_branch_to_origin(
                ROOT, REPO, "feat/demo", 7
            )
        self.assertTrue(result["ok"], result)
        self.assertEqual(run.call_args.args[0], ["git", "push", "origin", "feat/demo"])
        self.response(
            "", {**PROJECT, "default_branch": "main", "forked_from_project": {"id": 9}}
        )
        with (
            patch.object(repos, "_current_branch", return_value="main"),
            patch.object(repos, "_require_clean_worktree", return_value=None),
            patch.object(
                repos,
                "_run_fixed",
                side_effect=[completed("origin\nupstream\n"), completed(), completed()],
            ) as run,
        ):
            result = repos.push_gitlab_fork_main_fast_forward(ROOT, REPO)
        self.assertTrue(result["ok"], result)
        self.assertEqual(run.call_args.args[0], ["git", "push", "origin", "main"])

    def test_cleanup_rejects_cross_project_and_uses_shared_oid_logic(self):
        merged = {**MR, "state": "merged", "merged_at": "2026-01-01"}
        self.setup_merge(merged)
        with (
            patch.object(repos, "_require_clean_worktree", return_value=None),
            patch.object(
                repos,
                "_cleanup_local_branch",
                return_value={"completed": True, "actions": []},
            ) as cleanup,
        ):
            result = repos.cleanup_merged_mr_local_branch(
                ROOT, REPO, 8, merged_head_oid=SHA
            )
            self.assertTrue(result["completed"], result)
            self.assertEqual(
                cleanup.call_args.args,
                (
                    ROOT,
                    {
                        "state": "MERGED",
                        "baseRefName": "main",
                        "headRefName": "feat/demo",
                    },
                    None,
                    SHA,
                ),
            )
            cleanup.reset_mock()
            self.response("/merge_requests/8", {**merged, "source_project_id": 99})
            self.assertFalse(
                repos.cleanup_merged_mr_local_branch(ROOT, REPO, 8)["completed"]
            )
            cleanup.assert_not_called()

    def test_repository_audit_separates_local_success_and_remote_error(self):
        self.response("", completed("synthetic-secret", 1))
        with (
            patch.object(repos, "_current_branch", return_value="feat/demo"),
            patch.object(
                repos,
                "_run_fixed",
                side_effect=[completed("## feat/demo"), completed("origin")],
            ),
        ):
            result = repos.audit_gitlab_repository_state(ROOT, REPO)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["gitlab"])
        self.assertTrue(result["gitlab_error"])
        self.assertNotIn("synthetic-secret", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
