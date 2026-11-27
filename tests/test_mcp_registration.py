from __future__ import annotations

import asyncio
import inspect
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from codex_session_fixtures import ROOT, tool_json
from dev_agent_toolkit_tools.infrastructure.openai_client import (
    GPT_LUNA_MODEL,
    GPT_SOL_MODEL,
)
from dev_agent_toolkit_tools.server import mcp as complete_server
from dev_agent_toolkit_tools.services import codex_session_facts as service
from dev_agent_toolkit_tools.services import local_mcp, validation, workflows
from dev_agent_toolkit_tools.services.codex_session_facts import (
    CodexSessionSource,
)
from mcp import Client, StdioServerParameters
from pydantic import create_model


class MCPRegistrationTests(IsolatedAsyncioTestCase):
    A = "00000000-0000-4000-8000-000000000005"

    async def test_local_mcp_bridge_discovers_and_calls_fresh_stdio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / local_mcp.UV_TOOL_NAME
            executable = prefix / "bin" / local_mcp.UV_TOOL_NAME
            executable.parent.mkdir(parents=True)
            (prefix / "uv-receipt.toml").touch()
            executable.write_text(
                "#!/bin/bash\n"
                f"cd -- {shlex.quote(str(ROOT / 'mcp-server'))} || exit 1\n"
                f"exec {shlex.quote(sys.executable)} -m dev_agent_toolkit_tools.server\n"
            )
            executable.chmod(0o700)
            with patch.object(local_mcp, "sys", SimpleNamespace(prefix=str(prefix))):
                listing = await local_mcp.call_updated_local_mcp()
                self.assertEqual(listing["status"], "listed")
                self.assertTrue(
                    {
                        "list_repository_worktrees",
                        "get_codex_session_summary_guidance",
                        "get_mcp_server_build_info",
                    }
                    <= {tool["name"] for tool in listing["tools"]}
                )
                response = await local_mcp.call_updated_local_mcp(
                    "get_codex_session_summary_guidance",
                    {"custom_questions": ["示例问题？"]},
                )
                self.assertEqual(response["status"], "called")
                self.assertEqual(
                    json.loads(response["result"]["content"][0]["text"])["questions"],
                    ["示例问题？"],
                )
                response = await local_mcp.call_updated_local_mcp(
                    "create_repository_branch"
                )
                self.assertEqual(
                    response, {"ok": False, "status": "tool_not_available"}
                )

    async def test_discovers_environment_names_in_both_stdio_protocols(self) -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "dev_agent_toolkit_tools.server"],
            cwd=ROOT / "mcp-server",
        )
        for mode in ("auto", "legacy"):
            with self.subTest(mode=mode):
                async with asyncio.timeout(10), Client(params, mode=mode) as client:
                    catalog = {
                        tool.name: tool for tool in (await client.list_tools()).tools
                    }
                    discovery = catalog["get_mcp_environment"]
                    self.assertTrue(discovery.annotations.read_only_hint)
                    reply = await client.call_tool("get_mcp_environment")
                    self.assertFalse(reply.is_error)
                    declaration = reply.structured_content
                    self.assertEqual(set(declaration), {"names"})
                    self.assertEqual(
                        set(declaration["names"]),
                        {
                            "OPENAI_API_KEY",
                            "OPENAI_BASE_URL",
                            "OPENAI_TIMEOUT_MAX_RETRIES",
                            "HTTP_PROXY",
                            "HTTPS_PROXY",
                            "ALL_PROXY",
                            "NO_PROXY",
                            "http_proxy",
                            "https_proxy",
                            "all_proxy",
                            "no_proxy",
                        },
                    )

    async def test_issue_pr_metadata_over_stdio_initialize_and_tools_list(self) -> None:
        from dev_agent_toolkit_tools.services.ai_workflow import (
            ContentGenerationRequest,
        )
        from dev_agent_toolkit_tools.tools._descriptions import (
            CLI_FALLBACK_DESCRIPTION,
            OPENAI_NETWORK_DESCRIPTION,
        )

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "dev_agent_toolkit_tools.server"],
            cwd=ROOT / "mcp-server",
            env={},
        )
        async with asyncio.timeout(20), Client(params) as client:
            instructions = client.instructions
            self.assertEqual(client.server_info.name, "dev_agent_toolkit")
            self.assertIn(CLI_FALLBACK_DESCRIPTION, instructions)
            self.assertEqual(instructions.count(OPENAI_NETWORK_DESCRIPTION), 1)
            for phrase in (
                "Pi Code Agent",
                "searchTools",
                "describeNamespace",
                "不要求调用",
                "不提供 read_thread",
                "timeout",
            ):
                self.assertIn(phrase, instructions)
            for phrase in (
                "Issue",
                "PR",
                "最小充分",
                "所有待交付的 git commit patch",
                "已内置默认布局",
                "output_format",
                "默认中文",
                "language_override",
                "needs_revision",
                "两次",
            ):
                self.assertIn(phrase, instructions)
            for phrase in (
                "httpx2.AsyncClient(trust_env=True)",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "NO_PROXY",
                "重新加载",
            ):
                self.assertIn(phrase, instructions)
            for phrase in (
                "OPENAI_TIMEOUT_SECONDS=180",
                "OPENAI_TIMEOUT_MAX_RETRIES",
                "最多6次",
                "api_timeout",
            ):
                self.assertIn(phrase, instructions)
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            self.assertIn("get_mcp_server_build_info", instructions)
            build_info = tools["get_mcp_server_build_info"]
            self.assertEqual(build_info.input_schema.get("properties", {}), {})
            self.assertTrue(build_info.annotations.read_only_hint)
            self.assertFalse(build_info.annotations.open_world_hint)
            running_build = tool_json(await client.call_tool(build_info.name, {}))
            self.assertEqual(set(running_build), {"server_version", "git_commit"})
            self.assertEqual(
                running_build["server_version"], client.server_info.version
            )
            self.assertIn("call_updated_local_mcp", instructions)
            bridge = tools["call_updated_local_mcp"]
            self.assert_described_properties(bridge.input_schema, bridge.name)
            self.assertEqual(
                set(bridge.input_schema["properties"]), {"tool_name", "arguments"}
            )
            self.assertTrue(bridge.annotations.read_only_hint)
            self.assertFalse(bridge.annotations.open_world_hint)
            self.assertNotIn("dev-agent-toolkit/local-stdio", bridge.meta or {})
            self.assertIn("title_file", instructions)
            self.assertIn("body_file", instructions)
            for name in ("create_github_issue", "create_github_pull_request"):
                tool = tools[name]
                schema = tool.input_schema
                self.assertNotIn("title", schema["properties"])
                self.assertNotIn("body", schema["properties"])
                for field in ("title_file", "body_file"):
                    self.assertIn(field, schema["required"])
                    self.assertEqual(schema["properties"][field]["type"], "string")
                    self.assertIn(
                        "绝对路径", schema["properties"][field]["description"]
                    )
                self.assertIn("--title", tool.description)
                self.assertIn("--body-file", tool.description)
                self.assertFalse(tool.annotations.read_only_hint)
                self.assertTrue(tool.annotations.open_world_hint)
            self.assertNotIn("gitlab", instructions.lower())
            self.assertNotIn("glab", instructions.lower())
            for name in (
                "audit_gitlab_repository_state",
                "list_gitlab_issue_labels",
                "create_gitlab_issue",
                "push_gitlab_issue_branch_to_origin",
                "create_gitlab_merge_request",
                "merge_gitlab_merge_request",
                "audit_issue_mr_policy",
                "push_gitlab_fork_main_fast_forward",
                "cleanup_merged_mr_local_branch",
            ):
                self.assertNotIn(name, tools)
        self.assertIn(f"Decisions 固定使用 {GPT_LUNA_MODEL}", instructions)
        self.assertIn(f"Responses 固定使用 {GPT_SOL_MODEL}", instructions)
        for name, models in {
            "check_branch_names": (GPT_LUNA_MODEL,),
            "check_commit_message": (GPT_LUNA_MODEL,),
            "audit_issue_pr_policy": (GPT_LUNA_MODEL,),
            "decide_codex_session_action": (GPT_LUNA_MODEL,),
            "generate_skill_content": (GPT_SOL_MODEL,),
            "check_api_input": (GPT_LUNA_MODEL,),
            "start_issue_pr_draft": (GPT_SOL_MODEL,),
            "revise_issue_pr_draft": (GPT_SOL_MODEL,),
            "generate_git_commit_message": (GPT_SOL_MODEL,),
            "web_search": (GPT_LUNA_MODEL, GPT_SOL_MODEL),
        }.items():
            for phrase in (
                *models,
                "OPENAI_API_KEY",
                "OPENAI_BASE_URL",
                "OpenAI 请求配置",
                "api_timeout",
            ):
                self.assertIn(phrase, tools[name].description, name)
            self.assertNotIn(OPENAI_NETWORK_DESCRIPTION, tools[name].description, name)
            self.assertNotIn("proxy", tools[name].input_schema.get("properties", {}))
        for name, detail in (
            ("revise_issue_pr_draft", "draft_revision_conflict"),
            (
                "generate_git_commit_message",
                "staged_sha256",
            ),
            ("web_search", "search_evidence_missing"),
        ):
            self.assertIn(detail, tools[name].description, name)
            self.assertNotIn(detail, instructions)
        for name, tool_metadata in tools.items():
            description = tool_metadata.description
            self.assertNotIn("需要明确用户授权和 Codex writes approval", description)
            self.assertNotIn("需要用户授权与 Codex writes approval", description)
            if not tool_metadata.annotations.read_only_hint:
                self.assertIn("Pi", description, name)
        for name in (
            "order_codex_session_sources",
            "prepare_codex_session_memory",
            "generate_skill_content",
        ):
            self.assertIn("不接受或伪造 Pi", tools[name].description)
            self.assertIn(
                "不接受 Pi 原生会话",
                json.dumps(tools[name].input_schema, ensure_ascii=False),
            )
        for name in (
            "start_issue_pr_draft",
            "revise_issue_pr_draft",
            "get_issue_pr_draft",
            "close_issue_pr_draft",
        ):
            self.assertIn("process_memory", tools[name].description)
            self.assertIn("1800", tools[name].description)
            self.assert_described_properties(tools[name].input_schema, name)
        for name in ("start_issue_pr_draft", "revise_issue_pr_draft"):
            self.assertIn("无需传通用模板", tools[name].description)
        commit_tool = tools["generate_git_commit_message"]
        self.assertIn("本次选定提交", commit_tool.description)
        self.assertIn("check_commit_message", commit_tool.description)
        self.assertIn("OPENAI_BASE_URL", commit_tool.description)
        self.assertIn("cached diff", commit_tool.description)
        self.assertIn("单行中文标题与按需正文", commit_tool.description)
        self.assertIn("无需传通用模板", commit_tool.description)
        self.assertEqual(set(commit_tool.input_schema["properties"]), {"repo_path"})
        self.assertEqual(commit_tool.input_schema["required"], ["repo_path"])
        self.assertFalse(commit_tool.input_schema["additionalProperties"])
        self.assertTrue(commit_tool.annotations.read_only_hint)
        self.assertTrue(commit_tool.annotations.open_world_hint)
        self.assert_described_properties(commit_tool.input_schema, commit_tool.name)
        tool = tools["generate_skill_content"]
        for phrase in (
            "前后行为",
            "复现",
            "实际验证",
            "user_provided",
            "默认中文",
            "adoptable",
            "quality_review",
            "不会读写",
            "OPENAI_BASE_URL",
            "所有待交付的 git commit patch",
            "merge-base",
            "纯需求/缺陷 Issue 尚无对应提交",
            "无需传通用模板",
            "编号已核实的同仓库 Issue 默认生成真实关闭引用",
        ):
            self.assertIn(phrase, tool.description)
        schema_text = json.dumps(tool.input_schema, ensure_ascii=False)
        for phrase in (
            "language_override",
            "instruction_ref",
            "language",
            "user_provided",
            "实际/期望/影响",
            "已完成diff",
            "所有待交付commit patch",
            "完整提交列表",
            "最后一次提交",
            "默认中文",
            "已内置布局",
            "优先于默认布局",
        ):
            self.assertIn(phrase, schema_text)
        for marker, kind in (("Issue示例：", "issue"), ("PR示例：", "pr")):
            example, _ = json.JSONDecoder().raw_decode(
                tool.description.split(marker, 1)[1]
            )
            self.assertEqual(
                ContentGenerationRequest.model_validate(example["request"]).kind, kind
            )
        self.assertTrue(tool.annotations.read_only_hint)
        self.assertTrue(tool.annotations.open_world_hint)
        self.assertFalse(tool.annotations.idempotent_hint)

    def assert_described_properties(self, schema: dict, tool_name: str) -> None:
        for property_schema in schema.get("properties", {}).values():
            self.assertTrue(
                property_schema.get("description"), (tool_name, property_schema)
            )
        for value in schema.values():
            if isinstance(value, dict):
                self.assert_described_properties(value, tool_name)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self.assert_described_properties(item, tool_name)

    async def test_all_tools_registered_with_described_schemas(self) -> None:
        self.assertIn("本地开发工作流 MCP 服务", complete_server.description)
        tools = await complete_server.list_tools()
        self.assertEqual(len(tools), 50)
        by_name = {tool.name: tool for tool in tools}
        self.assertEqual(len(by_name), len(tools))
        self.assertIn("get_mcp_environment", by_name)
        self.assertNotIn("decide_skill_workflow", by_name)
        for tool in tools:
            self.assertTrue(tool.description, tool.name)

            self.assert_described_properties(tool.input_schema, tool.name)
        deterministic_names = {
            "get_codex_session_summary_guidance",
            "order_codex_session_sources",
            "prepare_codex_session_memory",
            "serena_memory_tail_read",
            "serena_memory_write_check",
        }
        ai_names = {
            "decide_codex_session_action",
            "generate_skill_content",
            "check_api_input",
        }
        names = deterministic_names | ai_names
        self.assertTrue(names.issubset(by_name))
        for name in deterministic_names:
            tool = by_name[name]
            self.assertTrue(tool.annotations.read_only_hint)
            self.assertFalse(tool.annotations.destructive_hint)
            self.assertTrue(tool.annotations.idempotent_hint)
            self.assertFalse(tool.annotations.open_world_hint)
            self.assertEqual(tool.input_schema["type"], "object")
        self.assertIn(
            "custom_questions",
            by_name["get_codex_session_summary_guidance"].input_schema["properties"],
        )
        self.assertIn(
            "sources", by_name["order_codex_session_sources"].input_schema["properties"]
        )
        self.assertIn(
            "source", by_name["prepare_codex_session_memory"].input_schema["properties"]
        )
        for name in ai_names:
            tool = by_name[name]
            self.assertTrue(tool.annotations.read_only_hint)
            self.assertFalse(tool.annotations.destructive_hint)
            self.assertFalse(tool.annotations.idempotent_hint)
            self.assertTrue(tool.annotations.open_world_hint)

    async def test_network_git_annotations_and_discovery_examples_are_explicit(
        self,
    ) -> None:
        tools = {tool.name: tool for tool in await complete_server.list_tools()}
        for name in ("pull_origin_branch_fast_forward", "fetch_upstream_branch"):
            self.assertTrue(tools[name].annotations.open_world_hint)

        self.assertTrue(tools["audit_worktree_base_sync"].annotations.read_only_hint)
        self.assertTrue(tools["audit_worktree_base_sync"].annotations.open_world_hint)
        for name in (
            "fetch_repository_branch",
            "merge_repository_branch",
            "rebase_repository_branch",
        ):
            self.assertFalse(tools[name].annotations.read_only_hint)
            self.assertTrue(tools[name].annotations.open_world_hint)

        audit_schema = tools["audit_worktree_base_sync"].input_schema
        self.assertEqual(
            set(audit_schema["properties"]), {"repo_path", "base_ref", "remote"}
        )
        self.assertIn("null", str(audit_schema["properties"]["remote"]))
        fetch_schema = tools["fetch_repository_branch"].input_schema
        self.assertEqual(
            set(fetch_schema["properties"]), {"repo_path", "remote", "branch_name"}
        )
        merge_schema = tools["merge_repository_branch"].input_schema
        self.assertTrue(
            {"expected_head_oid", "expected_base_oid"}.issubset(
                merge_schema["required"]
            )
        )
        rebase_schema = tools["rebase_repository_branch"].input_schema
        self.assertTrue(
            {
                "expected_head_oid",
                "expected_base_oid",
                "old_base_oid",
                "remote",
            }.issubset(rebase_schema["properties"])
        )
        for name, phrases in {
            "audit_worktree_base_sync": (
                "publication_status=unknown",
                "不会 fetch",
                "ahead_by/behind_by",
            ),
            "fetch_repository_branch": (
                "FETCH_HEAD",
                "compare-and-swap",
                "不调用 OpenAI",
            ),
            "merge_repository_branch": (
                "expected_head_oid",
                "--no-overwrite-ignore",
                "普通 merge commit",
            ),
            "rebase_repository_branch": ("live 查询", "禁止 rebase", "old_base_oid"),
        }.items():
            for phrase in phrases:
                self.assertIn(phrase, tools[name].description, (name, phrase))

        branch_tool = tools["create_repository_branch"]
        self.assertFalse(branch_tool.annotations.read_only_hint)
        self.assertFalse(branch_tool.annotations.destructive_hint)
        self.assertFalse(branch_tool.annotations.idempotent_hint)
        self.assertFalse(branch_tool.annotations.open_world_hint)
        self.assertIn("expected_head_oid", branch_tool.input_schema["properties"])
        self.assertIn(
            "null", str(branch_tool.input_schema["properties"]["expected_head_oid"])
        )
        self.assertTrue(
            branch_tool.input_schema["properties"]["expected_head_oid"].get(
                "description"
            )
        )
        self.assertIn("OID是唯一并发条件", branch_tool.description)

        descriptions = {
            "copy_untracked_files_to_worktree": ("结构示例：",),
            "create_github_issue": ("示例：",),
            "cleanup_merged_pr_local_branch": ("示例：",),
            "prepare_codex_session_memory": ("示例：",),
        }
        for name, markers in descriptions.items():
            description = tools[name].description
            marker = next(marker for marker in markers if marker in description)
            example_text = description.split(marker, 1)[1]
            example, _ = json.JSONDecoder().raw_decode(example_text.lstrip())
            self.assertIsInstance(example, dict)

        copy_example, _ = json.JSONDecoder().raw_decode(
            tools["copy_untracked_files_to_worktree"]
            .description.split("结构示例：", 1)[1]
            .lstrip()
        )
        self.assertEqual(len(copy_example["manifest"][0]["sha256"]), 64)
        self.assertEqual(set(copy_example["manifest"][0]), {"path", "sha256", "size"})
        prepare_example, _ = json.JSONDecoder().raw_decode(
            tools["prepare_codex_session_memory"]
            .description.split("示例：", 1)[1]
            .lstrip()
        )
        CodexSessionSource.model_validate(prepare_example["source"])
        self.assertEqual(
            set(prepare_example), {"repo_path", "source", "summary", "evidence_refs"}
        )

        example_services = {
            "copy_untracked_files_to_worktree": workflows.copy_untracked_files_to_worktree,
            "create_github_issue": workflows.create_github_issue,
            "create_github_pull_request": workflows.create_github_pull_request,
            "cleanup_merged_pr_local_branch": validation.cleanup_merged_pr_local_branch,
            "prepare_codex_session_memory": service.prepare_codex_session_memory,
        }
        for name, target in example_services.items():
            marker = (
                "结构示例：" if name == "copy_untracked_files_to_worktree" else "示例："
            )
            text = tools[name].description.split(marker, 1)[1].lstrip()
            example, _ = json.JSONDecoder().raw_decode(text)
            signature = inspect.signature(target)
            hints = get_type_hints(target)
            fields = {
                param_name: (
                    hints[param_name],
                    ...
                    if parameter.default is inspect.Parameter.empty
                    else parameter.default,
                )
                for param_name, parameter in signature.parameters.items()
            }
            input_model = create_model(f"{target.__name__}Input", **fields)
            input_model.model_validate(example)

    async def test_create_repository_branch_via_mcp_call_tool(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mcp branch tool 日本語 ") as temp:
            repo = Path(temp) / "repo with spaces"
            repo.mkdir()
            (
                await asyncio.to_thread(
                    subprocess.run, ["git", "init", "-q"], cwd=repo, check=True
                )
            )
            (
                await asyncio.to_thread(
                    subprocess.run,
                    ["git", "config", "user.name", "Synthetic"],
                    cwd=repo,
                    check=True,
                )
            )
            (
                await asyncio.to_thread(
                    subprocess.run,
                    ["git", "config", "user.email", "fixture@example.invalid"],
                    cwd=repo,
                    check=True,
                )
            )
            (repo / "tracked").write_bytes(b"baseline\n")
            (
                await asyncio.to_thread(
                    subprocess.run, ["git", "add", "tracked"], cwd=repo, check=True
                )
            )
            (
                await asyncio.to_thread(
                    subprocess.run,
                    ["git", "commit", "-qm", "baseline"],
                    cwd=repo,
                    check=True,
                )
            )
            head_oid = (
                await asyncio.to_thread(
                    subprocess.run,
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            ).stdout.strip()
            raw = await complete_server.call_tool(
                "create_repository_branch",
                {
                    "repo_path": str(repo),
                    "branch_name": "feat/mcp-call",
                    "expected_head_oid": head_oid,
                },
            )
            self.assertFalse(raw.is_error)
            data = raw.structured_content or json.loads(raw.content[0].text)
            self.assertTrue(data["ok"], data)
            self.assertTrue(data["created"])
            self.assertEqual(data["start_head_oid"], head_oid)

    async def test_real_tool_calls_return_expected_guidance_order_and_memory_payload(
        self,
    ) -> None:
        guidance_result = await complete_server.call_tool(
            "get_codex_session_summary_guidance", {}
        )
        guidance = tool_json(guidance_result)
        self.assertEqual(guidance["ok"], True)
        self.assertEqual(len(guidance["questions"]), 7)

        source_input = {
            "source_link": f"codex://threads/{self.A}",
            "created_at": "2026-01-01T00:00:00Z",
            "title": "测试会话",
        }
        order_result = await complete_server.call_tool(
            "order_codex_session_sources", {"sources": [source_input]}
        )
        ordered = tool_json(order_result)
        self.assertEqual(ordered["deduplicated_count"], 1)
        self.assertTrue(ordered["ready"])

        with patch.object(
            service, "_validated_repo_path", return_value=("/tmp/fixture", None)
        ):
            prepare_result = await complete_server.call_tool(
                "prepare_codex_session_memory",
                {
                    "repo_path": "/tmp/fixture",
                    "source": source_input,
                    "summary": "## User format\nRaw summary.",
                    "evidence_refs": ["turn:2"],
                },
            )
        prepared = tool_json(prepare_result)
        self.assertEqual(prepared["status"], "prepared")
        self.assertTrue(
            prepared["payload"]["content"].endswith("## User format\nRaw summary.")
        )


if __name__ == "__main__":
    unittest.main()
