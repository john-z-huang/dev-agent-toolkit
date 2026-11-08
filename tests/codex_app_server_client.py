"""测试专用的 stdio JSON-RPC 客户端；不依赖 Codex SDK。"""

from __future__ import annotations

import json
import queue
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path


class SmokeFailure(Exception):
    """只传递固定安全分类，不转发进程输出、RPC 正文或底层异常。"""


def inspect_cli(executable: str, environment: dict[str, str]) -> dict[str, str]:
    try:
        result = subprocess.run(
            [executable, "--version"],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        match = re.fullmatch(
            r"codex-cli (\d+\.\d+\.\d+(?:[-+][a-zA-Z0-9.-]+)?)\s*", result.stdout
        )
        if result.returncode or match is None:
            raise SmokeFailure("codex_cli_version_unavailable")
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        raise SmokeFailure("codex_cli_version_unavailable") from None
    return {"path": executable, "version": match[1]}


class AppServerClient:
    def __init__(
        self, *, cwd: str, env: dict[str, str], config_overrides: tuple[str, ...]
    ):
        self.cwd = cwd
        self.env = env
        self.config_overrides = config_overrides
        self.process = None
        self.messages: queue.Queue = queue.Queue()
        self.notifications: deque[dict] = deque()
        self.request_id = 0
        self.deadline = time.monotonic() + 120
        self.reader = None
        self.cli_info = None

    def __enter__(self):
        executable = shutil.which("codex", path=self.env.get("PATH", ""))
        if executable is None:
            raise SmokeFailure("codex_cli_missing")
        executable = str(Path(executable).resolve())
        self.cli_info = inspect_cli(executable, self.env)
        command = [executable, "app-server", "--stdio"]
        for override in self.config_overrides:
            command.extend(["-c", override])
        try:
            self.process = subprocess.Popen(
                command,
                cwd=self.cwd,
                env=self.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError:
            raise SmokeFailure("app_server_start_failed") from None
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        return self

    def __exit__(self, *args):
        self.close()

    def _read(self):
        try:
            for line in self.process.stdout:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise TypeError("invalid envelope")
                self.messages.put(message)
        except (TypeError, ValueError, UnicodeError):
            self.messages.put(SmokeFailure("app_server_invalid_json"))
        except OSError:
            self.messages.put(SmokeFailure("app_server_read_failed"))
        finally:
            self.messages.put(SmokeFailure("app_server_process_exited"))

    def _receive(self) -> dict:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise SmokeFailure("app_server_timeout")
        try:
            message = self.messages.get(timeout=remaining)
        except queue.Empty:
            raise SmokeFailure("app_server_timeout") from None
        if isinstance(message, SmokeFailure):
            raise message
        return message

    def _send(self, message: dict):
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError, AttributeError):
            raise SmokeFailure("app_server_write_failed") from None

    def request(self, method: str, params: dict) -> dict:
        self.request_id += 1
        request_id = self.request_id
        self._send({"id": request_id, "method": method, "params": params})
        while True:
            message = self._receive()
            if "method" in message:
                if "id" in message:
                    raise SmokeFailure("unexpected_server_request")
                self.notifications.append(message)
                continue
            if message.get("id") != request_id:
                raise SmokeFailure("app_server_response_id_mismatch")
            if "error" in message:
                raise SmokeFailure("app_server_rpc_error")
            result = message.get("result")
            if not isinstance(result, dict):
                raise SmokeFailure("app_server_invalid_result")
            return result

    def initialize(self):
        self.request(
            "initialize",
            {
                "clientInfo": {"name": "dev_workflow_smoke", "version": "1.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        self._send({"method": "initialized"})

    def next_turn_notification(self, thread_id: str, turn_id: str) -> dict:
        while True:
            message = (
                self.notifications.popleft() if self.notifications else self._receive()
            )
            if "id" in message:
                raise SmokeFailure("unexpected_server_request")
            params = message.get("params", {})
            if not isinstance(params, dict) or params.get("threadId") != thread_id:
                continue
            event_turn = params.get("turnId") or params.get("turn", {}).get("id")
            if event_turn == turn_id:
                return message

    def close(self):
        if self.process is None:
            return
        try:
            self.process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.reader.join(timeout=1)
        self.process.stdout.close()
        self.process = None
