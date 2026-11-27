"""Offline interoperability checks for the modern protocol extensions."""

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
    open_session,
)

TASK_EXTENSION = "io.modelcontextprotocol/tasks"
SUBSCRIPTION_ID = "io.modelcontextprotocol/subscriptionId"


def _send(**message):
    print(json.dumps({"jsonrpc": "2.0", **message}), flush=True)


def _complete(**fields):
    return {"resultType": "complete", **fields}


def _tool_result(text):
    return _complete(
        content=[{"type": "text", "text": text}],
        structuredContent={"value": text},
        cacheScope="private",
        ttlMs=0,
    )


def _task(kind, status, **fields):
    return {
        "resultType": kind,
        "taskId": "fixture-task",
        "status": status,
        "createdAt": "2026-07-28T00:00:00Z",
        "lastUpdatedAt": "2026-07-28T00:00:00Z",
        "ttlMs": None,
        "pollIntervalMs": 10,
        **fields,
    }


def _serve_fixture(mode):
    label = None
    for line in sys.stdin:
        message = json.loads(line)
        if "id" not in message:
            continue
        request_id = message["id"]
        params = message.get("params", {})
        match message["method"]:
            case "server/discover":
                capabilities = {"tools": {"listChanged": True}}
                if mode != "unadvertised":
                    capabilities["extensions"] = {TASK_EXTENSION: {}}
                reply = _complete(
                    supportedVersions=["2026-07-28"], capabilities=capabilities
                )
            case "tools/list":
                reply = _complete(
                    tools=[{"name": "demo", "inputSchema": {"type": "object"}}],
                    cacheScope="private",
                    ttlMs=0,
                )
            case "tools/call":
                advertised = params["_meta"][
                    "io.modelcontextprotocol/clientCapabilities"
                ].get("extensions", {})
                reply = (
                    _task("task", "working")
                    if TASK_EXTENSION in advertised
                    else _tool_result("inline")
                )
            case "tasks/get":
                assert params["taskId"] == "fixture-task"
                if mode == "hanging":
                    reply = _task("complete", "working")
                elif label is None:
                    reply = _task(
                        "complete",
                        "input_required",
                        inputRequests={
                            "question": {
                                "method": "elicitation/create",
                                "params": {
                                    "message": "Choose a label",
                                    "requestedSchema": {
                                        "type": "object",
                                        "properties": {"label": {"type": "string"}},
                                        "required": ["label"],
                                    },
                                },
                            }
                        },
                    )
                else:
                    reply = _task("complete", "completed", result=_tool_result(label))
            case "tasks/update":
                label = params["inputResponses"]["question"]["content"]["label"]
                reply = _complete()
            case "tasks/cancel":
                Path(os.environ["CANCEL_MARKER"]).write_text(params["taskId"])
                reply = _complete()
            case "subscriptions/listen":
                assert params["notifications"] == {"toolsListChanged": True}
                meta = {SUBSCRIPTION_ID: request_id}
                _send(
                    method="notifications/subscriptions/acknowledged",
                    params={"_meta": meta, "notifications": params["notifications"]},
                )
                _send(method="notifications/tools/list_changed", params={"_meta": meta})
                reply = _complete(_meta=meta)
            case _:
                _send(
                    id=request_id, error={"code": -32601, "message": "Unknown method"}
                )
                continue
        _send(id=request_id, result=reply)


class MCPClientExtensionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.registry = Registry(self.root / "registry.json")

    def _register(self, *, mode="normal", tasks=False):
        self.registry.add(
            "fixture",
            ServerConfig(
                command=sys.executable,
                args=["-B", str(Path(__file__).resolve()), "--fixture", mode],
                cwd=self.root,
                env={"CANCEL_MARKER": str(self.root / "cancelled")},
                allowed_tools=["demo"],
                tasks=tasks,
                elicitation=True,
                request_timeout=5,
            ),
        )

    async def test_tasks_opt_in_and_terminal_result_after_input(self):
        self._register(tasks=True)
        events = []

        async def on_event(event):
            events.append(event)

        async def on_input(event):
            self.assertEqual(event["method"], "elicitation/create")
            return {"action": "accept", "content": {"label": "ready"}}

        async with open_session(
            self.registry, "fixture", on_event=on_event, on_input=on_input
        ) as session:
            result = await session.request("tools/call", {"name": "demo"})
        self.assertEqual(result["structuredContent"], {"value": "ready"})
        self.assertEqual(
            [event["status"] for event in events],
            ["working", "input_required", "completed"],
        )

    async def test_tasks_default_off(self):
        self._register()
        async with open_session(self.registry, "fixture") as session:
            result = await session.request("tools/call", {"name": "demo"})
        self.assertEqual(result["structuredContent"], {"value": "inline"})

    async def test_unadvertised_task_result_is_rejected(self):
        self._register(mode="unadvertised", tasks=True)
        async with open_session(self.registry, "fixture") as session:
            with self.assertRaises(ClientError) as failed:
                await session.request("tools/call", {"name": "demo"})
        self.assertEqual(failed.exception.code, "protocol_error")
        self.assertTrue(failed.exception.outcome_unknown)

    async def test_cancelling_call_sends_task_cancel(self):
        self._register(mode="hanging", tasks=True)
        started = asyncio.Event()

        async def on_event(event):
            if event["type"] == "task" and event["status"] == "working":
                started.set()

        async with open_session(self.registry, "fixture", on_event=on_event) as session:
            calling = asyncio.create_task(
                session.request("tools/call", {"name": "demo"})
            )
            await asyncio.wait_for(started.wait(), 5)
            calling.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await calling
            await asyncio.wait_for(session.wait_closed(), 5)
        self.assertEqual((self.root / "cancelled").read_text(), "fixture-task")

    async def test_subscription_ack_and_change_emitted_once(self):
        self._register()
        events = []

        async def on_event(event):
            events.append(event)

        async with open_session(self.registry, "fixture", on_event=on_event) as session:
            response = await session.request(
                "subscriptions/listen", {"notifications": {"toolsListChanged": True}}
            )
        self.assertEqual(response["notifications"], {"toolsListChanged": True})
        self.assertEqual(
            [event["type"] for event in events], ["subscription", "notification"]
        )
        self.assertEqual(events[1]["method"], "notifications/tools/list_changed")
        self.assertEqual(
            events[1]["params"]["_meta"][SUBSCRIPTION_ID], response["subscriptionId"]
        )


if __name__ == "__main__" and sys.argv[1:2] == ["--fixture"]:
    _serve_fixture(sys.argv[2])
