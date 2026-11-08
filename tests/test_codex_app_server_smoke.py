from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
import tempfile
import tomllib
import unittest
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dev_workflow_standards_tools.server import mcp
from mcp import Client

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "codex_app_server_smoke", Path(__file__).with_name("codex_app_server_smoke.py")
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def _local_smoke_tool_result(tool_name: str) -> dict:
    """返回两个允许只读工具的合成响应，拒绝未声明的工具调用。"""
    if tool_name == smoke.TOOL:
        return {
            "isError": False,
            "structuredContent": {
                "ok": True,
                "questions": smoke.ARGUMENTS["custom_questions"],
                "template": smoke.ARGUMENTS["custom_template"],
            },
        }
    if tool_name == smoke.CHECK_API_TOOL:
        return {
            "isError": False,
            "structuredContent": {
                "passed": False,
                "status": "blocked_local",
                "stage": "local",
                "external_review_performed": False,
                "error_code": "sensitive_input_detected",
                "findings": [{"field": "content", "rule_id": "credential.bearer"}],
            },
        }
    raise AssertionError("unexpected tool")


class _LocalSmokeClient:
    """使用原始 JSON 字典的本地 App Server 协议替身。"""

    def __init__(self, *, schema: dict, instances: list[object], **config):
        self.config = config
        self.schema = schema
        self.requests = []
        self.closed = False
        self.cli_info = {"path": "/synthetic/bin/codex", "version": "0.167.0"}
        instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.closed = True

    def initialize(self):
        pass

    def request(self, method, params):
        self.requests.append((method, params))
        if method == "thread/start":
            return {
                "model": smoke.MODEL,
                "reasoningEffort": smoke.EFFORT,
                "modelProvider": "app_server_test",
                "thread": {"id": "synthetic-thread"},
            }
        if method == "mcpServerStatus/list":
            return {
                "data": [
                    {
                        "name": smoke.SERVER,
                        "toolsError": None,
                        "tools": {
                            smoke.TOOL: {
                                "name": smoke.TOOL,
                                "inputSchema": {"type": "object"},
                            },
                            smoke.CHECK_API_TOOL: {
                                "name": smoke.CHECK_API_TOOL,
                                "inputSchema": self.schema,
                            },
                        },
                        "serverCapabilities": {"tools": {}},
                    }
                ]
            }
        return _local_smoke_tool_result(params["tool"])


