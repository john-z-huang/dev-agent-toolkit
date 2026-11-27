"""Deterministic, offline MCP server for the standalone client tests."""

import itertools
import json
import os
import sys
import time
from pathlib import Path


def send(message):
    print(json.dumps({"jsonrpc": "2.0", **message}), flush=True)


def tool(name):
    return {
        "name": name,
        "description": name,
        "inputSchema": {"type": "object", "properties": {"label": {"type": "string"}}},
    }


def result(value, *, error=False):
    return {
        "content": [{"type": "text", "text": str(value)}],
        "structuredContent": {"value": value},
        "isError": error,
    }


def main():
    if marker := os.environ.get("TEST_MARKER"):
        with Path(marker).open("a") as stream:
            stream.write(f"{os.getpid()}\n")
    if os.environ.get("TEST_HANG_START"):
        time.sleep(60)
    legacy_only = os.environ.get("TEST_LEGACY_ONLY") == "yes"
    flavor = os.environ.get("TEST_FLAVOR", "original")
    modern = False
    calls = itertools.count(1)
    capabilities = {
        "tools": {"listChanged": True},
        "resources": {"subscribe": True, "listChanged": True},
        "prompts": {"listChanged": True},
        "completions": {},
    }
    server = {"name": "offline-fixture", "version": "1"}
    pending = {
        "method": "elicitation/create",
        "params": {
            "mode": "form",
            "message": "Choose a label",
            "requestedSchema": {
                "type": "object",
                "properties": {"label": {"type": "string"}},
                "required": ["label"],
            },
        },
    }
    for line in sys.stdin:
        message = json.loads(line)
        if "id" not in message:
            continue
        method = message["method"]
        params = message.get("params", {})
        request_id = message["id"]
        if method == "server/discover" and not legacy_only:
            modern = True
            reply = {
                "supportedVersions": ["2026-07-28"],
                "capabilities": capabilities,
                "_meta": {"io.modelcontextprotocol/serverInfo": server},
            }
        elif method == "initialize":
            reply = {
                "protocolVersion": "2025-11-25",
                "capabilities": capabilities,
                "serverInfo": server,
            }
        elif method == "tools/list":
            if params.get("cursor") == "more":
                reply = {
                    "tools": [
                        tool(name)
                        for name in (
                            "state",
                            "slow",
                            "broken",
                            "ask",
                            "assist",
                            "denied",
                        )
                    ]
                }
            else:
                reply = {"tools": [tool("echo")], "nextCursor": "more"}
        elif method == "tools/call":
            name = params["name"]
            if params.get("arguments", {}).get("label") == "rpc-error":
                send(
                    {
                        "id": request_id,
                        "error": {
                            "code": -32602,
                            "message": "Rejected fixture request",
                        },
                    }
                )
                continue
            if name == "slow":
                token = params.get("_meta", {}).get("progressToken")
                if token is not None:
                    send(
                        {
                            "method": "notifications/progress",
                            "params": {
                                "progressToken": token,
                                "progress": 1,
                                "total": 2,
                            },
                        }
                    )
                time.sleep(0.6)
                reply = result("finished")
            elif name == "state":
                reply = result(
                    {
                        "pid": os.getpid(),
                        "calls": next(calls),
                        "cwd": os.getcwd(),
                        "flavor": flavor,
                    }
                )
            elif name == "broken":
                reply = result("tool failed", error=True)
            elif name in {"ask", "assist"}:
                needed = (
                    {"label": pending}
                    if name == "ask"
                    else {
                        "roots": {"method": "roots/list"},
                        "sample": {
                            "method": "sampling/createMessage",
                            "params": {
                                "messages": [
                                    {
                                        "role": "user",
                                        "content": {"type": "text", "text": "Test"},
                                    }
                                ],
                                "maxTokens": 16,
                            },
                        },
                    }
                )
                if modern:
                    if "inputResponses" not in params:
                        send(
                            {
                                "id": request_id,
                                "result": {
                                    "resultType": "input_required",
                                    "inputRequests": needed,
                                    "requestState": "opaque-state",
                                },
                            }
                        )
                        continue
                    assert params["requestState"] == "opaque-state"
                    responses = params["inputResponses"]
                else:
                    responses = {}
                    for key, request in needed.items():
                        send({"id": key, **request})
                        responses[key] = json.loads(sys.stdin.readline())["result"]
                if name == "ask":
                    reply = result(responses["label"]["content"]["label"])
                else:
                    reply = result(
                        {
                            "root": responses["roots"]["roots"][0]["uri"],
                            "sample": responses["sample"]["content"]["text"],
                        }
                    )
            else:
                reply = result(params.get("arguments", {}).get("label", "echo"))
        elif method == "resources/list":
            reply = {"resources": [{"uri": "fixture://entry", "name": "Entry"}]}
        elif method == "resources/templates/list":
            reply = {
                "resourceTemplates": [
                    {"uriTemplate": "fixture://{name}", "name": "Entries"}
                ]
            }
        elif method == "resources/read":
            reply = {"contents": [{"uri": params["uri"], "text": "offline fixture"}]}
        elif method == "prompts/list":
            reply = {"prompts": [{"name": "welcome"}]}
        elif method == "prompts/get":
            reply = {
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": "Welcome"}}
                ]
            }
        elif method == "completion/complete":
            reply = {"completion": {"values": ["Alice"], "total": 1}}
        elif method in {"ping", "resources/subscribe", "resources/unsubscribe"}:
            reply = {}
        else:
            send(
                {
                    "id": request_id,
                    "error": {"code": -32601, "message": "Unknown method"},
                }
            )
            continue
        if modern:
            reply["resultType"] = "complete"
            if method in {
                "tools/list",
                "tools/call",
                "resources/list",
                "resources/templates/list",
                "resources/read",
                "prompts/list",
            }:
                reply.update(cacheScope="private", ttlMs=0)
        send({"id": request_id, "result": reply})


if __name__ == "__main__":
    main()
