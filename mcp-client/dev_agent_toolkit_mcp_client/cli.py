"""Standalone JSON command-line interface for the MCP client."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Never

from pydantic import ValidationError

from .api import EventHandler, execute, execute_batch, request_outcome
from .registry import ClientError, Registry, ServerConfig


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise ClientError("invalid_arguments", "Invalid CLI arguments. See --help.")


def _json_options(
    parser: argparse.ArgumentParser, *, string_arguments: bool = False
) -> None:
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--json", help="read JSON from a command argument")
    source.add_argument("--file", type=Path, help="read JSON from a UTF-8 file")
    source.add_argument("--stdin", action="store_true", help="read JSON from stdin")
    if string_arguments:
        source.add_argument(
            "--arg",
            action="append",
            nargs=2,
            metavar=("NAME", "VALUE"),
            help="set a string tool argument (repeatable)",
        )


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="dev_agent_toolkit_mcp_client_cli",
        description="Call explicitly configured local MCP servers",
    )
    parser.add_argument("--registry", type=Path, help="use this server registry file")
    parser.add_argument(
        "--events",
        action="store_true",
        help="emit progress and the final result as JSON Lines",
    )
    groups = parser.add_subparsers(dest="group", required=True)

    commands = groups.add_parser(
        "registry", help="manage local server configurations"
    ).add_subparsers(dest="action", required=True)
    commands.add_parser("list")
    for action in ("add", "update", "get", "remove"):
        command = commands.add_parser(action)
        command.add_argument("server")
        if action in {"add", "update"}:
            _json_options(command)

    server = groups.add_parser("server", help="inspect a server")
    server.add_subparsers(dest="action", required=True).add_parser("info").add_argument(
        "server"
    )
    for group, target, summary in (
        ("request", "method", "send an MCP request"),
        ("call", "tool", "call a tool with its arguments"),
    ):
        command = groups.add_parser(group, help=summary)
        command.add_argument("server")
        command.add_argument(target)
        command.add_argument(
            "--session",
            dest="session_id",
            metavar="ID",
            help="reuse a session opened for this server",
        )
        _json_options(command, string_arguments=group == "call")
    batch = groups.add_parser(
        "batch", help="execute method or tool steps in one connection"
    )
    batch.add_argument("server")
    _json_options(batch)

    sessions = groups.add_parser(
        "session", help="use a temporary cross-command session"
    ).add_subparsers(dest="action", required=True)
    sessions.add_parser("open").add_argument("server")
    for action in ("status", "request", "respond", "cancel", "close"):
        command = sessions.add_parser(action)
        command.add_argument("session_id")
        if action == "request":
            command.add_argument("method")
        if action in {"request", "respond"}:
            _json_options(command)
    return parser


def _read_json(args: argparse.Namespace, default: Any = None) -> Any:
    try:
        if args.json is not None:
            return json.loads(args.json)
        if args.file is not None:
            return json.loads(args.file.read_text(encoding="utf-8"))
        if args.stdin:
            return json.load(sys.stdin)
    except (ValueError, OSError, RecursionError):
        raise ClientError("invalid_json", "Cannot read valid JSON input") from None
    return default


def _params(args: argparse.Namespace) -> dict[str, Any]:
    if args.group == "call" and args.arg is not None:
        arguments = dict(args.arg)
        if "" in arguments or len(arguments) != len(args.arg):
            raise ClientError(
                "invalid_request", "Argument names must be nonempty and unique"
            )
        return arguments
    params = _read_json(args, {})
    if not isinstance(params, dict):
        raise ClientError("invalid_request", "Request parameters must be a JSON object")
    return params


def _registry_command(args: argparse.Namespace, registry: Registry) -> dict[str, Any]:
    if args.action == "list":
        return {"servers": registry.list()}
    if args.action == "remove":
        registry.remove(args.server)
        return {"server": args.server}
    if args.action == "get":
        config = registry.get(args.server).config
        return {"server": args.server, "config": config.model_dump(mode="json")}
    try:
        config = ServerConfig.model_validate(_read_json(args))
    except ValidationError as error:
        fields = sorted(
            {
                str(item["loc"][0])
                for item in error.errors()
                if item["loc"] and item["loc"][0] in ServerConfig.model_fields
            }
        )
        detail = f" ({', '.join(fields)})" if fields else ""
        raise ClientError(
            "invalid_config", f"Invalid server configuration{detail}"
        ) from None
    if args.action == "add":
        registry.add(args.server, config)
    else:
        registry.update(args.server, config)
    return {"server": args.server}


def _emit(record: dict[str, Any]) -> None:
    print(json.dumps({"schema_version": 1, **record}, ensure_ascii=True), flush=True)


async def _event(event: dict[str, Any]) -> None:
    _emit({"type": "event", "event": event})


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    registry = Registry(args.registry)
    callback: EventHandler | None = _event if args.events else None
    if args.group == "registry":
        return {"ok": True, "result": _registry_command(args, registry)}
    if args.group == "server":
        return {
            "ok": True,
            "result": await execute(registry, args.server, "server/info"),
        }
    if args.group in {"request", "call"}:
        params = _params(args)
        method = "tools/call" if args.group == "call" else args.method
        if args.group == "call":
            params = {"name": args.tool, "arguments": params}
        if args.session_id is None:
            result = await execute(
                registry, args.server, method, params, on_event=callback
            )
        else:
            from .worker import worker_request

            result = await worker_request(
                args.session_id,
                "request_for",
                {
                    "server": args.server,
                    "registry": str(registry.path),
                    "method": method,
                    "params": params,
                },
                on_event=callback,
            )
        return request_outcome(method, result)
    if args.group == "batch":
        return await execute_batch(
            registry, args.server, _read_json(args), on_event=callback
        )

    from .worker import open_worker, worker_request

    if args.action == "open":
        return {"ok": True, "result": await open_worker(registry, args.server)}
    if args.action == "request":
        result = await worker_request(
            args.session_id,
            "request",
            {"method": args.method, "params": _params(args)},
            on_event=callback,
        )
        return request_outcome(args.method, result)
    payload = _params(args) if args.action == "respond" else None
    return {
        "ok": True,
        "result": await worker_request(args.session_id, args.action, payload),
    }


def main(argv: list[str] | None = None) -> int:
    sdk_logger = logging.getLogger("mcp")
    previous_level = sdk_logger.level
    sdk_logger.setLevel(logging.CRITICAL + 1)
    try:
        args = _parser().parse_args(argv)
        reply = asyncio.run(_run(args))
    except ClientError as error:
        _emit({"type": "result", "ok": False, "error": error.as_dict()})
        return (
            2
            if error.code
            in {
                "invalid_arguments",
                "invalid_json",
                "invalid_config",
                "invalid_request",
            }
            else 1
        )
    except KeyboardInterrupt:
        error = ClientError("cancelled", "The command was cancelled")
        _emit({"type": "result", "ok": False, "error": error.as_dict()})
        return 130
    finally:
        sdk_logger.setLevel(previous_level)
    _emit({"type": "result", **reply})
    return 0 if reply["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