class CodexAppServerContractTests(unittest.TestCase):
    def test_live_review_forwards_names_without_putting_secrets_in_overrides(self):
        configuration = {
            "OPENAI_API_KEY": "synthetic-key",
            "OPENAI_BASE_URL": "https://example.invalid/v1",
        }
        config, _ = smoke.settings(
            Path("/synthetic/root"),
            Path("/synthetic/site"),
            configuration,
            live_review=True,
        )
        server = config["mcp_servers"][smoke.SERVER]
        self.assertEqual(
            server["env_vars"],
            ["OPENAI_API_KEY", "OPENAI_BASE_URL", *smoke.NETWORK_ENV_VARS],
        )
        self.assertEqual(server["env"], {"OPENAI_TIMEOUT_MAX_RETRIES": "0"})
        self.assertNotIn(configuration["OPENAI_API_KEY"], str(server))
        self.assertNotIn(configuration["OPENAI_BASE_URL"], str(server))

    def test_live_review_preserves_proxy_environment_without_serializing_values(self):
        configuration = {
            "OPENAI_API_KEY": "synthetic-key",
            "OPENAI_BASE_URL": "https://example.invalid/v1",
        }
        for name in smoke.NETWORK_ENV_VARS:
            with (
                self.subTest(name=name),
                patch.dict(os.environ, {name: "synthetic-network-value"}, clear=True),
            ):
                config, environment = smoke.settings(
                    Path("/synthetic/root"),
                    Path("/synthetic/site"),
                    configuration,
                    live_review=True,
                )
                self.assertEqual(environment[name], "synthetic-network-value")
                self.assertIn(name, config["mcp_servers"][smoke.SERVER]["env_vars"])
                self.assertNotIn("synthetic-network-value", str(config))

    def test_external_review_diagnostics_publish_only_known_safe_codes(self):
        for code in (
            "api_connection_failed",
            "api_timeout",
            "missing_base_url",
            "model_refusal",
        ):
            with (
                self.subTest(code=code),
                self.assertRaisesRegex(
                    smoke.SmokeFailure, "^check_api_input_" + code + "$"
                ),
            ):
                smoke.check_api_input_external_result(
                    {"structuredContent": {"passed": False, "error_code": code}}
                )
        with self.assertRaisesRegex(
            smoke.SmokeFailure, "^check_api_input_unavailable$"
        ):
            smoke.check_api_input_external_result(
                {
                    "structuredContent": {
                        "passed": False,
                        "status": "unavailable",
                        "error_code": "synthetic-secret-error-text",
                    }
                }
            )

    def test_external_review_requires_real_attempt_and_current_complete_pass(self):
        body = {
            "passed": True,
            "status": "passed",
            "stage": "complete",
            "external_review_performed": True,
            "policy_version": "2026-11-05.5",
            "input_hash": "a" * 64,
            "findings": [],
        }
        smoke.check_api_input_external_result({"structuredContent": body})
        smoke.check_api_input_external_result(
            {"content": [{"type": "text", "text": json.dumps(body)}]}
        )
        for field, value in (
            ("external_review_performed", False),
            ("passed", False),
            ("policy_version", "old"),
            ("findings", [{}]),
        ):
            with self.subTest(field=field), self.assertRaises(smoke.SmokeFailure):
                smoke.check_api_input_external_result(
                    {"structuredContent": {**body, field: value}}
                )

    def test_missing_or_blank_config_stops_before_subprocess_or_app_server(self):
        cases = (
            {},
            {"OPENAI_API_KEY": "fake", "OPENAI_BASE_URL": " "},
            {"OPENAI_API_KEY": "", "OPENAI_BASE_URL": "https://example.invalid/v1"},
        )
        for environment in cases:
            with (
                self.subTest(names=list(environment)),
                patch.dict(os.environ, environment, clear=True),
                patch.object(smoke, "execute_app_server") as app_server,
                patch.object(smoke.subprocess, "run") as process,
            ):
                with self.assertRaises(smoke.SmokeFailure):
                    smoke.run(Path("unused.whl"), live=True)
                app_server.assert_not_called()
                process.assert_not_called()

    def test_reads_current_environment_without_fallback(self):
        for value in ("one", "two"):
            environment = {
                "OPENAI_API_KEY": value,
                "OPENAI_BASE_URL": f"https://{value}.example.invalid/v1",
            }
            with patch.dict(os.environ, environment, clear=True):
                self.assertEqual(smoke.credentials(), environment)

    def test_settings_lock_model_effort_and_explicit_provider(self):
        configuration = {
            "OPENAI_API_KEY": "fake-test-key",
            "OPENAI_BASE_URL": "https://example.invalid/v1",
        }
        with patch.dict(
            os.environ,
            {"MODEL": "invalid-model", "REASONING_EFFORT": "high"},
            clear=True,
        ):
            config, environment = smoke.settings(
                Path("/synthetic/root"), Path("/synthetic/installed"), configuration
            )
        self.assertEqual(config["model"], "gpt-6-luna")
        self.assertEqual(config["model_reasoning_effort"], "medium")
        self.assertTrue(all(value is False for value in config["features"].values()))
        provider = config["model_providers"]["app_server_test"]
        self.assertEqual(provider["base_url"], configuration["OPENAI_BASE_URL"])
        self.assertEqual(provider["env_key"], "OPENAI_API_KEY")
        self.assertFalse(provider["requires_openai_auth"])
        self.assertEqual(provider["request_max_retries"], 0)
        self.assertEqual(environment["OPENAI_API_KEY"], configuration["OPENAI_API_KEY"])
        self.assertEqual(
            config["mcp_servers"][smoke.SERVER]["enabled_tools"],
            [smoke.TOOL, smoke.CHECK_API_TOOL],
        )
        self.assertNotIn(
            configuration["OPENAI_API_KEY"], "\n".join(smoke.overrides(config))
        )
        # App Server 命令行覆盖值必须是合法 TOML，并保留全部受控字段。
        parsed = tomllib.loads("\n".join(smoke.overrides(config)))
        self.assertEqual(parsed, config)

    def test_settings_uses_the_selected_installed_executable_directly(self):
        executable = Path("/synthetic/uv/tools/server/bin/dev-workflow-standards-tools")
        config, _ = smoke.settings(
            Path("/synthetic/root"),
            Path("/synthetic/site"),
            {"OPENAI_API_KEY": "fake", "OPENAI_BASE_URL": "https://example.invalid/v1"},
            server_executable=executable,
        )
        server = config["mcp_servers"][smoke.SERVER]
        self.assertEqual(server["command"], str(executable))
        self.assertEqual(server["args"], [])
        self.assertIn(smoke.CHECK_API_TOOL, server["enabled_tools"])

    def _check_api_input_schema(self):
        fields = {
            name: {"type": "string", "minLength": 1, "maxLength": smoke.API_FIELD_LIMIT}
            for name in ("purpose", "content")
        }
        return {
            "type": "object",
            "properties": {"request": {"$ref": "#/$defs/ApiInputReviewRequest"}},
            "required": ["request"],
            "$defs": {
                "ApiInputReviewRequest": {
                    "type": "object",
                    "properties": fields,
                    "required": ["purpose", "content"],
                    "additionalProperties": False,
                },
            },
        }

    def test_check_api_input_schema_requires_only_two_fields_and_no_extras(self):
        schema = self._check_api_input_schema()
        smoke.check_api_input_schema({"inputSchema": schema})
        invalid = copy.deepcopy(schema)
        invalid["$defs"]["ApiInputReviewRequest"]["required"] = ["purpose"]
        with self.assertRaisesRegex(
            smoke.SmokeFailure, "check_api_input_schema_mismatch"
        ):
            smoke.check_api_input_schema({"inputSchema": invalid})
        invalid = copy.deepcopy(schema)
        invalid["$defs"]["ApiInputReviewRequest"]["additionalProperties"] = True
        with self.assertRaisesRegex(
            smoke.SmokeFailure, "check_api_input_schema_mismatch"
        ):
            smoke.check_api_input_schema({"inputSchema": invalid})

    def test_check_api_input_result_requires_credential_block(self):
        result = {
            "isError": False,
            "structuredContent": {
                "passed": False,
                "status": "blocked_local",
                "stage": "local",
                "external_review_performed": False,
                "error_code": "sensitive_input_detected",
                "findings": [{"field": "content", "rule_id": "credential.bearer"}],
            },
        }
        smoke.check_api_input_result(result)
        for field, value in (("external_review_performed", True), ("status", "passed")):
            invalid = copy.deepcopy(result)
            invalid["structuredContent"][field] = value
            with self.subTest(field=field), self.assertRaises(smoke.SmokeFailure):
                smoke.check_api_input_result(invalid)

    def test_app_server_driver_discovers_schema_and_calls_installed_issue_tool_locally(
        self,
    ):
        schema = self._check_api_input_schema()
        installed_executable = Path(
            "/synthetic/uv/tools/server/bin/dev-workflow-standards-tools"
        )
        installed_info = {
            "path": str(installed_executable),
            "version": "0.2.0",
            "module": "/synthetic/uv/tools/server/lib/site-packages/dev_workflow_standards_tools/server.py",
        }

        clients: list[object] = []
        client_factory = partial(_LocalSmokeClient, schema=schema, instances=clients)

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(smoke, "AppServerClient", client_factory),
        ):
            result = smoke.execute_app_server(
                Path(temporary),
                Path(installed_info["module"]).parent.parent,
                {
                    "OPENAI_API_KEY": "fake",
                    "OPENAI_BASE_URL": "https://example.invalid/v1",
                },
                installed_info=installed_info,
            )
        client = clients[-1]
        calls = [
            params
            for method, params in client.requests
            if method == "mcpServer/tool/call"
        ]
        self.assertEqual(
            [call["tool"] for call in calls], [smoke.TOOL, smoke.CHECK_API_TOOL]
        )
        self.assertEqual(calls[-1]["arguments"], smoke.CHECK_API_ARGUMENTS)
        self.assertIn(
            installed_info["path"], "\n".join(client.config["config_overrides"])
        )
        server_env = "\n".join(client.config["config_overrides"])
        self.assertIn(
            'mcp_servers.dev-workflow-standards-tools.env.OPENAI_API_KEY=""', server_env
        )
        self.assertIn(
            'mcp_servers.dev-workflow-standards-tools.env.OPENAI_BASE_URL=""',
            server_env,
        )
        self.assertEqual(result["installed_version"], "0.2.0")
        self.assertEqual(result["check_api_input_schema"], "passed")
        self.assertEqual(result["check_api_input_local_call"], "passed")

    def _fake_installed_entrypoint(self, root: Path) -> tuple[Path, Path, Path]:
        binary_dir = root / "tool" / "bin"
        binary_dir.mkdir(parents=True)
        executable = binary_dir / "dev-workflow-standards-tools"
        interpreter = binary_dir / "python"
        managed_python = root / "managed-python" / "bin" / "python3.14"
        managed_python.parent.mkdir(parents=True)
        managed_python.write_text("synthetic managed interpreter\n", encoding="utf-8")
        managed_python.chmod(0o755)
        executable.write_text(
            "#!/bin/sh\n"
            f"'''exec' '{interpreter}' \"$0\" \"$@\"\n"
            "' '''\n"
            "from dev_workflow_standards_tools.server import main\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        interpreter.symlink_to(managed_python)
        module = (
            root
            / "tool"
            / "lib"
            / "python3.14"
            / "site-packages"
            / "dev_workflow_standards_tools"
            / "server.py"
        )
        module.parent.mkdir(parents=True)
        module.write_text("# synthetic installed module\n", encoding="utf-8")
        return executable, interpreter, module

    def test_installed_executable_is_resolved_to_its_versioned_uv_tool_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable, interpreter, module = self._fake_installed_entrypoint(
                Path(temporary)
            )
            with patch.object(
                smoke.subprocess,
                "run",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps({"version": "0.2.0", "server": str(module)}),
                ),
            ) as process:
                installed = smoke.inspect_installed_executable(executable)
                interpreter_is_symlink = interpreter.is_symlink()
                interpreter_target_exists = interpreter.resolve().is_file()
        self.assertEqual(installed["path"], str(executable.resolve()))
        self.assertEqual(installed["version"], "0.2.0")
        call = process.call_args
        self.assertEqual(call.args[0][0], str(interpreter))
        self.assertTrue(interpreter_is_symlink)
        self.assertTrue(interpreter_target_exists)
        self.assertEqual(call.args[0][1:3], ["-I", "-c"])
        self.assertEqual(call.kwargs["env"], {"PATH": os.defpath})

    def test_installed_version_mismatch_stops_before_app_server_startup(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable, _, module = self._fake_installed_entrypoint(Path(temporary))
            with (
                patch.dict(
                    os.environ,
                    {
                        "OPENAI_API_KEY": "fake",
                        "OPENAI_BASE_URL": "https://example.invalid/v1",
                    },
                    clear=True,
                ),
                patch.object(
                    smoke.subprocess,
                    "run",
                    return_value=SimpleNamespace(
                        returncode=0,
                        stdout=json.dumps({"version": "9.9.9", "server": str(module)}),
                    ),
                ),
                patch.object(smoke, "execute_app_server") as app_server,
                self.assertRaisesRegex(
                    smoke.SmokeFailure, "installed_package_mismatch"
                ),
            ):
                smoke.run(installed_executable=executable)
        app_server.assert_not_called()

    def test_installed_mode_uses_exact_executable_and_skips_package_install(self):
        executable = Path("/synthetic/uv/tools/server/bin/dev-workflow-standards-tools")
        installed = {
            "path": str(executable),
            "version": "0.2.0",
            "module": "/synthetic/uv/tools/server/site-packages/dev_workflow_standards_tools/server.py",
        }
        with (
            patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "fake",
                    "OPENAI_BASE_URL": "https://example.invalid/v1",
                },
                clear=True,
            ),
            patch.object(smoke, "inspect_installed_executable", return_value=installed),
            patch.object(
                smoke, "execute_app_server", return_value={"ok": True}
            ) as app_server,
            patch.object(smoke.subprocess, "run") as process,
        ):
            self.assertEqual(smoke.run(installed_executable=executable), {"ok": True})
        process.assert_not_called()
        self.assertEqual(app_server.call_args.kwargs["installed_info"], installed)
        self.assertEqual(
            app_server.call_args.args[1], Path(installed["module"]).parent.parent
        )

    def test_model_words_without_real_tool_event_cannot_pass(self):
        with self.assertRaisesRegex(smoke.SmokeFailure, "missing_actual_mcp_call"):
            smoke.check_turn(
                {
                    "status": "completed",
                    "items": [
                        {"type": "agentMessage", "text": "MCP is installed and works"}
                    ],
                }
            )

    def test_live_turn_consumes_json_notifications_and_rejects_failed_status(self):
        item = {
            "type": "mcpToolCall",
            "server": smoke.SERVER,
            "tool": smoke.TOOL,
            "arguments": smoke.ARGUMENTS,
            "status": "completed",
            "result": _local_smoke_tool_result(smoke.TOOL),
        }
        for status in ("completed", "failed", "interrupted"):
            events = [
                {"method": "item/completed", "params": {"item": item}},
                {"method": "turn/completed", "params": {"turn": {"status": status}}},
            ]
            client = SimpleNamespace(
                request=Mock(return_value={"turn": {"id": "synthetic-turn"}}),
                next_turn_notification=Mock(side_effect=events),
            )
            with self.subTest(status=status):
                if status == "completed":
                    self.assertEqual(
                        smoke._read_live_turn(client, "synthetic-thread", "probe"), 1
                    )
                else:
                    with self.assertRaisesRegex(
                        smoke.SmokeFailure, "model_turn_failed"
                    ):
                        smoke._read_live_turn(client, "synthetic-thread", "probe")
            client.next_turn_notification.assert_called_with(
                "synthetic-thread", "synthetic-turn"
            )
            params = client.request.call_args.args[1]
            self.assertEqual(params["model"], "gpt-6-luna")
            self.assertEqual(params["effort"], "medium")

    def test_real_event_result_is_checked_for_tool_arguments_and_output(self):
        item = {
            "type": "mcpToolCall",
            "server": smoke.SERVER,
            "tool": smoke.TOOL,
            "arguments": smoke.ARGUMENTS,
            "status": "completed",
            "result": {
                "structuredContent": {
                    "ok": True,
                    "questions": smoke.ARGUMENTS["custom_questions"],
                    "template": smoke.ARGUMENTS["custom_template"],
                }
            },
        }
        turn = {"status": "completed", "items": [item]}
        self.assertEqual(smoke.check_turn(turn), 1)
        for name, value in (
            ("status", "failed"),
            ("tool", "other"),
            ("arguments", {}),
            ("result", {}),
        ):
            invalid = copy.deepcopy(turn)
            invalid["items"][0][name] = value
            with self.subTest(field=name), self.assertRaises(smoke.SmokeFailure):
                smoke.check_turn(invalid)
        turn["items"].append({"type": "commandExecution"})
        with self.assertRaisesRegex(smoke.SmokeFailure, "unexpected_agent_action"):
            smoke.check_turn(turn)

    def test_app_server_model_readback_mismatch_prevents_any_model_or_tool_request(
        self,
    ):
        clients = []
        factory = partial(_LocalSmokeClient, schema={}, instances=clients)
        original = _LocalSmokeClient.request

        def mismatched(client, method, params):
            if method != "thread/start":
                raise AssertionError("must stop before discovery/tool/model request")
            result = original(client, method, params)
            result["model"] = "unexpected-model"
            return result

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(smoke, "AppServerClient", factory),
            patch.object(_LocalSmokeClient, "request", mismatched),
            self.assertRaisesRegex(smoke.SmokeFailure, "model_or_effort_mismatch"),
        ):
            smoke.execute_app_server(
                Path(temporary),
                Path(temporary) / "site",
                {
                    "OPENAI_API_KEY": "fake",
                    "OPENAI_BASE_URL": "https://example.invalid/v1",
                },
                live=True,
            )
        self.assertEqual(clients[0].requests[0][1]["model"], "gpt-6-luna")
        self.assertEqual(
            clients[0].requests[0][1]["config"]["model_reasoning_effort"], "medium"
        )
        self.assertTrue(clients[0].closed)

    def test_cli_is_opt_in_and_never_echoes_raw_app_server_errors(self):
        with (
            patch.object(
                smoke,
                "run",
                side_effect=RuntimeError("synthetic-private-key-and-endpoint"),
            ),
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            self.assertEqual(smoke.main(["--wheel", "test.whl"]), 1)
            self.assertEqual(
                json.loads(output.getvalue()),
                {"ok": False, "error_code": "test_setup_failed"},
            )
        with (
            patch.object(smoke, "run", return_value={"ok": True}) as run,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            smoke.main(["--wheel", "test.whl"])
            self.assertFalse(run.call_args.kwargs["live"])

    def test_sdk_dependency_is_removed(self):
        project = tomllib.loads((ROOT / "mcp-server/pyproject.toml").read_text())
        self.assertNotIn("codex-test", project.get("dependency-groups", {}))
        lock = tomllib.loads((ROOT / "mcp-server/uv.lock").read_text())
        self.assertFalse(
            any(item["name"].startswith("openai-codex") for item in lock["package"])
        )
        self.assertFalse(
            any("codex" in item for item in project["project"]["dependencies"])
        )
        for path in (ROOT / "mcp-server/dev_workflow_standards_tools").rglob("*.py"):
            self.assertNotIn("openai_codex", path.read_text())
            self.assertNotIn("codex_app_server_client", path.read_text())


class CodexAppServerDiscoveredSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_helper_accepts_the_real_mcp_discovery_schema(self):
        async with Client(mcp, raise_exceptions=True) as client:
            listed = await client.list_tools()
        tool = next(item for item in listed.tools if item.name == smoke.CHECK_API_TOOL)
        actual_tool = tool.model_dump(mode="json", by_alias=True)
        smoke.check_api_input_schema(actual_tool)


if __name__ == "__main__":
    unittest.main()
