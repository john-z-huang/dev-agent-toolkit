"""测试专用 Codex SDK 驱动；默认仅协议检查，--live 显式启用一次模型测试。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import tomllib
from unittest.mock import patch
from urllib.parse import urlsplit


MODEL = "gpt-6-luna"
EFFORT = "medium"
SERVER = "dev-workflow-standards-tools"
TOOL = "get_codex_session_summary_guidance"
ARGUMENTS = {"custom_questions": ["SDK smoke test question"], "custom_template": "SDK_SMOKE_TEMPLATE"}
CHECK_API_TOOL = "check_api_input"
CHECK_API_ARGUMENTS = {
    "request": {
        "purpose": "Review a synthetic request before external transmission",
        "content": "See /Users/example/private.log",
    }
}
API_FIELD_LIMIT = 32 * 1024


class SmokeFailure(Exception):
    """仅包含安全错误分类，不转发 SDK/HTTP/子进程原始异常。"""


def credentials() -> dict[str, str]:
    result = {}
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
        value = os.environ.get(name, "")
        if not value.strip():
            raise SmokeFailure("missing_" + name.lower())
        result[name] = value
    try:
        url = urlsplit(result["OPENAI_BASE_URL"])
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError
    except ValueError:
        raise SmokeFailure("invalid_base_url") from None
    return result


def settings(
    root: Path,
    site: Path,
    configuration: dict[str, str],
    *,
    server_executable: Path | None = None,
) -> tuple[dict, dict[str, str]]:
    """SDK provider 仅使用显式环境配置，MCP 子进程不继承 API 配置。"""
    launcher = (
        "import sys;sys.path.insert(0," + repr(str(site)) + ");"
        "import dev_workflow_standards_tools as package;"
        "assert package.__file__.startswith(" + repr(str(site) + os.sep) + ");"
        "from dev_workflow_standards_tools.server import main;main()"
    )
    if server_executable is None:
        server_command = sys.executable
        server_args = ["-I", "-c", launcher]
    else:
        server_command = str(server_executable)
        server_args = []
    config = {
        "model": MODEL,
        "model_reasoning_effort": EFFORT,
        "model_provider": "sdk_test",
        "model_providers": {"sdk_test": {
            "name": "SDK test provider",
            "base_url": configuration["OPENAI_BASE_URL"],
            "env_key": "OPENAI_API_KEY",
            "wire_api": "responses",
            "requires_openai_auth": False,
            "supports_websockets": False,
            "request_max_retries": 0,
            "stream_max_retries": 0,
        }},
        "mcp_servers": {SERVER: {
            "command": server_command,
            "args": server_args,
            "enabled_tools": [TOOL, CHECK_API_TOOL],
            "env_vars": [],
            "env": {"OPENAI_API_KEY": "", "OPENAI_BASE_URL": ""},
            "startup_timeout_sec": 30,
        }},
    }
    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "CODEX_HOME": str(root / "codex-state"),
        "RUST_LOG": "off",
        **configuration,
    }
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "all_proxy", "no_proxy", "SSL_CERT_FILE"):
        if name in os.environ:
            environment[name] = os.environ[name]
    return config, environment


def overrides(config: dict, prefix: str = "") -> tuple[str, ...]:
    """将受控结构变为 SDK 支持的 TOML 叶值覆盖，不向磁盘保存配置。"""
    result = []
    for key, value in config.items():
        name = prefix + key
        if isinstance(value, dict):
            result.extend(overrides(value, name + "."))
        else:
            result.append(name + "=" + json.dumps(value))
    return tuple(result)


def guidance_result(value: dict) -> None:
    if value.get("isError") or value.get("error"):
        raise SmokeFailure("mcp_tool_failed")
    body = value.get("structuredContent")
    if not isinstance(body, dict):
        for item in value.get("content", []):
            if item.get("type") == "text":
                try:
                    body = json.loads(item["text"])
                except (ValueError, KeyError):
                    continue
                break
    if not isinstance(body, dict) or body.get("ok") is not True or body.get("questions") != ARGUMENTS["custom_questions"] or body.get("template") != ARGUMENTS["custom_template"]:
        raise SmokeFailure("unexpected_mcp_result")


def _mapping(value) -> dict | None:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            result = value.model_dump(mode="json", by_alias=True)
        except Exception:
            return None
        return result if isinstance(result, dict) else None
    return None


def check_api_input_schema(value) -> None:
    """Require the installed tool's actual MCP schema to match its two-field contract."""
    tool = _mapping(value)
    schema = tool.get("inputSchema") if tool else None
    if not isinstance(schema, dict):
        raise SmokeFailure("check_api_input_schema_missing")
    properties = schema.get("properties")
    if (
        not isinstance(properties, dict)
        or set(properties) != {"request"}
        or set(schema.get("required", [])) != {"request"}
    ):
        raise SmokeFailure("check_api_input_schema_mismatch")
    request_schema = properties["request"]
    if not isinstance(request_schema, dict):
        raise SmokeFailure("check_api_input_schema_mismatch")
    reference = request_schema.get("$ref")
    if isinstance(reference, str):
        definitions = schema.get("$defs", schema.get("definitions"))
        key = reference.rsplit("/", 1)[-1]
        request_schema = definitions.get(key) if isinstance(definitions, dict) else None
    if not isinstance(request_schema, dict):
        raise SmokeFailure("check_api_input_schema_mismatch")
    fields = request_schema.get("properties")
    if (
        not isinstance(fields, dict)
        or set(fields) != {"purpose", "content"}
        or set(request_schema.get("required", [])) != {"purpose", "content"}
        or request_schema.get("additionalProperties") is not False
    ):
        raise SmokeFailure("check_api_input_schema_mismatch")
    for field in ("purpose", "content"):
        details = fields[field]
        if not isinstance(details, dict) or details.get("type") != "string" or details.get("minLength") != 1 or details.get("maxLength") != API_FIELD_LIMIT:
            raise SmokeFailure("check_api_input_schema_mismatch")


