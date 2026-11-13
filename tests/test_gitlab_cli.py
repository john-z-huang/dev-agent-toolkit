"""GitLab CLI 的显式范围、固定请求与脱敏边界。"""

import json
import subprocess
import unittest
from unittest.mock import patch

from dev_workflow_standards_tools.infrastructure import gitlab_cli as cli


class GitLabCLITests(unittest.TestCase):
    def test_nested_project_is_encoded_and_host_is_explicit(self):
        with patch.object(
            cli, "_validated_repo_path", return_value=("/workspace/repo", None)
        ):
            context = cli.gitlab_context(
                "/workspace/repo", "gitlab.example.com/team/sub/project"
            )
        response = subprocess.CompletedProcess([], 0, '{"iid":7}', "")
        body = {"description": "中文\n`touch x` $(secret)\nCloses #7"}
        with patch.object(cli, "_run_fixed", return_value=response) as run:
            value = cli.gitlab_object(context, "/issues", method="POST", payload=body)
        self.assertEqual(value, {"iid": 7})
        self.assertEqual(
            run.call_args.args[0],
            [
                "glab",
                "api",
                "--hostname",
                "gitlab.example.com",
                "--method",
                "POST",
                "projects/team%2Fsub%2Fproject/issues",
                "--input",
                "-",
            ],
        )
        self.assertEqual(json.loads(run.call_args.kwargs["input_text"]), body)
        self.assertEqual(run.call_args.kwargs["cwd"], "/workspace/repo")

    def test_invalid_repo_is_rejected_before_any_command(self):
        invalid = [
            "team/project",
            "https://gitlab.example.com/team/project",
            "gitlab.example.com/team/../project",
            "gitlab.example.com/team/project.git",
            "user:secret@gitlab.example.com/team/project",
            "-host/team/project",
            "gitlab.example.com/team/project?token=secret",
        ]
        with (
            patch.object(cli, "_run_fixed") as run,
            patch.object(cli, "_validated_repo_path") as validate,
        ):
            for repo in invalid:
                with self.subTest(repo=repo), self.assertRaises(ValueError):
                    cli.gitlab_context("/workspace/repo", repo)
        run.assert_not_called()
        validate.assert_not_called()

    def test_host_with_port_is_rejected_before_cli(self):
        with (
            patch.object(cli, "_validated_repo_path") as validate,
            patch.object(cli, "_run_fixed") as run,
            self.assertRaisesRegex(ValueError, "host 不含端口"),
        ):
            cli.gitlab_context(
                "/workspace/repo", "gitlab.example.com:8443/team/project"
            )
        validate.assert_not_called()
        run.assert_not_called()

    def test_read_requests_explicit_get_and_errors_do_not_echo_output(self):
        context = cli.GitLabContext(
            "/workspace/repo", "gitlab.example.com", "team/project"
        )
        response = subprocess.CompletedProcess(
            [], 1, "synthetic-secret", "synthetic-secret"
        )
        with (
            patch.object(cli, "_run_fixed", return_value=response) as run,
            self.assertRaises(ValueError) as caught,
        ):
            cli.gitlab_object(context, "/issues/7")
        self.assertNotIn("synthetic-secret", str(caught.exception))
        self.assertEqual(run.call_args.args[0][4:6], ["--method", "GET"])

    def test_invalid_json_shape_and_missing_glab_fail_closed(self):
        context = cli.GitLabContext(
            "/workspace/repo", "gitlab.example.com", "team/project"
        )
        for output in ("not-json", "null", "[]"):
            with (
                self.subTest(output=output),
                patch.object(
                    cli,
                    "_run_fixed",
                    return_value=subprocess.CompletedProcess([], 0, output, ""),
                ),
                self.assertRaises(ValueError),
            ):
                cli.gitlab_object(context)
        with (
            patch.object(
                cli, "_run_fixed", side_effect=FileNotFoundError("synthetic-secret")
            ),
            self.assertRaisesRegex(ValueError, "glab 不可用"),
        ):
            cli.gitlab_object(context)

    def test_origin_includes_every_push_url(self):
        context = cli.GitLabContext(
            "/workspace/repo", "gitlab.example.com", "team/sub/project"
        )
        fetch = subprocess.CompletedProcess(
            [], 0, "git@gitlab.example.com:team/sub/project.git\n", ""
        )
        push = subprocess.CompletedProcess(
            [], 0, "https://gitlab.example.com/team/sub/project.git\n", ""
        )
        with patch.object(cli, "_run_fixed", side_effect=[fetch, push]):
            cli.require_origin(context)
        push.stdout += "https://other.example.com/team/sub/project.git\n"
        with (
            patch.object(cli, "_run_fixed", side_effect=[fetch, push]),
            self.assertRaisesRegex(ValueError, "origin"),
        ):
            cli.require_origin(context)


if __name__ == "__main__":
    unittest.main()
