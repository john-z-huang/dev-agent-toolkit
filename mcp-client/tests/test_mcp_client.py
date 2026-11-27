from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from dev_agent_toolkit_mcp_client import (
    ClientError,
    Registry,
    ServerConfig,
    execute,
    execute_batch,
    open_session,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp_client_stdio.py"


class StandaloneMCPClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.registry = Registry(self.root / "servers.json")
        self.marker = self.root / "launches"
        self.config = ServerConfig(
            command=sys.executable,
            args=["-B", str(FIXTURE)],
            cwd=self.root,
            env={"TEST_MARKER": str(self.marker)},
        )
        self.registry.add("fixture", self.config)

    async def cli(self, *args, expected=0, stdin=None, registry_path=None):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-B",
            "-m",
            "dev_agent_toolkit_mcp_client.cli",
            "--registry",
            str(registry_path or self.registry.path),
            *args,
            stdin=asyncio.subprocess.PIPE
            if stdin is not None
            else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.root,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(stdin), 15)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        self.assertEqual(process.returncode, expected, (stdout, stderr))
        return [json.loads(line) for line in stdout.splitlines()]

    async def test_standard_methods_on_both_versions_and_pagination(self):
        self.registry.add(
            "legacy",
            self.config.model_copy(update={"env": {"TEST_LEGACY_ONLY": "yes"}}),
        )
        for name, version in (("fixture", "2026-07-28"), ("legacy", "2025-11-25")):
            async with open_session(self.registry, name) as session:
                info = await session.request("server/info")
                self.assertEqual(info["protocolVersion"], version)
                listing = await session.request("tools/list")
                self.assertTrue(listing["nextCursor"])
                schema = await session.request("tools/schema", {"name": "state"})
                self.assertEqual(schema["inputSchema"]["type"], "object")
                extra = await session.request(
                    "tools/call", {"name": "extra", "arguments": {"label": "available"}}
                )
                self.assertEqual(extra["structuredContent"]["value"], "available")
                with self.assertRaises(ClientError) as rpc:
                    await session.request(
                        "tools/call",
                        {"name": "echo", "arguments": {"label": "rpc-error"}},
                    )
                self.assertEqual(
                    (rpc.exception.code, rpc.exception.rpc_code), ("rpc_error", -32602)
                )
                for method, params, key in (
                    ("resources/list", {}, "resources"),
                    ("resources/templates/list", {}, "resourceTemplates"),
                    ("resources/read", {"uri": "fixture://entry"}, "contents"),
                    ("prompts/list", {}, "prompts"),
                    ("prompts/get", {"name": "welcome"}, "messages"),
                    (
                        "completion/complete",
                        {
                            "ref": {"type": "ref/prompt", "name": "welcome"},
                            "argument": {"name": "person", "value": "Al"},
                        },
                        "completion",
                    ),
                ):
                    with self.subTest(version=version, method=method):
                        self.assertTrue((await session.request(method, params))[key])
                if name == "legacy":
                    await session.request("ping")
                    await session.request(
                        "resources/subscribe", {"uri": "fixture://entry"}
                    )
                    await session.request(
                        "resources/unsubscribe", {"uri": "fixture://entry"}
                    )

    async def test_update_delete_readd_and_project_isolation(self):
        other_dir = self.root / "other"
        other_dir.mkdir()
        self.registry.add("other", self.config.model_copy(update={"cwd": other_dir}))
        async with (
            open_session(self.registry, "fixture") as first,
            open_session(self.registry, "other") as second,
        ):
            self.assertFalse(self.marker.exists())
            a, b = await asyncio.gather(
                *(
                    session.request("tools/call", {"name": "state"})
                    for session in (first, second)
                )
            )
            a, b = (value["structuredContent"]["value"] for value in (a, b))
            self.assertNotEqual(a["pid"], b["pid"])
            self.assertEqual((a["cwd"], b["cwd"]), (str(self.root), str(other_dir)))
            self.assertEqual((a["calls"], b["calls"]), (1, 1))
            self.registry.update(
                "fixture",
                self.config.model_copy(update={"env": {"TEST_FLAVOR": "updated"}}),
            )
            old = await first.request("tools/call", {"name": "state"})
            new = await execute(
                self.registry, "fixture", "tools/call", {"name": "state"}
            )
            self.assertEqual(old["structuredContent"]["value"]["flavor"], "original")
            self.assertEqual(new["structuredContent"]["value"]["flavor"], "updated")
            self.registry.remove("fixture")
            self.registry.add("fixture", self.config)
            with self.assertRaises(ClientError) as failure:
                await first.request("tools/list")
            self.assertEqual(failure.exception.code, "server_removed")
            await asyncio.wait_for(first.wait_closed(), 5)
            self.assertFalse(second.closed)

    async def test_batch_preserves_order_and_tool_error(self):
        requests = [
            {"method": "tools/call", "params": {"name": name}}
            for name in ("state", "state", "broken", "echo")
        ]
        reply = await execute_batch(self.registry, "fixture", requests)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["skipped"], 1)
        self.assertEqual(reply["items"][2]["error"]["code"], "tool_error")
        self.assertTrue(reply["items"][2]["result"]["isError"])
        a, b = [
            item["result"]["structuredContent"]["value"] for item in reply["items"][:2]
        ]
        self.assertEqual(a["pid"], b["pid"])
        self.assertEqual((a["calls"], b["calls"]), (1, 2))
        self.assertEqual(len(self.marker.read_text().splitlines()), 1)

    async def test_cli_batch_binds_session_token_and_pagination_cursor(self):
        steps = [
            {"tool": "initial_instructions"},
            {
                "tool": "activate_project",
                "arguments": {"project": "other-project"},
                "bind": {
                    "session": {
                        "path": [0, "content", 0, "text"],
                        "between": ["Your Serena session id is `", "`"],
                    }
                },
            },
            {"method": "tools/list"},
            {"method": "tools/list", "bind": {"cursor": {"path": [2, "nextCursor"]}}},
            {"tool": "state"},
        ]
        reply = (
            await self.cli(
                "batch", "fixture", "--stdin", stdin=json.dumps(steps).encode()
            )
        )[0]
        self.assertTrue(reply["ok"], reply)
        items = reply["items"]
        self.assertNotIn("nextCursor", items[3]["result"])
        self.assertIn("state", [tool["name"] for tool in items[3]["result"]["tools"]])
        state = items[4]["result"]["structuredContent"]["value"]
        self.assertEqual(state["project"], "other-project")
        self.assertEqual(len(self.marker.read_text().splitlines()), 1)

    async def test_batch_validates_bindings_and_preserves_completed_results(self):
        with self.assertRaises(ClientError) as invalid:
            await execute_batch(
                self.registry,
                "fixture",
                [
                    {"tool": "state"},
                    {"tool": "echo", "bind": {"label": {"path": [1, "result"]}}},
                ],
            )
        self.assertEqual(invalid.exception.code, "invalid_request")
        self.assertFalse(self.marker.exists())

        reply = await execute_batch(
            self.registry,
            "fixture",
            [
                {"tool": "echo"},
                {
                    "tool": "echo",
                    "bind": {
                        "label": {
                            "path": [0, "content", 0, "text"],
                            "between": ["missing start", "missing end"],
                        }
                    },
                },
                {"tool": "state"},
            ],
        )
        self.assertTrue(reply["items"][0]["ok"])
        self.assertEqual(reply["items"][1]["error"]["code"], "invalid_binding")
        self.assertEqual(reply["skipped"], 1)

    async def test_progress_ignores_idle_timeout_and_pending_request_cancels(self):
        self.registry.update(
            "fixture", self.config.model_copy(update={"idle_timeout": 0.3})
        )
        progress = asyncio.Event()

        async def on_event(event):
            if event["type"] == "progress":
                progress.set()

        async with open_session(self.registry, "fixture", on_event=on_event) as session:
            value = await session.request("tools/call", {"name": "slow"})
            self.assertTrue(progress.is_set())
            self.assertEqual(value["structuredContent"]["value"], "finished")
            progress.clear()
            pending = asyncio.create_task(
                session.request("tools/call", {"name": "slow"})
            )
            await asyncio.wait_for(progress.wait(), 5)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            await asyncio.wait_for(session.wait_closed(), 5)

    async def test_input_callback_in_legacy_and_modern_protocols(self):
        for mode in ("legacy", "auto"):
            self.registry.update(
                "fixture",
                self.config.model_copy(
                    update={
                        "mode": mode,
                        "elicitation": True,
                        "sampling": True,
                        "roots": [self.root],
                    }
                ),
            )
            events = []

            async def reply(event):
                events.append(event)
                if event["method"] == "sampling/createMessage":
                    return {
                        "role": "assistant",
                        "model": "test",
                        "content": {"type": "text", "text": "sampled"},
                    }
                return {"action": "accept", "content": {"label": mode}}

            async with open_session(
                self.registry, "fixture", on_input=reply
            ) as session:
                response = await session.request("tools/call", {"name": "ask"})
                assisted = await session.request("tools/call", {"name": "assist"})
            self.assertEqual(response["structuredContent"]["value"], mode)
            self.assertEqual(
                assisted["structuredContent"]["value"],
                {"root": self.root.as_uri(), "sample": "sampled"},
            )
            self.assertEqual(
                [event["method"] for event in events],
                ["elicitation/create", "sampling/createMessage"],
            )

    async def test_startup_request_and_session_deadlines(self):
        hanging = self.config.model_copy(
            update={"startup_timeout": 0.25, "env": {"TEST_HANG_START": "yes"}}
        )
        self.registry.update("fixture", hanging)
        with self.assertRaises(ClientError) as failure:
            await execute(self.registry, "fixture", "tools/list")
        self.assertEqual(failure.exception.code, "startup_timeout")
        self.registry.update(
            "fixture", self.config.model_copy(update={"request_timeout": 0.12})
        )
        with self.assertRaises(ClientError) as failure:
            await execute(self.registry, "fixture", "tools/call", {"name": "slow"})
        self.assertEqual(failure.exception.code, "request_timeout")
        self.assertTrue(failure.exception.outcome_unknown)
        self.registry.update(
            "fixture", self.config.model_copy(update={"max_session_age": 0.2})
        )
        async with open_session(self.registry, "fixture") as session:
            await asyncio.wait_for(session.wait_closed(), 5)
            self.assertTrue(session.closed)

    async def test_cli_json_inputs_and_session_reuse_across_processes(self):
        legacy_config = {**self.config.model_dump(mode="json"), "allowed_tools": []}
        added = (
            await self.cli(
                "registry",
                "add",
                "cli",
                "--stdin",
                stdin=json.dumps(legacy_config).encode(),
            )
        )[0]
        self.assertTrue(added["ok"])
        self.assertEqual(self.registry.list(), ["cli", "fixture"])
        registry_data = json.loads(self.registry.path.read_text(encoding="utf-8"))
        cli_config = registry_data["servers"]["cli"]["config"]
        self.assertNotIn("allowed_tools", cli_config)
        cli_config["allowed_tools"] = []
        self.registry.path.write_text(json.dumps(registry_data), encoding="utf-8")
        response = (
            await self.cli(
                "call",
                "cli",
                "echo",
                "--arg",
                "label",
                "CLI",
            )
        )[0]
        self.assertEqual(response["result"]["structuredContent"]["value"], "CLI")
        opened = (await self.cli("session", "open", "fixture"))[0]["result"]
        token = opened["session_id"]

        async def close_if_open():
            try:
                await self.cli("session", "close", token)
            except AssertionError:
                pass

        self.addAsyncCleanup(close_if_open)
        self.assertEqual(
            (await self.cli("session", "status", token))[0]["result"]["session_id"],
            token,
        )
        values = []
        for _ in range(2):
            response = (
                await self.cli(
                    "session",
                    "request",
                    token,
                    "tools/call",
                    "--json",
                    '{"name":"state"}',
                )
            )[0]
            values.append(response["result"]["structuredContent"]["value"])
        self.assertEqual(values[0]["pid"], values[1]["pid"])
        self.assertEqual([value["calls"] for value in values], [1, 2])
        await self.cli("session", "close", token)
        with self.assertRaises(ProcessLookupError):
            os.kill(values[0]["pid"], 0)

    async def test_cli_request_reuses_project_state_and_cursor_in_explicit_session(
        self,
    ):
        self.registry.update(
            "fixture", self.config.model_copy(update={"mode": "legacy"})
        )
        opened = (await self.cli("session", "open", "fixture"))[0]
        session_id = opened["result"]["session_id"]
        session_option = ("--session", session_id)

        async def request(method, params):
            response = await self.cli(
                "request",
                "fixture",
                method,
                *session_option,
                "--json",
                json.dumps(params),
            )
            return response[0]["result"]

        try:
            instructions = await request("tools/call", {"name": "initial_instructions"})
            activated = await request(
                "tools/call",
                {
                    "name": "activate_project",
                    "arguments": {
                        "project": "other-project",
                        "session": instructions["structuredContent"]["value"],
                    },
                },
            )
            self.assertEqual(activated["structuredContent"]["value"], "other-project")
            page = await request("tools/list", {})
            following = await request("tools/list", {"cursor": page["nextCursor"]})
            self.assertIn("state", [tool["name"] for tool in following["tools"]])
            observed = (await self.cli("call", "fixture", "state", *session_option))[0][
                "result"
            ]
            self.assertEqual(
                observed["structuredContent"]["value"]["project"], "other-project"
            )

            other_registry = Registry(self.root / "other-servers.json")
            other_registry.add("fixture", self.config)
            self.registry.add("other-server", self.config)
            for server, registry_path in (
                ("other-server", self.registry.path),
                ("fixture", other_registry.path),
            ):
                mismatch = await self.cli(
                    "request",
                    server,
                    "tools/list",
                    *session_option,
                    registry_path=registry_path,
                    expected=1,
                )
                self.assertEqual(
                    mismatch[0]["error"]["code"], "session_target_mismatch"
                )
            self.assertEqual(len(self.marker.read_text().splitlines()), 1)
        finally:
            await self.cli("session", "close", session_id)

        closed = await self.cli(
            "request", "fixture", "tools/list", *session_option, expected=1
        )
        self.assertEqual(closed[0]["error"]["code"], "session_unavailable")
        self.assertEqual(len(self.marker.read_text().splitlines()), 1)
