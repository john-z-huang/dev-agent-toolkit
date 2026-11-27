from __future__ import annotations

import io
import json
import stat
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dev_agent_toolkit_tools.cli import main


class CommitDraftCliTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.registry = self.root / "registered.json"
        self.file = self.root / "candidate.json"
        self.server = "dev-agent-toolkit-tools"
        self.calls = []
        self.message = "fix: 修复暂存检查\n\n保留候选原文。"
        self.snapshot = {
            "branch": "main",
            "head_oid": "b" * 40,
            "staged_sha256": "a" * 64,
        }
        self.candidate = {
            "ok": True,
            "adoptable": True,
            "message": self.message,
            "staged_paths": ["source.py"],
            "snapshot": self.snapshot,
        }
        self.schema = {"inputSchema": {"properties": {"expected_snapshot": {}}}}

        locator = patch(
            "dev_agent_toolkit_tools.commit_draft.shutil.which",
            return_value=sys.executable,
        )
        locator.start()
        self.addCleanup(locator.stop)
        process = patch(
            "dev_agent_toolkit_tools.commit_draft.subprocess.run",
            side_effect=self.client,
        )
        process.start()
        self.addCleanup(process.stop)

    def client(self, command, *, input, **_kwargs):
        self.assertEqual(
            command[:3], [sys.executable, "--registry", str(self.registry)]
        )
        args = command[3:]
        if args == ["registry", "get", self.server]:
            result = {"config": {"command": "fixture-toolkit"}}
        elif args == ["session", "open", self.server]:
            result = {"session_id": "fixture-session"}
        elif args == ["session", "close", "fixture-session"]:
            result = {}
        elif args == ["call", self.server, "generate_git_commit_message", "--stdin"]:
            result = self.request(
                "tools/call",
                {"name": "generate_git_commit_message", "arguments": json.loads(input)},
            )
        else:
            self.assertEqual(args[:3], ["session", "request", "fixture-session"])
            self.assertEqual(args[-1], "--stdin")
            result = self.request(args[3], json.loads(input))
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps({"ok": True, "result": result})
        )

    def request(self, method, params):
        self.calls.append((method, params))
        if method == "tools/schema":
            return self.schema
        name = params["name"]
        if name == "generate_git_commit_message":
            return {"structuredContent": self.candidate}
        if name == "commit_repository_changes":
            return {
                "structuredContent": {
                    "ok": True,
                    "committed": True,
                    "commit_oid": "c" * 40,
                    "message": self.message,
                    "paths": ["source.py"],
                }
            }
        return {"content": [{"type": "text", "text": '{"passed":true}'}]}

    def run_cli(self, action, *options):
        with redirect_stdout(io.StringIO()) as output:
            status = main(
                [
                    "commit",
                    "--registry",
                    str(self.registry),
                    action,
                    str(self.file),
                    *options,
                ]
            )
        return status, json.loads(output.getvalue())

    def test_draft_saves_exact_candidate_for_explicit_apply(self):
        status, reply = self.run_cli("draft", "--repo-path", str(self.root))
        self.assertEqual(status, 0)
        self.assertEqual(reply["result"]["message"], self.message)
        self.assertNotIn("staged_paths", reply["result"])
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        repo = str(self.root.resolve())
        self.assertEqual(
            self.calls,
            [
                (
                    "tools/call",
                    {
                        "name": "generate_git_commit_message",
                        "arguments": {"repo_path": repo},
                    },
                )
            ],
        )

        status, reply = self.run_cli("apply")
        self.assertEqual(status, 0)
        self.assertTrue(reply["result"]["committed"])
        self.assertEqual(
            [params["name"] for _, params in self.calls],
            [
                "generate_git_commit_message",
                "commit_repository_changes",
                "check_branch_names",
                "check_staged_changes",
                "check_commit_message",
                "commit_repository_changes",
            ],
        )
        self.assertEqual(
            self.calls[-1][1]["arguments"],
            {
                "repo_path": repo,
                "message": self.message,
                "expected_paths": ["source.py"],
                "expected_snapshot": self.snapshot,
            },
        )

    def test_missing_snapshot_support_blocks_apply_before_other_requests(self):
        self.assertEqual(self.run_cli("draft")[0], 0)
        self.schema = {"inputSchema": {"properties": {}}}
        status, reply = self.run_cli("apply")
        self.assertEqual(status, 1)
        self.assertEqual(reply["error"]["code"], "server_update_required")
        self.assertEqual(len(self.calls), 2)

    def test_non_adoptable_result_does_not_create_a_draft(self):
        self.candidate.update(adoptable=False, missing_facts=["需要核对实际改动"])
        status, reply = self.run_cli("draft")
        self.assertEqual(status, 1)
        self.assertFalse(self.file.exists())
        self.assertEqual(reply["result"]["missing_facts"], ["需要核对实际改动"])
