from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from ai_workflow_fixtures import ContentGenerationTestCase
from dev_agent_toolkit_tools.infrastructure import openai_client
from dev_agent_toolkit_tools.server import mcp
from dev_agent_toolkit_tools.services import ai_workflow
from dev_agent_toolkit_tools.services.commit_content import generate_from_staged_diff
from dev_agent_toolkit_tools.services.staged_commit import (
    commit_snapshot,
    read_staged_diff,
)
from mcp.server.mcpserver.exceptions import ToolError


class CommitContentTests(ContentGenerationTestCase):
    def repository(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        self.git(root, "init", "--quiet")
        return root

    def git(self, root, *arguments):
        subprocess.run(["git", *arguments], cwd=root, capture_output=True, check=True)

    def staged_candidate(self, *refs):
        return self._completed(
            ai_workflow.GeneratedContent(
                title="feat: 添加暂存文件",
                content="",
                used_evidence_refs=list(refs),
                missing_facts=[],
                review_notes=[],
            )
        )

    def staged_repository(self):
        root = self.repository()
        (root / "staged.txt").write_text("staged-marker\n", encoding="utf-8")
        self.git(root, "add", "--", "staged.txt")
        return root

    async def test_staged_generation_sends_only_index(self):
        root = self.repository()
        tracked = root / "staged file.txt"
        tracked.write_text("staged-marker\n", encoding="utf-8")
        self.git(root, "add", "--", tracked.name)
        tracked.write_text("unstaged-marker\n", encoding="utf-8")
        (root / "untracked.txt").write_text("untracked-marker\n", encoding="utf-8")

        with patch.object(
            openai_client,
            "parse_response",
            new=AsyncMock(return_value=self.staged_candidate("S1")),
        ) as parse:
            reply = await mcp.call_tool(
                "generate_git_commit_message",
                {"repo_path": str(root)},
            )

        self.assertFalse(reply.is_error)
        result = reply.structured_content
        self.assertEqual(json.loads(reply.content[0].text), result)
        parse.assert_awaited_once()
        payload = parse.call_args.kwargs["input"]
        self.assertIn("staged-marker", payload)
        self.assertNotIn("unstaged-marker", payload)
        self.assertNotIn("untracked-marker", payload)
        self.assertEqual(result["staged_paths"], [tracked.name])
        self.assertRegex(result["staged_sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(result["adoptable"])
        self.assertEqual(result["message"], "feat: 添加暂存文件")
        self.assertNotIn("candidate", result)
        self.assertEqual(tracked.read_text(encoding="utf-8"), "unstaged-marker\n")

    async def test_staged_generation_rejects_candidate_if_index_changes(self):
        root = self.repository()
        tracked = root / "staged.txt"
        tracked.write_text("before\n", encoding="utf-8")
        self.git(root, "add", "--", tracked.name)

        async def change_index(**_kwargs):
            tracked.write_text("after\n", encoding="utf-8")
            self.git(root, "add", "--", tracked.name)
            return self.staged_candidate("S1")

        with patch.object(openai_client, "parse_response", side_effect=change_index):
            result = await generate_from_staged_diff(str(root))
        self.assertEqual(result["error_code"], "staged_diff_changed")
        self.assertNotIn("message", result)

    async def test_staged_generation_skips_model_for_empty_index(self):
        root = self.repository()
        with patch.object(openai_client, "parse_response") as parse:
            result = await generate_from_staged_diff(str(root))
        self.assertEqual(result["error_code"], "no_staged_changes")
        parse.assert_not_called()

    async def test_commit_rechecks_snapshot_even_when_staged_paths_match(self):
        root = self.staged_repository()
        with patch.object(
            openai_client, "parse_response", return_value=self.staged_candidate("S1")
        ):
            draft = await generate_from_staged_diff(str(root))
        self.assertTrue(draft["adoptable"])
        arguments = {
            "repo_path": str(root),
            "message": draft["message"],
            "expected_paths": draft["staged_paths"],
            "expected_snapshot": draft["snapshot"],
        }
        (root / "staged.txt").write_text("changed-after-review\n", encoding="utf-8")
        self.git(root, "add", "--", "staged.txt")
        reply = await mcp.call_tool("commit_repository_changes", arguments)
        result = reply.structured_content or json.loads(reply.content[0].text)
        self.assertEqual(result, {"ok": False, "error_code": "commit_snapshot_changed"})
        self.assertFalse(
            (root / ".git" / "refs" / "heads" / draft["snapshot"]["branch"]).exists()
        )

        self.git(root, "config", "user.name", "Fixture")
        self.git(root, "config", "user.email", "fixture@example.invalid")
        self.git(root, "config", "commit.gpgsign", "false")
        self.git(root, "config", "core.hooksPath", "/dev/null")
        current = await read_staged_diff(str(root))
        arguments["expected_snapshot"] = commit_snapshot(
            str(root), current.sha256
        ).model_dump()
        reply = await mcp.call_tool("commit_repository_changes", arguments)
        result = reply.structured_content or json.loads(reply.content[0].text)
        self.assertTrue(result["committed"], result)
        self.assertEqual(result["message"], draft["message"])
        self.assertEqual(result["paths"], ["staged.txt"])

    async def test_commit_tool_rejects_removed_arguments(self):
        with (
            patch.object(openai_client, "parse_response") as parse,
            self.assertRaisesRegex(ToolError, "Invalid tool arguments"),
        ):
            await mcp.call_tool(
                "generate_git_commit_message",
                {
                    "repo_path": str(self.staged_repository()),
                    "request": {"diff": "extra"},
                },
            )
        parse.assert_not_called()

    async def test_staged_generation_compacts_for_nested_audit_and_keeps_all_paths(
        self,
    ):
        root = self.repository()
        for index in range(24):
            (root / f"change-{index:02}.txt").write_text(
                ('变更说明：路径包含反斜线与引用 \\target "值"。' * 2 + "\n") * 12,
                encoding="utf-8",
            )
        self.git(root, "add", "--", ".")
        staged = await read_staged_diff(str(root))
        samples = staged.evidence(5)
        self.assertIsNotNone(samples)
        rich = ai_workflow.ContentGenerationRequest(
            kind="commit_message",
            user_request="根据暂存区生成提交信息。",
            evidence=samples,
        )
        with patch.object(
            openai_client,
            "_policy_review_payload",
            wraps=openai_client._policy_review_payload,
        ) as audit:
            self.assertFalse(ai_workflow.commit_request_fits(rich))
        audit.assert_called_once()
        with patch.object(
            openai_client, "parse_response", return_value=self.staged_candidate("S1")
        ) as parse:
            result = await generate_from_staged_diff(str(root))

        self.assertTrue(result["adoptable"])
        call = parse.call_args.kwargs
        self.assertTrue(openai_client.structured_response_fits(**call))
        evidence = json.loads(call["input"])["evidence"]
        self.assertEqual(len(evidence), 24)
        self.assertEqual(result["staged_paths"], staged.paths)
        for path, item in zip(staged.paths, evidence, strict=True):
            self.assertIn(f"A {path}", item["content"])
            self.assertIn("@@ -0,0 +1,12 @@", item["content"])

    async def test_large_index_uses_file_excerpts_in_one_audited_request(self):
        root = self.repository()
        context = (
            "reconcile_document_changes_using_stable_paths_and_registered_configuration"
        )
        base = "\n\n".join(
            f"def {context}_{index}():\n    return 'before'\n" for index in range(10)
        )
        paths = [root / f"module_{index:02}.py" for index in range(42)]
        for path in paths:
            path.write_text(base, encoding="utf-8")
        self.git(root, "add", "--", ".")
        self.git(
            root,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "--quiet",
            "--no-gpg-sign",
            "-m",
            "Fixture baseline",
        )
        for path in paths:
            path.write_text(base.replace("'before'", "'after'"), encoding="utf-8")
        self.git(root, "add", "--", ".")

        snapshot = await read_staged_diff(str(root))
        detailed = ai_workflow.ContentGenerationRequest(
            kind="commit_message",
            user_request="根据整个暂存区生成提交信息。",
            evidence=snapshot.evidence(0),
        )
        self.assertFalse(ai_workflow.commit_request_fits(detailed))

        with patch.object(
            openai_client, "parse_response", return_value=self.staged_candidate("S1")
        ) as parse:
            result = await generate_from_staged_diff(str(root))

        parse.assert_awaited_once()
        self.assertTrue(result["adoptable"])
        self.assertEqual(result["staged_paths"], [path.name for path in paths])
        self.assertEqual(result["staged_sha256"], snapshot.sha256)
        call = parse.call_args.kwargs
        self.assertTrue(openai_client.structured_response_fits(**call))
        evidence = json.loads(call["input"])["evidence"]
        self.assertEqual(len(evidence), len(paths))
        for path, item in zip(paths, evidence, strict=True):
            name, counts, ranges, *_ = item["content"].splitlines()
            self.assertEqual(name, f"M {path.name}")
            self.assertEqual(counts, "10 个 hunk，+10/-10")
            self.assertEqual(len(ranges.split()), 10)
            self.assertTrue(all("/+" in span for span in ranges.split()))

    async def test_shared_generator_fixed_kind_and_optional_body(self):
        root = self.staged_repository()
        for body in ("", "避免空报表失败。"):
            generated = ai_workflow.GeneratedContent(
                title="fix: 修复空输入处理",
                content=body,
                used_evidence_refs=["S1"],
                missing_facts=[],
                review_notes=[],
            )
            with patch.object(
                openai_client,
                "parse_response",
                new=AsyncMock(return_value=self._completed(generated)),
            ) as parse:
                result = await generate_from_staged_diff(str(root))
            self.assertTrue(result["adoptable"])
            self.assertEqual(
                result["message"], generated.title + ("\n\n" + body if body else "")
            )
            self.assertTrue(result["requires_agent_review"])
            self.assertEqual(parse.await_count, 1)
            call = parse.call_args.kwargs
            self.assertEqual(call["reasoning_effort"], "low")
            self.assertIs(call["text_format"], ai_workflow.GeneratedContent)
            self.assertEqual(json.loads(call["input"])["kind"], "commit_message")
            self.assertIn("本次选定提交范围", call["instructions"])
            self.assertIn("cached diff", call["instructions"])

    async def test_missing_facts_are_not_adoptable(self):
        root = self.staged_repository()
        generated = ai_workflow.GeneratedContent(
            title="fix: 修复输入",
            content="",
            used_evidence_refs=["S1"],
            missing_facts=["选定范围不完整"],
            review_notes=[],
        )
        with patch.object(
            openai_client,
            "parse_response",
            new=AsyncMock(return_value=self._completed(generated)),
        ):
            result = await generate_from_staged_diff(str(root))
        self.assertTrue(result["ok"])
        self.assertFalse(result["adoptable"])

    async def test_invalid_candidates_and_api_failures_do_not_yield_message(self):
        root = self.staged_repository()
        for title, body, refs in (
            ("invalid title", "", ["S1"]),
            ("fix: 修复输入", "Co-Authored-By: Example", ["S1"]),
            ("fix: 修复输入", "", ["unknown"]),
        ):
            candidate = ai_workflow.GeneratedContent(
                title=title,
                content=body,
                used_evidence_refs=refs,
                missing_facts=[],
                review_notes=[],
            )
            with patch.object(
                openai_client,
                "parse_response",
                new=AsyncMock(return_value=self._completed(candidate)),
            ):
                result = await generate_from_staged_diff(str(root))
            self.assertFalse(result["ok"])
            self.assertFalse(result["adoptable"])
            self.assertNotIn("message", result)
        with patch.object(
            openai_client,
            "parse_response",
            new=AsyncMock(side_effect=openai_client.OpenAIWorkflowError("api_timeout")),
        ):
            result = await generate_from_staged_diff(str(root))
        self.assertEqual(result["error_code"], "api_timeout")
        self.assertNotIn("message", result)

    async def test_missing_configuration_does_not_create_client(self):
        root = self.staged_repository()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(openai_client, "AsyncOpenAI") as factory,
        ):
            result = await generate_from_staged_diff(str(root))
        self.assertFalse(result["ok"])
        self.assertFalse(result["adoptable"])
        factory.assert_not_called()