def check_api_input_result(value) -> None:
    result = _mapping(value)
    if result is None or result.get("isError") or result.get("error"):
        raise SmokeFailure("check_api_input_call_failed")
    body = result.get("structuredContent")
    if not isinstance(body, dict):
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    body = json.loads(item["text"])
                except (ValueError, KeyError):
                    continue
                break
    findings = body.get("findings") if isinstance(body, dict) else None
    if (
        not isinstance(body, dict)
        or body.get("passed") is not False
        or body.get("status") != "blocked_local"
        or body.get("stage") != "local"
        or body.get("external_review_performed") is not False
        or not isinstance(findings, list)
        or not any(item.get("field") == "content" and item.get("rule_id") == "path.absolute_local" for item in findings if isinstance(item, dict))
        or "/Users/example/private.log" in json.dumps(body, ensure_ascii=False)
    ):
        raise SmokeFailure("check_api_input_local_gate_failed")


def check_turn(turn: dict) -> int:
    if turn.get("status") != "completed" or turn.get("error") is not None:
        raise SmokeFailure("model_turn_failed")
    calls = []
    for item in turn.get("items", []):
        if item.get("type") in {"commandExecution", "fileChange", "collabAgentToolCall"}:
            raise SmokeFailure("unexpected_agent_action")
        if item.get("type") == "mcpToolCall":
            if item.get("server") != SERVER or item.get("tool") != TOOL or item.get("arguments") != ARGUMENTS:
                raise SmokeFailure("unexpected_mcp_call")
            if item.get("status") != "completed" or item.get("error") is not None:
                raise SmokeFailure("mcp_tool_failed")
            guidance_result(item.get("result") or {})
            calls.append(item)
    if not calls:
        raise SmokeFailure("missing_actual_mcp_call")
    if len(calls) != 1:
        raise SmokeFailure("unexpected_mcp_call_count")
    return len(calls)


