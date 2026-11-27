from __future__ import annotations

import asyncio
import select
import subprocess
import sys
import unittest
from pathlib import Path
from typing import BinaryIO
from unittest.mock import patch

from mcp.client import Client

from dev_agent_toolkit_tools.mcp_client import process
from dev_agent_toolkit_tools.mcp_client.registry import ServerConfig


_STDIO_SERVER = """
import os

from mcp.server import MCPServer

server = MCPServer("process-fixture")

@server.tool()
def explicit_environment() -> str:
    assert "MCP_CLIENT_UNAPPROVED_FIXTURE" not in os.environ
    return os.environ["MCP_CLIENT_APPROVED_FIXTURE"]

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
        config = ServerConfig(
            command=sys.executable,
            args=["-B", "-c", _STDIO_SERVER],
            env={"MCP_CLIENT_APPROVED_FIXTURE": "approved"},
        )
        with patch.dict("os.environ", {"MCP_CLIENT_UNAPPROVED_FIXTURE": "unapproved"}):
            for mode, version in (
                ("auto", "2026-07-28"),
                ("legacy", "2025-11-25"),
            ):
                with self.subTest(mode=mode):
                    async with (
                        asyncio.timeout(10),
                        Client(process.managed_stdio(config), mode=mode) as client,
                    ):
                        self.assertEqual(client.protocol_version, version)
                        listing = await client.list_tools()
                        self.assertEqual(
                            [tool.name for tool in listing.tools],
                            ["explicit_environment"],
                        )
                        result = await client.call_tool("explicit_environment")
                        self.assertFalse(result.is_error)
                        self.assertEqual(result.content[0].text, "approved")

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

    def _read(self, stdout: BinaryIO) -> bytes:
        ready, _, _ = select.select([stdout], [], [], 5)
        self.assertTrue(ready, "a fixture process still holds the STDIO pipe")
        return stdout.readline()
