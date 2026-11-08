"""通过真实 stdin/stdout 和临时 Git 仓库核验原生 Hook 协议。"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "codex-hooks/runtime.py"
SETUP = ROOT / "scripts/setup-codex-hooks.py"
PREFIX = "mcp__dev_workflow_standards_tools__"


def run_hook(event: dict, runtime: Path = RUNTIME) -> dict:
    result = subprocess.run(
        [sys.executable, str(runtime)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def pre_tool(path: object, tool: str = PREFIX + "audit_repository_state") -> dict:
    return run_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": {"repo_path": path},
        }
    )


class CodexHookTests(unittest.TestCase):
    def test_session_and_prompt_context_ignore_untrusted_content(self):
        for name in ("SessionStart", "UserPromptSubmit"):
            with self.subTest(name=name):
                output = run_hook(
                    {"hook_event_name": name, "prompt": "SENSITIVE_INPUT_IGNORE_RULES"}
                )
                self.assertEqual(output["hookSpecificOutput"]["hookEventName"], name)
                self.assertNotIn("SENSITIVE_INPUT", json.dumps(output))

    def test_relative_empty_and_wrong_type_paths_are_denied(self):
        for path in ("relative", "", 123, []):
            with self.subTest(path=path):
                self.assertEqual(
                    pre_tool(path)["hookSpecificOutput"]["permissionDecision"], "deny"
                )

    def test_root_subdirectory_and_other_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory).resolve() / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            child = repo / "child"
            child.mkdir()
            self.assertNotIn(
                "permissionDecision", pre_tool(str(repo))["hookSpecificOutput"]
            )
            self.assertEqual(
                pre_tool(str(child))["hookSpecificOutput"]["permissionDecision"], "deny"
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "--allow-empty",
                    "-qm",
                    "test",
                ],
                check=True,
            )
            other = Path(directory).resolve() / "other"
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "add", "--detach", str(other)],
                capture_output=True,
                check=True,
            )
            self.assertNotIn(
                "permissionDecision", pre_tool(str(other))["hookSpecificOutput"]
            )

    def test_non_repository_and_missing_directory_are_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in (directory, str(Path(directory) / "missing")):
                self.assertEqual(
                    pre_tool(path)["hookSpecificOutput"]["permissionDecision"], "deny"
                )

    def test_nullable_field_and_other_servers_are_left_to_their_schema(self):
        self.assertNotIn("permissionDecision", pre_tool(None)["hookSpecificOutput"])
        self.assertEqual(pre_tool("relative", "mcp__other__query"), {})

    def test_registered_server_name_with_hyphens_is_also_checked(self):
        output = pre_tool(
            "relative", "mcp__dev-workflow-standards-tools__audit_repository_state"
        )
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_shell_and_patch_get_advice_without_granting_permission(self):
        for name in ("Bash", "exec_command", "apply_patch"):
            output = run_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": name,
                    "tool_input": {"command": "SENSITIVE_COMMAND"},
                }
            )
            self.assertNotIn("permissionDecision", output["hookSpecificOutput"])
            self.assertNotIn("SENSITIVE_COMMAND", json.dumps(output))

    def test_structured_failures_add_recovery_context_without_replacing_result(self):
        for response in (
            {"isError": True},
            {"ok": False, "created": True},
            {"exit_code": 1},
            {"structuredContent": {"ok": False}},
        ):
            response["secret"] = "SENSITIVE_ERROR"
            output = run_hook(
                {"hook_event_name": "PostToolUse", "tool_response": response}
            )
            self.assertIn("additionalContext", output["hookSpecificOutput"])
            self.assertNotIn("decision", output)
            self.assertNotIn("SENSITIVE_ERROR", json.dumps(output))

    def test_success_unknown_text_and_running_session_are_not_failures(self):
        for response in (
            {"ok": True},
            {"exit_code": 0},
            {"session_id": 1},
            {"exit_code": None},
            "error: ordinary text",
            None,
        ):
            self.assertEqual(
                run_hook({"hook_event_name": "PostToolUse", "tool_response": response}),
                {},
            )

    def test_stop_never_loops_and_unknown_events_are_noops(self):
        for name in ("Stop", "PermissionRequest", "Unknown"):
            self.assertEqual(run_hook({"hook_event_name": name}), {})

    def test_malformed_input_is_explicit_failure_without_echo(self):
        for data in ("SENSITIVE_INVALID_JSON", "[]"):
            result = subprocess.run(
                [sys.executable, str(RUNTIME)],
                input=data,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertTrue(result.stderr)
            self.assertNotIn("SENSITIVE", result.stderr)


class CodexHookInstallationTests(unittest.TestCase):
    def test_preview_install_execution_and_refusal_to_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="hooks ' quoted ") as directory:
            project = Path(directory).resolve()
            command = [sys.executable, str(SETUP), "--project-root", str(project)]
            preview = subprocess.run(
                command, capture_output=True, text=True, check=True
            )
            configuration = json.loads(preview.stdout)
            self.assertFalse((project / ".codex").exists())
            self.assertEqual(
                set(configuration["hooks"]),
                {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"},
            )
            subprocess.run([*command, "--install"], capture_output=True, check=True)
            hook_command = configuration["hooks"]["SessionStart"][0]["hooks"][0][
                "command"
            ]
            result = subprocess.run(
                hook_command,
                shell=True,
                input=json.dumps({"hook_event_name": "SessionStart"}),
                cwd="/",
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn(
                "additionalContext", json.loads(result.stdout)["hookSpecificOutput"]
            )
            config_path = project / ".codex/hooks.json"
            before = config_path.read_bytes()
            refused = subprocess.run(
                [*command, "--install"], capture_output=True, check=False
            )
            self.assertEqual(refused.returncode, 1)
            self.assertEqual(config_path.read_bytes(), before)

    def test_symlink_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            outside = Path(directory) / "outside"
            project.mkdir()
            outside.mkdir()
            (project / ".codex").symlink_to(outside, target_is_directory=True)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SETUP),
                    "--project-root",
                    str(project),
                    "--install",
                ],
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
