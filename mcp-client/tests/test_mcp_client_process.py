from __future__ import annotations

import asyncio
import os
import select
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import IO
from unittest.mock import patch

from dev_agent_toolkit_mcp_client import process
from dev_agent_toolkit_mcp_client.protocol import connect
from dev_agent_toolkit_mcp_client.registry import ServerConfig


_STDIO_SERVER = """
import os
import sys
from pathlib import Path

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

with Path(sys.argv[1]).open("a") as marker:
    marker.write(str("MCP_CLIENT_FORWARDED_FIXTURE" in os.environ) + chr(10))

server = MCPServer("process-fixture")

@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def get_mcp_environment() -> dict[str, list[str]]:
    return {"names": [
        "MCP_CLIENT_FORWARDED_FIXTURE",
        "MCP_CLIENT_EMPTY_FIXTURE",
        "MCP_CLIENT_MISSING_FIXTURE",
    ]}

@server.tool()
def configured_environment() -> dict[str, str | None]:
    assert "MCP_CLIENT_UNAPPROVED_FIXTURE" not in os.environ
    return {
        "forwarded": os.environ.get("MCP_CLIENT_FORWARDED_FIXTURE"),
        "empty": os.environ.get("MCP_CLIENT_EMPTY_FIXTURE"),
        "missing": os.environ.get("MCP_CLIENT_MISSING_FIXTURE"),
    }

server.run(transport="stdio")
"""

_DESCENDANT = """
import signal
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
print("descendant ready", flush=True)
time.sleep(12)
"""

_SERVER_LEADER = """
import subprocess
import sys

subprocess.Popen([sys.executable, "-c", sys.argv[1]])
sys.stdin.readline()
"""

_CALLER = """
import subprocess
import sys
import time

supervisor = subprocess.Popen(sys.argv[1:], stdin=subprocess.PIPE)
time.sleep(12)
"""


@unittest.skipUnless(sys.platform in {"darwin", "linux"}, "managed POSIX STDIO")
class ManagedStdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_stdio_and_environment_in_both_protocol_modes(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {
                    "MCP_CLIENT_UNAPPROVED_FIXTURE": "unapproved",
                    "MCP_CLIENT_FORWARDED_FIXTURE": "forwarded",
                    "MCP_CLIENT_EMPTY_FIXTURE": "",
                },
            ),
        ):
            os.environ.pop("MCP_CLIENT_MISSING_FIXTURE", None)
            for mode, version in (
                ("auto", "2026-07-28"),
                ("legacy", "2025-11-25"),
            ):
                marker = Path(directory) / mode
                config = ServerConfig(
                    command=sys.executable,
                    args=["-B", "-c", _STDIO_SERVER, str(marker)],
                    mode=mode,
                )
                with self.subTest(mode=mode):
                    async with (
                        asyncio.timeout(10),
                        connect(config) as client,
                    ):
                        info = await client.request("server/info", {})
                        self.assertEqual(info["protocolVersion"], version)
                        listing = await client.request("tools/list", {})
                        self.assertEqual(
                            [tool["name"] for tool in listing["tools"]],
                            ["get_mcp_environment", "configured_environment"],
                        )
                        result = await client.request(
                            "tools/call", {"name": "configured_environment"}
                        )
                        self.assertFalse(result.get("isError"))
                        self.assertEqual(
                            result["structuredContent"],
                            {
                                "forwarded": "forwarded",
                                "empty": "",
                                "missing": None,
                            },
                        )
                    self.assertEqual(marker.read_text().splitlines(), ["False", "True"])

    def test_server_leader_exit_reclaims_stubborn_descendant(self) -> None:
        with subprocess.Popen(
            self._supervisor_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            bufsize=0,
        ) as supervisor:
            assert supervisor.stdin is not None and supervisor.stdout is not None
            self.assertEqual(self._read(supervisor.stdout), b"descendant ready\n")
            supervisor.stdin.write(b"exit\n")
            self.assertEqual(supervisor.wait(timeout=5), 0)
            self.assertEqual(self._read(supervisor.stdout), b"")

    def test_caller_death_reclaims_supervisor_and_stubborn_descendant(self) -> None:
        with subprocess.Popen(
            [sys.executable, "-c", _CALLER, *self._supervisor_command()],
            stdout=subprocess.PIPE,
            bufsize=0,
        ) as caller:
            assert caller.stdout is not None
            self.assertEqual(self._read(caller.stdout), b"descendant ready\n")
            caller.kill()
            self.assertEqual(caller.wait(timeout=5), -9)
            self.assertEqual(self._read(caller.stdout), b"")

    @staticmethod
    def _supervisor_command() -> list[str]:
        return [
            sys.executable,
            "-I",
            "-S",
            str(Path(process.__file__).resolve()),
            sys.executable,
            "-c",
            _SERVER_LEADER,
            _DESCENDANT,
        ]

    def _read(self, stdout: IO[bytes]) -> bytes:
        ready, _, _ = select.select([stdout], [], [], 5)
        self.assertTrue(ready, "a fixture process still holds the STDIO pipe")
        return stdout.readline()
