from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

from ai_workflow_fixtures import ContentGenerationTestCase
from dev_agent_toolkit_tools.infrastructure import openai_client
from dev_agent_toolkit_tools.services import ai_workflow
from dev_agent_toolkit_tools.services.commit_content import (
    CommitMessageRequest,
    generate_git_commit_message,
)
from pydantic import ValidationError


class CommitContentTests(ContentGenerationTestCase):
    def request(self, **changes):
        return CommitMessageRequest(
            **{
                "user_request": "概述本次空输入修复",
                "evidence": [
                    {
                        "reference_id": "D1",
                        "origin": "current_observation",
                        "content": "本次选定patch仅report.py的空输入分支，原抛错，现返回空列表；测试未运行",
                    }
                ],
                **changes,
            }
        )

    async def test_shared_generator_fixed_kind_and_optional_body(self):
        for body in ("", "避免空报表失败；测试未运行。"):
            generated = ai_workflow.GeneratedContent(
                title="fix: 修复空输入处理",
                content=body,
                used_evidence_refs=["D1"],
                missing_facts=[],
                review_notes=[],
            )
            with patch.object(
                openai_client,
                "parse_response",
                new=AsyncMock(return_value=self._completed(generated)),
            ) as parse:
                result = await generate_git_commit_message(self.request())
            self.assertTrue(result["adoptable"])
            self.assertEqual(
                result["message"], generated.title + ("\n\n" + body if body else "")
            )
            self.assertEqual(result["validation_scope"], "local_format_and_attribution")
            self.assertTrue(result["requires_agent_review"])
            self.assertFalse(result["executed_external_actions"])
            self.assertEqual(parse.await_count, 1)
            call = parse.call_args.kwargs
            self.assertEqual(call["reasoning_effort"], "low")
            self.assertIs(call["text_format"], ai_workflow.GeneratedContent)
            self.assertEqual(json.loads(call["input"])["kind"], "commit_message")
            self.assertIn("本次选定提交范围", call["instructions"])
            self.assertIn("cached diff", call["instructions"])

    async def test_missing_facts_are_not_adoptable(self):
        generated = ai_workflow.GeneratedContent(
            title="fix: 修复输入",
            content="",
            used_evidence_refs=["D1"],
            missing_facts=["选定范围不完整"],
            review_notes=[],
        )
        with patch.object(
            openai_client,
            "parse_response",
            new=AsyncMock(return_value=self._completed(generated)),
        ):
            result = await generate_git_commit_message(self.request())
        self.assertTrue(result["ok"])
        self.assertFalse(result["adoptable"])

    async def test_invalid_candidates_and_api_failures_do_not_yield_message(self):
        for title, body, refs in (
            ("invalid title", "", ["D1"]),
            ("fix: 修复输入", "Co-Authored-By: Example", ["D1"]),
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
                result = await generate_git_commit_message(self.request())
            self.assertFalse(result["ok"])
            self.assertFalse(result["adoptable"])
            self.assertNotIn("message", result)
        with patch.object(
            openai_client,
            "parse_response",
            new=AsyncMock(side_effect=openai_client.OpenAIWorkflowError("api_timeout")),
        ):
            result = await generate_git_commit_message(self.request())
        self.assertEqual(result["error_code"], "api_timeout")
        self.assertNotIn("message", result)

    async def test_missing_configuration_does_not_create_client(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(openai_client, "AsyncOpenAI") as factory,
        ):
            result = await generate_git_commit_message(self.request())
        self.assertFalse(result["ok"])
        self.assertFalse(result["adoptable"])
        factory.assert_not_called()

    def test_strict_request_and_shared_validation(self):
        for changes in (
            {"kind": "pr"},
            {"model": "other"},
            {"source": None},
            {"language_override": None},
            {"evidence": []},
            {"user_request": " "},
            {"focus_questions": [" "]},
            {"output_format": " "},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.request(**changes)
        data = self.request().model_dump()
        data["evidence"] *= 2
        with self.assertRaises(ValidationError):
            CommitMessageRequest.model_validate(data)
