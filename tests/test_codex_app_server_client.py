"""使用独立合成进程测试 JSON-RPC 时序、脱敏、期限和资源清理。"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_app_server_client import AppServerClient, SmokeFailure

FIXTURE = """
import json, os, sys, time
if '--version' in sys.argv:
    print('codex-cli 0.167.0')
    sys.exit(0)
def send(value):
    print(json.dumps(value), flush=True)
for line in sys.stdin:
    message = json.loads(line)
    if 'id' not in message:
        continue
    mode = os.environ.get('MODE')
    if mode == 'invalid':
        print('synthetic-private-output', flush=True)
        break
    if mode == 'rpc_error':
        send({'id': message['id'], 'error': {'message': 'synthetic-private-error'}})
        continue
    if mode == 'approval':
        send({'id': 99, 'method': 'item/commandExecution/requestApproval', 'params': {}})
        continue
    if mode == 'eof':
        break
    if mode == 'timeout':
        time.sleep(0.3)
        break
    if message['method'] == 'turn/start':
        send({'method': 'item/completed', 'params': {'threadId': 'other', 'turnId': 'turn'}})
        send({'method': 'item/completed', 'params': {'threadId': 'thread', 'turnId': 'old'}})
        send({'method': 'item/completed', 'params': {'threadId': 'thread', 'turnId': 'turn', 'item': {'type': 'agentMessage'}}})
        send({'method': 'turn/completed', 'params': {'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'completed'}}})
    result = {'turn': {'id': 'turn'}, 'method': message['method'],
              'params': message.get('params'), 'argv': sys.argv[1:],
              'unrelatedSecret': os.environ.get('UNRELATED_SECRET')}
    send({'id': message['id'] + (1 if mode == 'wrong_id' else 0), 'result': result})
"""


class AppServerClientTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        executable = self.root / "codex"
        executable.write_text("#!" + sys.executable + "\n" + FIXTURE)
        executable.chmod(0o755)

    def client(self, mode="normal"):
        return AppServerClient(
            cwd=str(self.root),
            env={"PATH": str(self.root), "MODE": mode},
            config_overrides=('model="gpt-6-luna"',),
        )

    def test_stdio_command_handshake_and_environment_are_explicit(self):
        with (
            patch.dict(os.environ, {"UNRELATED_SECRET": "synthetic-secret"}),
            self.client() as client,
        ):
            client.initialize()
            result = client.request("echo", {"value": "synthetic"})
            process = client.process
        self.assertEqual(result["params"], {"value": "synthetic"})
        self.assertEqual(
            result["argv"], ["app-server", "--stdio", "-c", 'model="gpt-6-luna"']
        )
        self.assertIsNone(result["unrelatedSecret"])
        self.assertEqual(client.cli_info["version"], "0.167.0")
        self.assertIsNotNone(process.poll())
        self.assertFalse(client.reader.is_alive())
        client.close()

    def test_notifications_before_response_are_preserved_and_filtered(self):
        with self.client() as client:
            client.initialize()
            client.request("turn/start", {})
            first = client.next_turn_notification("thread", "turn")
            last = client.next_turn_notification("thread", "turn")
        self.assertEqual(first["method"], "item/completed")
        self.assertEqual(last["method"], "turn/completed")

    def test_transport_failures_are_classified_without_private_output(self):
        cases = {
            "invalid": "app_server_invalid_json",
            "rpc_error": "app_server_rpc_error",
            "approval": "unexpected_server_request",
            "eof": "app_server_process_exited",
            "wrong_id": "app_server_response_id_mismatch",
        }
        for mode, code in cases.items():
            with (
                self.subTest(mode=mode),
                self.client(mode) as client,
                self.assertRaisesRegex(SmokeFailure, "^" + code + "$"),
            ):
                client.initialize()

    def test_deadline_stops_waiting_without_retry(self):
        with self.client("timeout") as client:
            client.deadline = time.monotonic() + 0.1
            with self.assertRaisesRegex(SmokeFailure, "^app_server_timeout$"):
                client.initialize()
            self.assertEqual(client.request_id, 1)

    def test_missing_cli_stops_before_launch(self):
        with (
            patch("codex_app_server_client.shutil.which", return_value=None),
            patch("codex_app_server_client.subprocess.Popen") as start,
        ):
            with self.assertRaisesRegex(SmokeFailure, "codex_cli_missing"):
                self.client().__enter__()
            start.assert_not_called()

    def test_launch_error_never_exposes_exception_details(self):
        with (
            patch("codex_app_server_client.inspect_cli", return_value={}),
            patch(
                "codex_app_server_client.subprocess.Popen",
                side_effect=OSError("synthetic-secret"),
            ),
            self.assertRaisesRegex(SmokeFailure, "^app_server_start_failed$"),
        ):
            self.client().__enter__()

    def test_version_failure_is_redacted_before_starting_server(self):
        with (
            patch(
                "codex_app_server_client.subprocess.run",
                side_effect=OSError("synthetic-secret"),
            ),
            self.assertRaisesRegex(SmokeFailure, "^codex_cli_version_unavailable$"),
        ):
            self.client().__enter__()


if __name__ == "__main__":
    unittest.main()
