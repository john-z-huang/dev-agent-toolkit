from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from mcp_client import ClientError, Registry, ServerConfig
from mcp_client.worker import open_worker, worker_request

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp_client_stdio.py"


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def _stop_cli(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        process.kill()
        await process.wait()


class MCPClientWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.project = Path(directory.name).resolve()
        self.registry = Registry(self.project / "servers.json")

    async def open_fixture(self, **options):
        self.registry.add(
            "fixture",
            ServerConfig(
                command=sys.executable,
                args=["-B", str(FIXTURE)],
                cwd=self.project,
                allowed_tools=["ask", "state"],
                **options,
            ),
        )
        opened = await open_worker(self.registry, "fixture")
        self.addAsyncCleanup(self.close_fixture, opened["session_id"])
        return opened

    async def close_fixture(self, session_id):
        try:
            await worker_request(session_id, "close")
        except ClientError as error:
            if error.code != "session_unavailable":
                raise

    async def spawn_cli(self, *args):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-B",
            "-m",
            "mcp_client.cli",
            "--registry",
            str(self.registry.path),
            *args,
            cwd=self.project,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.addAsyncCleanup(_stop_cli, process)
        return process

    async def cli_result(self, process):
        stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
        self.assertEqual(process.returncode, 0, (stdout, stderr))
        return json.loads(stdout)

    async def test_respond_from_another_cli_to_input_required_event(self):
        opened = await self.open_fixture(elicitation=True)
        session = opened["session_id"]
        call = await self.spawn_cli(
            "--events",
            "session",
            "request",
            session,
            "tools/call",
            "--json",
            '{"name":"ask"}',
        )
        assert call.stdout is not None
        record = json.loads(await asyncio.wait_for(call.stdout.readline(), 15))
        self.assertEqual(record["type"], "event")
        event = record["event"]
        self.assertEqual(event["type"], "input_required")
        self.assertEqual(event["method"], "elicitation/create")

        status = await self.cli_result(
            await self.spawn_cli("session", "status", session)
        )
        self.assertEqual(status["result"]["state"], "busy")
        self.assertEqual(status["result"]["pending_inputs"], [event])
        response = json.dumps(
            {
                "input_id": event["input_id"],
                "response": {"action": "accept", "content": {"label": "another CLI"}},
            }
        )
        acknowledged = await self.cli_result(
            await self.spawn_cli("session", "respond", session, "--json", response)
        )
        self.assertTrue(acknowledged["result"]["accepted"])
        final = await self.cli_result(call)
        self.assertEqual(final["result"]["structuredContent"]["value"], "another CLI")

    async def test_idle_session_reclaims_worker_and_its_stdio_server(self):
        opened = await self.open_fixture(idle_timeout=1.5)
        session_id = opened["session_id"]
        result = await worker_request(
            session_id, "request", {"method": "tools/call", "params": {"name": "state"}}
        )
        worker_pid = opened["pid"]
        server_pid = result["structuredContent"]["value"]["pid"]
        async with asyncio.timeout(10):
            while _running(worker_pid) or _running(server_pid):
                await asyncio.sleep(0.05)
        with self.assertRaises(ClientError) as closed:
            await worker_request(session_id, "status")
        self.assertEqual(closed.exception.code, "session_unavailable")