def execute_sdk(
    root: Path,
    site: Path,
    configuration: dict[str, str],
    *,
    live: bool = False,
    installed_info: dict[str, str] | None = None,
) -> dict:
    # 延迟导入：普通离线测试及运行时包均不要求安装 SDK。
    try:
        from openai_codex import CodexConfig
        from openai_codex.client import CodexClient
        from openai_codex.generated.v2_all import ListMcpServerStatusResponse, McpServerToolCallResponse
    except ImportError:
        raise SmokeFailure("sdk_dependency_missing") from None

    config, environment = settings(
        root,
        site,
        configuration,
        server_executable=Path(installed_info["path"]) if installed_info else None,
    )
    (root / "codex-state").mkdir()
    workspace = root / "workspace"
    workspace.mkdir()
    timed_out = threading.Event()
    # SDK 启动时自身会合并环境；清空继承防止其他凭据、配置路径或 provider 覆盖混入。
    with patch.dict(os.environ, environment, clear=True):
        client = CodexClient(CodexConfig(
            cwd=str(workspace), env=environment,
            config_overrides=overrides(config),
        ))
        def expire():
            timed_out.set()
            client.close()
        timer = threading.Timer(120, expire)
        timer.daemon = True
        timer.start()
        try:
            with client:
                client.initialize()
                started = client.thread_start({
                    "model": MODEL, "modelProvider": "sdk_test", "config": {"model_reasoning_effort": EFFORT},
                    "cwd": str(workspace), "sandbox": "read-only", "approvalPolicy": "never",
                    "ephemeral": True,
                    "baseInstructions": "You are a test subject. Use only the specified read-only MCP tool with the exact synthetic arguments. Do not inspect files, use shell, write, or delegate.",
                })
                if started.model != MODEL or started.reasoning_effort is None or started.reasoning_effort.value != EFFORT or started.model_provider != "sdk_test":
                    raise SmokeFailure("model_or_effort_mismatch")
                thread_id = started.thread.id
                status = client.request("mcpServerStatus/list", {
                    "threadId": thread_id, "serverName": SERVER, "detail": "toolsAndAuthOnly",
                }, response_model=ListMcpServerStatusResponse)
                servers = [entry for entry in status.data if entry.name == SERVER]
                if (
                    len(servers) != 1
                    or servers[0].tools_error
                    or not isinstance(servers[0].tools, dict)
                    or TOOL not in servers[0].tools
                    or CHECK_API_TOOL not in servers[0].tools
                    or servers[0].server_capabilities is None
                ):
                    raise SmokeFailure("mcp_discovery_failed")
                check_api_input_schema(servers[0].tools[CHECK_API_TOOL])
                direct = client.request("mcpServer/tool/call", {
                    "threadId": thread_id, "server": SERVER, "tool": TOOL, "arguments": ARGUMENTS,
                }, response_model=McpServerToolCallResponse)
                guidance_result(_mapping(direct) or {})
                api_input_call = client.request("mcpServer/tool/call", {
                    "threadId": thread_id,
                    "server": SERVER,
                    "tool": CHECK_API_TOOL,
                    "arguments": CHECK_API_ARGUMENTS,
                }, response_model=McpServerToolCallResponse)
                check_api_input_result(_mapping(api_input_call) or {})
                calls = 0
                if live:
                    prompt = "Call " + TOOL + " exactly once with these arguments: " + json.dumps(ARGUMENTS) + ". Then reply OK. Do not answer without calling the tool."
                    turn = client.turn_start(thread_id, prompt, params={"model": MODEL, "effort": EFFORT})
                    client.register_turn_notifications(turn.turn.id)
                    items = []
                    try:
                        while True:
                            notification = client.next_turn_notification(turn.turn.id)
                            value = notification.payload.model_dump(mode="json", by_alias=True)
                            if notification.method == "item/completed":
                                items.append(value["item"])
                            if notification.method == "turn/completed":
                                calls = check_turn({**value["turn"], "items": items})
                                break
                    finally:
                        client.unregister_turn_notifications(turn.turn.id)
                result = {
                    "ok": True,
                    "model": MODEL,
                    "effort": EFFORT,
                    "mcp_discovery": "passed",
                    "direct_tool_call": "passed",
                    "check_api_input_schema": "passed",
                    "check_api_input_local_call": "passed",
                    "model_test": "passed" if live else "not_run",
                    "actual_model_tool_calls": calls,
                }
                if installed_info is not None:
                    result.update({
                        "install_source": "uv_tool",
                        "installed_executable": installed_info["path"],
                        "installed_version": installed_info["version"],
                    })
                else:
                    result["install_source"] = "wheel"
                return result
        except SmokeFailure:
            raise
        except Exception:
            raise SmokeFailure("sdk_timeout" if timed_out.is_set() else "sdk_request_failed") from None
        finally:
            timer.cancel()
            client.close()


def _project_version() -> str:
    project_file = Path(__file__).resolve().parents[1] / "mcp-server" / "pyproject.toml"
    try:
        project = tomllib.loads(project_file.read_text(encoding="utf-8"))
        version = project["project"]["version"]
    except Exception:
        raise SmokeFailure("project_version_unavailable") from None
    if not isinstance(version, str) or not version:
        raise SmokeFailure("project_version_unavailable")
    return version


