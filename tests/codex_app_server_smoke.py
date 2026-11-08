"""测试专用 Codex App Server 驱动；默认仅协议检查，--live 显式启用一次模型测试。"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from codex_app_server_client import AppServerClient, SmokeFailure

MODEL = "gpt-6-luna"
EFFORT = "medium"
SERVER = "dev-workflow-standards-tools"
TOOL = "get_codex_session_summary_guidance"
ARGUMENTS = {
    "custom_questions": ["App Server 冒烟测试问题"],
    "custom_template": "APP_SERVER_SMOKE_TEMPLATE",
}
CHECK_API_TOOL = "check_api_input"
CHECK_API_ARGUMENTS = {
    "request": {
        "purpose": "在外发前审查合成请求",
        "content": "Authorization: Bearer AbC123def456GhI789",
    }
}
LIVE_REVIEW_ARGUMENTS = {
    "request": {
        "purpose": "审核合成开发事实",
        "content": "src/example.py 对空列表返回空结果；此处仅为合成测试事实。",
    }
}
API_FIELD_LIMIT = 32 * 1024
NETWORK_ENV_VARS = (
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "all_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
)


def credentials() -> dict[str, str]:
    result = {}
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
        value = os.environ.get(name, "")
        if not value.strip():
            raise SmokeFailure("missing_" + name.lower())
        result[name] = value
    try:
        url = urlsplit(result["OPENAI_BASE_URL"])
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
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
    live_review: bool = False,
) -> tuple[dict, dict[str, str]]:
    """App Server provider 使用显式配置；仅 live 测试向 MCP 转发 API 变量名称。"""
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
        "model_provider": "app_server_test",
        "features": {
            "apps": False,
            "plugins": False,
            "api_key_model_discovery": False,
            "multi_agent": False,
        },
        "model_providers": {
            "app_server_test": {
                "name": "App Server test provider",
                "base_url": configuration["OPENAI_BASE_URL"],
                "env_key": "OPENAI_API_KEY",
                "wire_api": "responses",
                "requires_openai_auth": False,
                "supports_websockets": False,
                "request_max_retries": 0,
                "stream_max_retries": 0,
            }
        },
        "mcp_servers": {
            SERVER: {
                "command": server_command,
                "args": server_args,
                "enabled_tools": [TOOL, CHECK_API_TOOL],
                "env_vars": ["OPENAI_API_KEY", "OPENAI_BASE_URL", *NETWORK_ENV_VARS]
                if live_review
                else [],
                "env": {"OPENAI_TIMEOUT_MAX_RETRIES": "0"}
                if live_review
                else {"OPENAI_API_KEY": "", "OPENAI_BASE_URL": ""},
                "startup_timeout_sec": 30,
            }
        },
    }
    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "CODEX_HOME": str(root / "codex-state"),
        "RUST_LOG": "off",
        **configuration,
    }
    for name in NETWORK_ENV_VARS:
        if name in os.environ:
            environment[name] = os.environ[name]
    return config, environment


def overrides(config: dict, prefix: str = "") -> tuple[str, ...]:
    """将受控结构变为 App Server 支持的 TOML 叶值覆盖，不向磁盘保存配置。"""
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
    if (
        not isinstance(body, dict)
        or body.get("ok") is not True
        or body.get("questions") != ARGUMENTS["custom_questions"]
        or body.get("template") != ARGUMENTS["custom_template"]
    ):
        raise SmokeFailure("unexpected_mcp_result")


def _mapping(value) -> dict | None:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            result = value.model_dump(mode="json", by_alias=True)
        except Exception:
            logging.getLogger(__name__).exception(
                "unexpected_boundary_failure", exc_info=False
            )
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
        if (
            not isinstance(details, dict)
            or details.get("type") != "string"
            or details.get("minLength") != 1
            or details.get("maxLength") != API_FIELD_LIMIT
        ):
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
        or not any(
            item.get("field") == "content"
            and item.get("rule_id") == "credential.bearer"
            for item in findings
            if isinstance(item, dict)
        )
        or "AbC123def456GhI789" in json.dumps(body, ensure_ascii=False)
    ):
        raise SmokeFailure("check_api_input_local_gate_failed")


def check_api_input_external_result(value) -> None:
    result = _mapping(value)
    body = result.get("structuredContent") if result else None
    if not isinstance(body, dict) and result:
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    body = json.loads(item["text"])
                except (ValueError, KeyError):
                    continue
                break
    if isinstance(body, dict) and body.get("passed") is not True:
        # Only publish known safe classifications, never arbitrary API/MCP text.
        code = body.get("error_code")
        if code in {
            "missing_api_key",
            "missing_base_url",
            "client_initialization_failed",
            "api_connection_failed",
            "api_timeout",
            "api_status_error",
            "model_refusal",
            "invalid_decision_response",
            "request_too_large",
        }:
            raise SmokeFailure("check_api_input_" + code)
        status = body.get("status")
        if status in {
            "blocked_local",
            "needs_revision",
            "insufficient_evidence",
            "unavailable",
        }:
            raise SmokeFailure("check_api_input_" + status)
    if (
        not result
        or result.get("isError")
        or result.get("error")
        or not isinstance(body, dict)
        or body.get("passed") is not True
        or body.get("status") != "passed"
        or body.get("stage") != "complete"
        or body.get("external_review_performed") is not True
        or body.get("policy_version") != "2026-11-05.5"
        or not isinstance(body.get("input_hash"), str)
        or len(body["input_hash"]) != 64
        or body.get("findings") != []
    ):
        raise SmokeFailure("check_api_input_external_review_failed")


def check_turn(turn: dict) -> int:
    if turn.get("status") != "completed" or turn.get("error") is not None:
        raise SmokeFailure("model_turn_failed")
    calls = []
    for item in turn.get("items", []):
        if item.get("type") in {
            "commandExecution",
            "fileChange",
            "collabAgentToolCall",
        }:
            raise SmokeFailure("unexpected_agent_action")
        if item.get("type") == "mcpToolCall":
            if (
                item.get("server") != SERVER
                or item.get("tool") != TOOL
                or item.get("arguments") != ARGUMENTS
            ):
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


def _read_live_turn(client: AppServerClient, thread_id: str, prompt: str) -> int:
    """保留响应前到达的通知，并且仅核对当前 thread/turn 的真实完成事件。"""
    started = client.request(
        "turn/start",
        {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
            "model": MODEL,
            "effort": EFFORT,
        },
    )
    turn_id = started["turn"]["id"]
    items = []
    while True:
        notification = client.next_turn_notification(thread_id, turn_id)
        value = notification["params"]
        if notification["method"] == "item/completed":
            items.append(value["item"])
        if notification["method"] == "turn/completed":
            return check_turn({**value["turn"], "items": items})


def _start_thread(client: AppServerClient, workspace: Path) -> str:
    started = client.request(
        "thread/start",
        {
            "model": MODEL,
            "modelProvider": "app_server_test",
            "config": {"model_reasoning_effort": EFFORT},
            "cwd": str(workspace),
            "sandbox": "read-only",
            "approvalPolicy": "never",
            "ephemeral": True,
            "baseInstructions": "你正在接受测试。仅可使用指定的只读 MCP 工具，并严格使用给定的合成参数。不得查看文件、使用 Shell、写入或委派任务。",
        },
    )
    if (
        started.get("model") != MODEL
        or started.get("reasoningEffort") != EFFORT
        or started.get("modelProvider") != "app_server_test"
    ):
        raise SmokeFailure("model_or_effort_mismatch")
    return started["thread"]["id"]


def _discover_tools(client: AppServerClient, thread_id: str):
    status = client.request(
        "mcpServerStatus/list",
        {
            "threadId": thread_id,
            "serverName": SERVER,
            "detail": "toolsAndAuthOnly",
        },
    )
    servers = [entry for entry in status.get("data", []) if entry.get("name") == SERVER]
    if len(servers) != 1:
        raise SmokeFailure("mcp_discovery_failed")
    server = servers[0]
    tools = server.get("tools")
    if (
        server.get("toolsError")
        or not isinstance(tools, dict)
        or TOOL not in tools
        or CHECK_API_TOOL not in tools
        or server.get("serverCapabilities") is None
    ):
        raise SmokeFailure("mcp_discovery_failed")
    check_api_input_schema(tools[CHECK_API_TOOL])


def _call(client: AppServerClient, thread_id: str, tool: str, arguments: dict) -> dict:
    return client.request(
        "mcpServer/tool/call",
        {
            "threadId": thread_id,
            "server": SERVER,
            "tool": tool,
            "arguments": arguments,
        },
    )


def _exercise_tools(client: AppServerClient, thread_id: str, live: bool) -> int:
    _discover_tools(client, thread_id)
    guidance_result(_call(client, thread_id, TOOL, ARGUMENTS))
    check_api_input_result(
        _call(client, thread_id, CHECK_API_TOOL, CHECK_API_ARGUMENTS)
    )
    if not live:
        return 0
    check_api_input_external_result(
        _call(client, thread_id, CHECK_API_TOOL, LIVE_REVIEW_ARGUMENTS)
    )
    prompt = (
        "严格调用 "
        + TOOL
        + " 一次，参数如下："
        + json.dumps(ARGUMENTS)
        + "。随后回复 OK。不得在未调用该工具时直接回答。"
    )
    return _read_live_turn(client, thread_id, prompt)


def execute_app_server(
    root: Path,
    site: Path,
    configuration: dict[str, str],
    *,
    live: bool = False,
    installed_info: dict[str, str] | None = None,
) -> dict:
    config, environment = settings(
        root,
        site,
        configuration,
        server_executable=Path(installed_info["path"]) if installed_info else None,
        live_review=live,
    )
    (root / "codex-state").mkdir()
    workspace = root / "workspace"
    workspace.mkdir()
    try:
        with AppServerClient(
            cwd=str(workspace), env=environment, config_overrides=overrides(config)
        ) as client:
            client.initialize()
            thread_id = _start_thread(client, workspace)
            calls = _exercise_tools(client, thread_id, live)
    except SmokeFailure:
        raise
    except Exception:
        logging.getLogger(__name__).exception(
            "unexpected_boundary_failure", exc_info=False
        )
        raise SmokeFailure("app_server_request_failed") from None
    result = {
        "ok": True,
        "model": MODEL,
        "effort": EFFORT,
        "mcp_discovery": "passed",
        "direct_tool_call": "passed",
        "check_api_input_schema": "passed",
        "check_api_input_local_call": "passed",
        "check_api_input_external_review": "passed" if live else "not_run",
        "model_test": "passed" if live else "not_run",
        "actual_model_tool_calls": calls,
        "app_server_cli": client.cli_info,
    }
    if installed_info is not None:
        result.update(
            {
                "install_source": "uv_tool",
                "installed_executable": installed_info["path"],
                "installed_version": installed_info["version"],
            }
        )
    else:
        result["install_source"] = "wheel"
    return result


def _project_version() -> str:
    project_file = Path(__file__).resolve().parents[1] / "mcp-server" / "pyproject.toml"
    try:
        project = tomllib.loads(project_file.read_text(encoding="utf-8"))
        version = project["project"]["version"]
    except Exception:
        logging.getLogger(__name__).exception(
            "project_version_unavailable", exc_info=False
        )
        raise SmokeFailure("project_version_unavailable") from None
    if not isinstance(version, str) or not version:
        raise SmokeFailure("project_version_unavailable")
    return version


def _installed_interpreter(resolved: Path, source: str) -> Path:
    """解释器必须来自被核验入口的同一安装目录，拒绝其他环境的替代项。"""
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
        logging.getLogger(__name__).exception(
            "installed_interpreter_unavailable", exc_info=False
        )
        raise SmokeFailure("installed_interpreter_unavailable") from None
    return interpreter_entrypoint


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
        logging.getLogger(__name__).exception(
            "installed_executable_unavailable", exc_info=False
        )
        raise SmokeFailure("installed_executable_unavailable") from None
    if "from dev_workflow_standards_tools.server import main" not in source:
        raise SmokeFailure("installed_executable_mismatch")
    interpreter_entrypoint = _installed_interpreter(resolved, source)

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
            check=False,
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
        logging.getLogger(__name__).exception(
            "installed_package_inspection_failed", exc_info=False
        )
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
    configuration = credentials()  # 缺配置时在 App Server 启动或 wheel 安装前停止。
    if wheel is not None:
        if not wheel.is_file() or wheel.suffix != ".whl":
            raise SmokeFailure("wheel_required")
        with tempfile.TemporaryDirectory(prefix="codex-app-server-test-") as temporary:
            root = Path(temporary).resolve()
            site = root / "installed"
            result = subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--offline",
                    "--no-deps",
                    "--target",
                    str(site),
                    str(wheel.resolve()),
                ],
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )
            if result.returncode:
                raise SmokeFailure("wheel_install_failed")
            return execute_app_server(root, site, configuration, live=live)

    installed_info = inspect_installed_executable(installed_executable)
    with tempfile.TemporaryDirectory(prefix="codex-app-server-test-") as temporary:
        root = Path(temporary).resolve()
        installed_site = Path(installed_info["module"]).parent.parent
        return execute_app_server(
            root,
            installed_site,
            configuration,
            live=live,
            installed_info=installed_info,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="测试专用 Codex App Server：固定 gpt-6-luna/medium，无配置或模型回退"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--wheel", type=Path, help="待测完整 wheel")
    source.add_argument(
        "--installed-executable",
        type=Path,
        help="已更新 uv tool 的绝对 MCP 可执行文件路径",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="显式发起一次真实模型测试；默认只检查 App Server/MCP 协议",
    )
    args = parser.parse_args(argv)
    try:
        result = run(
            args.wheel, installed_executable=args.installed_executable, live=args.live
        )
    except SmokeFailure as error:
        print(json.dumps({"ok": False, "error_code": str(error)}))
        return 1
    except Exception:
        logging.getLogger(__name__).exception("test_setup_failed", exc_info=False)
        print(json.dumps({"ok": False, "error_code": "test_setup_failed"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
