"""通过真实 stdin/stdout 和临时 Git 仓库核验原生 Hook 协议。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from codex_hooks_test_support import InstalledHooksTestCase

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "codex-hooks/dev_workflow_standards_hooks/runtime.py"
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
            payload: dict[str, object] = {**response, "secret": "SENSITIVE_ERROR"}
            output = run_hook(
                {"hook_event_name": "PostToolUse", "tool_response": payload}
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


class CodexHookInstallationTests(InstalledHooksTestCase):
    def test_pre_tool_status_matches_each_scenario_without_duplicate_handlers(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [*self.configure_command, "--project-root", directory],
                capture_output=True,
                text=True,
                check=True,
            )
            hooks = json.loads(result.stdout)["hooks"]
            cases = {
                "exec_command": "Python/Shell",
                "Bash": "Python/Shell",
                "apply_patch": "修改范围",
                "mcp__dev_workflow_standards_tools__check_branch_name": "目标仓库",
                "mcp__dev-workflow-standards-tools__check_branch_name": "目标仓库",
            }
            for tool, message in cases.items():
                groups = [
                    group
                    for group in hooks["PreToolUse"]
                    if re.fullmatch(group["matcher"], tool)
                ]
                self.assertEqual(len(groups), 1, tool)
                self.assertIn(message, groups[0]["hooks"][0]["statusMessage"])
            self.assertFalse(
                any(
                    re.fullmatch(group["matcher"], "mcp__other__tool")
                    for group in hooks["PreToolUse"]
                )
            )
            messages = [
                handler["statusMessage"]
                for groups in hooks.values()
                for group in groups
                for handler in group["hooks"]
            ]
            self.assertEqual(len(messages), len(set(messages)))

    def test_preview_install_execution_and_refusal_to_overwrite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hooks ' quoted ") as directory:
            project = Path(directory).resolve()
            command = [*self.configure_command, "--project-root", str(project)]
            preview = subprocess.run(
                command, capture_output=True, text=True, check=True
            )
            configuration = json.loads(preview.stdout)
            self.assertFalse((project / ".codex").exists())
            subprocess.run([*command, "--install"], capture_output=True, check=True)
            hook_command = configuration["hooks"]["SessionStart"][0]["hooks"][0][
                "command"
            ]
            result = subprocess.run(
                hook_command,
                shell=True,
                cwd="/",
                input=json.dumps({"hook_event_name": "SessionStart"}),
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn(
                "additionalContext", json.loads(result.stdout)["hookSpecificOutput"]
            )
            self.assertFalse((project / ".codex/hooks/dev_workflow.py").exists())
            before = (project / ".codex/hooks.json").read_bytes()
            refused = subprocess.run(
                [*command, "--install"], capture_output=True, check=False
            )
            self.assertEqual(refused.returncode, 1)
            self.assertEqual((project / ".codex/hooks.json").read_bytes(), before)
            subprocess.run([*command, "--update"], capture_output=True, check=True)
            self.assertEqual((project / ".codex/hooks.json").read_bytes(), before)

    def test_global_install_update_and_local_change_protection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            env = {**os.environ, "CODEX_HOME": str(home)}
            command = [*self.configure_command, "--global"]
            subprocess.run(
                [*command, "--install", "--dry-run"],
                env=env,
                capture_output=True,
                check=True,
            )
            self.assertEqual(list(home.iterdir()), [])
            subprocess.run(
                [*command, "--install"], env=env, capture_output=True, check=True
            )
            self.assertFalse((home / ".codex").exists())
            subprocess.run(
                [*command, "--update"], env=env, capture_output=True, check=True
            )
            config = home / "hooks.json"
            config.write_bytes(b"local changes")
            result = subprocess.run(
                [*command, "--update"], env=env, capture_output=True, check=False
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(config.read_bytes(), b"local changes")

    def test_default_home_and_scope_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            env = {
                key: value for key, value in os.environ.items() if key != "CODEX_HOME"
            }
            env["HOME"] = str(home)
            command = self.configure_command
            subprocess.run(
                [*command, "--global", "--install"],
                env=env,
                capture_output=True,
                check=True,
            )
            self.assertTrue((home / ".codex/hooks.json").is_file())
            for scope in ([], ["--global", "--project-root", str(home)]):
                result = subprocess.run(
                    [*command, *scope], env=env, capture_output=True, check=False
                )
                self.assertEqual(result.returncode, 2)

    def test_update_refuses_modified_missing_and_linked_resources(self) -> None:
        for name in ("hooks.json", "hooks/dev_workflow.manifest.json"):
            for change in ("modified", "missing", "symlink", "hardlink"):
                with (
                    self.subTest(name=name, change=change),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    home = Path(directory).resolve()
                    env = {**os.environ, "CODEX_HOME": str(home)}
                    command = [*self.configure_command, "--global"]
                    subprocess.run(
                        [*command, "--install"],
                        env=env,
                        capture_output=True,
                        check=True,
                    )
                    path = home / name
                    previous = path.read_bytes()
                    path.unlink()
                    if change == "modified":
                        path.write_bytes(b"local changes")
                    elif change in ("symlink", "hardlink"):
                        source = home / "source"
                        source.write_bytes(previous)
                        if change == "symlink":
                            path.symlink_to(source)
                        else:
                            path.hardlink_to(source)
                    for flags in (["--update"], ["--update", "--dry-run"]):
                        result = subprocess.run(
                            [*command, *flags],
                            env=env,
                            capture_output=True,
                            check=False,
                        )
                        self.assertEqual(result.returncode, 1, result.stderr)

    def test_global_rejects_invalid_and_symlinked_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            outside = root / "outside"
            outside.mkdir()
            linked = root / "linked"
            linked.symlink_to(outside, target_is_directory=True)
            for target, status in (
                ("", 2),
                ("relative", 2),
                (str(root / "missing"), 2),
                (str(linked), 1),
            ):
                result = subprocess.run(
                    [*self.configure_command, "--global", "--install"],
                    env={**os.environ, "CODEX_HOME": target},
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, status, result.stderr)
            self.assertEqual(list(outside.iterdir()), [])

    def test_update_migrates_legacy_snapshot_and_preserves_script(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            scripts = root / "hooks"
            scripts.mkdir()
            legacy = scripts / "dev_workflow.py"
            legacy.write_bytes(b"# legacy managed script")
            config = root / "hooks.json"
            config.write_bytes(b'{"hooks": {}}')
            manifest = scripts / "dev_workflow.manifest.json"
            record = {
                "format": 1,
                "files": {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (legacy, config)
                },
            }
            manifest.write_text(json.dumps(record))
            result = subprocess.run(
                [*self.configure_command, "--global", "--update"],
                env={**os.environ, "CODEX_HOME": str(root)},
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(manifest.read_bytes())["format"], 3)
            self.assertEqual(legacy.read_bytes(), b"# legacy managed script")
            self.assertIn("dev-workflow-standards-hooks", config.read_text())


if __name__ == "__main__":
    unittest.main()