def inspect_installed_executable(executable: Path) -> dict[str, str]:
    """核对 uv tool console entrypoint 与其安装环境中的包版本，不运行 MCP 服务。"""
    if not executable.is_absolute():
        raise SmokeFailure("installed_executable_must_be_absolute")
    try:
        resolved = executable.resolve(strict=True)
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise SmokeFailure("installed_executable_invalid")
        source = resolved.read_text(encoding="utf-8")
    except SmokeFailure:
        raise
    except Exception:
        raise SmokeFailure("installed_executable_unavailable") from None
    if "from dev_workflow_standards_tools.server import main" not in source:
        raise SmokeFailure("installed_executable_mismatch")
    interpreter_match = re.search(r"(?m)^'''exec' '([^']+)'", source)
    if interpreter_match is None:
        raise SmokeFailure("installed_executable_mismatch")
    try:
        interpreter_entrypoint = Path(interpreter_match.group(1))
        if not interpreter_entrypoint.is_absolute():
            raise SmokeFailure("installed_executable_mismatch")
        interpreter_target = interpreter_entrypoint.resolve(strict=True)
        if (
            not interpreter_target.is_file()
            or not os.access(interpreter_target, os.X_OK)
            or interpreter_entrypoint.parent.resolve() != resolved.parent.resolve()
        ):
            raise SmokeFailure("installed_executable_mismatch")
    except SmokeFailure:
        raise
    except Exception:
        raise SmokeFailure("installed_interpreter_unavailable") from None

    query = (
        "import importlib.metadata as m,json,pathlib;"
        "d=m.distribution('dev-workflow-standards-tools');"
        "p=pathlib.Path(d.locate_file('dev_workflow_standards_tools/server.py')).resolve();"
        "print(json.dumps({'version':d.version,'server':str(p)}))"
    )
    try:
        inspected = subprocess.run(
            [str(interpreter_entrypoint), "-I", "-c", query],
            text=True,
            capture_output=True,
            timeout=15,
            env={"PATH": os.defpath},
        )
        if inspected.returncode:
            raise SmokeFailure("installed_package_inspection_failed")
        metadata = json.loads(inspected.stdout)
        version = metadata.get("version")
        server_module = Path(metadata.get("server", "")).resolve(strict=True)
        environment_root = resolved.parent.parent.resolve()
        if (
            not isinstance(version, str)
            or version != _project_version()
            or not server_module.is_file()
            or not server_module.is_relative_to(environment_root)
        ):
            raise SmokeFailure("installed_package_mismatch")
    except SmokeFailure:
        raise
    except Exception:
        raise SmokeFailure("installed_package_inspection_failed") from None
    return {
        "path": str(resolved),
        "version": version,
        "module": str(server_module),
    }


def run(
    wheel: Path | None = None,
    *,
    installed_executable: Path | None = None,
    live: bool = False,
) -> dict:
    if (wheel is None) == (installed_executable is None):
        raise SmokeFailure("one_install_source_required")
    configuration = credentials()  # 缺配置时在 SDK 启动或 wheel 安装前停止。
    if wheel is not None:
        if not wheel.is_file() or wheel.suffix != ".whl":
            raise SmokeFailure("wheel_required")
        with tempfile.TemporaryDirectory(prefix="codex-sdk-test-") as temporary:
            root = Path(temporary).resolve()
            site = root / "installed"
            result = subprocess.run(["uv", "pip", "install", "--offline", "--no-deps", "--target", str(site), str(wheel.resolve())],
                                    text=True, capture_output=True, timeout=60)
            if result.returncode:
                raise SmokeFailure("wheel_install_failed")
            return execute_sdk(root, site, configuration, live=live)

    installed_info = inspect_installed_executable(installed_executable)
    with tempfile.TemporaryDirectory(prefix="codex-sdk-test-") as temporary:
        root = Path(temporary).resolve()
        installed_site = Path(installed_info["module"]).parent.parent
        return execute_sdk(root, installed_site, configuration, live=live, installed_info=installed_info)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="测试专用 Codex SDK：固定 gpt-6-luna/medium，无配置或模型回退")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--wheel", type=Path, help="待测完整 wheel")
    source.add_argument("--installed-executable", type=Path, help="已更新 uv tool 的绝对 MCP 可执行文件路径")
    parser.add_argument("--live", action="store_true", help="显式发起一次真实模型测试；默认只检查 SDK/MCP 协议")
    args = parser.parse_args(argv)
    try:
        result = run(args.wheel, installed_executable=args.installed_executable, live=args.live)
    except SmokeFailure as error:
        print(json.dumps({"ok": False, "error_code": str(error)}))
        return 1
    except Exception:
        print(json.dumps({"ok": False, "error_code": "test_setup_failed"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
