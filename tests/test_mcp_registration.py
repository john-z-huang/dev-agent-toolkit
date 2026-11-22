from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import get_type_hints
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from codex_session_fixtures import ROOT, tool_json
from dev_workflow_standards_tools.server import mcp as complete_server
from dev_workflow_standards_tools.services import codex_session_facts as service
from dev_workflow_standards_tools.services import validation, workflows
from dev_workflow_standards_tools.services.codex_session_facts import (
    CodexSessionSource,
)
from mcp import Client, StdioServerParameters
from pydantic import create_model


class MCPRegistrationTests(IsolatedAsyncioTestCase):
    A = "00000000-0000-4000-8000-000000000005"

    async def test_issue_pr_metadata_over_stdio_initialize_and_tools_list(self) -> None:
        from dev_workflow_standards_tools.services.ai_workflow import (
            ContentGenerationRequest,
        )
        from dev_workflow_standards_tools.tools._descriptions import (
            CLI_FALLBACK_DESCRIPTION,
        )

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "dev_workflow_standards_tools.server"],
            cwd=ROOT / "mcp-server",
            env={},
        )
        async with asyncio.timeout(20), Client(params) as client:
            self.assertEqual(client.server_info.name, "dev-workflow-standards-tools")
            self.assertIn(CLI_FALLBACK_DESCRIPTION, client.instructions)
            for phrase in (
                "Pi Code Agent",
                "searchTools",
                "describeNamespace",
                "不要求调用",
                "不提供 read_thread",
                "timeout",
            ):
                self.assertIn(phrase, client.instructions)
            for phrase in (
                "Issue",
                "PR",
                "最小充分",
                "所有待交付的 git commit patch",
                "不仅是最后一个 commit patch",
                "默认中文",
                "language_override",
                "needs_revision",
                "两次",
            ):
                self.assertIn(phrase, client.instructions)
            for phrase in (
                "httpx2.AsyncClient(trust_env=True)",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "NO_PROXY",
                "重新加载",
            ):
                self.assertIn(phrase, client.instructions)
            for phrase in (
                "OPENAI_TIMEOUT_SECONDS=180",
                "OPENAI_TIMEOUT_MAX_RETRIES",
                "最多6次",
                "api_timeout",
            ):
                self.assertIn(phrase, client.instructions)
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            self.assertIn("host/group[/subgroup]/project", client.instructions)
            self.assertIn("GitLab", client.instructions)
            self.assertIn("GitHub→GitLab 仓库迁移", client.instructions)
            self.assertIn("git push --mirror", client.instructions)
            self.assertIn("不得修改源 checkout 的 Git 配置", client.instructions)
            self.assertNotIn("GitLab 切到 origin", client.instructions)
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
                metadata = tools[name]
                self.assertIn("glab", metadata.description)
                self.assertIn("不调用 OpenAI", metadata.description)
                self.assert_described_properties(metadata.input_schema, name)
                self.assertTrue(metadata.annotations.open_world_hint)
                self.assertTrue(
                    {"repo_path", "repo"}.issubset(metadata.input_schema["required"])
                )
                self.assertNotIn("endpoint", metadata.input_schema["properties"])
            response = await client.call_tool(
                "audit_issue_mr_policy",
                {
                    "repo_path": "/workspace/synthetic",
                    "repo": "invalid",
                    "mr_number": 7,
                },
            )
            self.assertFalse(tool_json(response)["passed"])
        for name in (
            "check_branch_names",
            "check_commit_message",
            "audit_issue_pr_policy",
            "decide_codex_session_action",
            "generate_skill_content",
        ):
            for phrase in (
                "httpx2.AsyncClient(trust_env=True)",
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "NO_PROXY",
            ):
                self.assertIn(phrase, tools[name].description, name)
            self.assertNotIn("proxy", tools[name].input_schema.get("properties", {}))
            for phrase in (
                "OPENAI_TIMEOUT_MAX_RETRIES",
                "180",
                "invalid_timeout_max_retries",
                "SDK内部重试关闭",
            ):
                self.assertIn(phrase, tools[name].description, name)
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
        commit_tool = tools["generate_git_commit_message"]
        self.assertIn("本次选定提交", commit_tool.description)
        self.assertIn("check_commit_message", commit_tool.description)
        self.assertIn("OPENAI_BASE_URL", commit_tool.description)
        self.assertIn("cached diff", commit_tool.description)
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
        self.assertEqual(len(tools), 56)
        by_name = {tool.name: tool for tool in tools}
        self.assertEqual(len(by_name), 56)
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
        issue_example, _ = json.JSONDecoder().raw_decode(
            tools["create_github_issue"].description.split("示例：", 1)[1].lstrip()
        )
        self.assertEqual(
            set(issue_example), {"repo_path", "repo", "title", "body", "labels"}
        )
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
