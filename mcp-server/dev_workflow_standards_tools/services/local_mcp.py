"""One-shot, offline access to the replacement uv tool process."""

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool

from .. import SERVER_NAME

BRIDGE_NAME = "call_updated_local_mcp"
BRIDGE_METADATA_KEY = "dev-workflow-standards/local-stdio"
REQUEST_TIMEOUT_SECONDS = 20


def _installed_executable() -> Path | None:
    """Use the stable uv tool environment of the calling MCP or management CLI."""
    prefix = Path(sys.prefix).resolve()
    if prefix.name != SERVER_NAME or not (prefix / "uv-receipt.toml").is_file():
        return None
    relative = f"Scripts/{SERVER_NAME}.exe" if os.name == "nt" else f"bin/{SERVER_NAME}"
    executable = (prefix / relative).resolve(strict=True)
    if (
        executable.is_relative_to(prefix)
        and executable.is_file()
        and os.access(executable, os.X_OK)
    ):
        return executable
    return None


def _eligible(tool: Tool) -> bool:
    annotations = tool.annotations
    return (
        tool.name != BRIDGE_NAME
        and (tool.meta or {}).get(BRIDGE_METADATA_KEY) is True
        and annotations is not None
        and annotations.read_only_hint is True
        and annotations.open_world_hint is False
        and annotations.destructive_hint is not True
    )


def _failure(status: str) -> dict[str, Any]:
    return {"ok": False, "status": status}


async def call_updated_local_mcp(
    tool_name: str | None = None,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Discover or call one explicitly supported tool in the fresh stdio server."""
    if tool_name is None:
        if arguments is not None:
            return _failure("invalid_request")
    elif not isinstance(tool_name, str) or not re.fullmatch(
        r"[a-z][a-z0-9_]{0,127}", tool_name
    ):
        return _failure("invalid_request")
    if arguments is not None and not isinstance(arguments, dict):
        return _failure("invalid_request")
    if tool_name == BRIDGE_NAME:
        return _failure("tool_not_available")

    try:
        executable = _installed_executable()
    except (OSError, RuntimeError):
        return _failure("installation_unavailable")
    if executable is None:
        return _failure("installation_unavailable")

    # Keep the launch independent of the Codex connection, its forwarded API
    # credentials, and the repository serving as the caller's working directory.
    params = StdioServerParameters(
        command=str(executable),
        cwd=executable.parent,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"},
    )
    try:
        with open(os.devnull, "w") as stderr:
            transport = stdio_client(params, errlog=stderr)
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS), Client(
                transport, mode="legacy", input_required_max_rounds=0, cache=None
            ) as client:
                server = client.server_info
                if server is None or server.name != SERVER_NAME:
                    return _failure("server_mismatch")
                listing = await client.list_tools()
                if listing.next_cursor is not None:
                    # This service publishes a complete catalog in one response.
                    return _failure("incomplete_discovery")
                available = {tool.name: tool for tool in listing.tools if _eligible(tool)}
                if tool_name is None:
                    return {
                        "ok": True,
                        "status": "listed",
                        "server_version": server.version,
                        "tools": [
                            tool.model_dump(mode="json", by_alias=True, exclude_none=True)
                            for tool in available.values()
                        ],
                    }
                if tool_name not in available:
                    return _failure("tool_not_available")
                result = await client.call_tool(tool_name, arguments or {})
                if result.is_error:
                    return _failure("tool_error")
                target_failed = (result.structured_content or {}).get("ok") is False
                return {
                    "ok": not target_failed,
                    "status": "target_failed" if target_failed else "called",
                    "server_version": server.version,
                    "tool_name": tool_name,
                    "result": result.model_dump(mode="json", by_alias=True, exclude_none=True),
                }
    except TimeoutError:
        return _failure("timeout")
    except Exception:
        # A child launch, initialization or protocol error may include raw inputs.
        return _failure("stdio_failed")
