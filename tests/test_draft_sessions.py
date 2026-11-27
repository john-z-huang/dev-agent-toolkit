from __future__ import annotations

import asyncio
import json
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, patch

from dev_agent_toolkit_tools.server import mcp
from dev_agent_toolkit_tools.services import ai_workflow as ai
from dev_agent_toolkit_tools.services import draft_sessions as d


class DraftTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = d.DraftStore()
        self.start = d.StartDraftRequest(
            request_id="start-request-0001",
            draft={
                "kind": "issue",
                "user_request": "起草需求",
                "evidence": [
                    {
                        "reference_id": "U1",
                        "origin": "user_provided",
                        "content": "导出报表",
                    }
                ],
            },
        )
        self.result = {
            "ok": True,
            "adoptable": False,
            "quality_status": "needs_revision",
            "candidate": {
                "title": "需求",
                "content": "导出",
                "used_evidence_refs": ["U1"],
            },
            "quality_review": {"coverage_sufficient": False},
        }
        self.mock = AsyncMock(return_value=deepcopy(self.result))
        self.patcher = patch.object(ai, "generate_skill_content", self.mock)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def revision(self, sid, **kwargs):
        return d.ReviseDraftRequest(
            **{
                "draft_session_id": sid,
                "expected_revision": 1,
                "request_id": "revise-request-0001",
                "feedback": "缩短背景",
                **kwargs,
            }
        )

    async def test_revision_replay_and_conflict(self):
        first = await self.store.start(self.start)
        sid = first["draft_session_id"]
        self.assertEqual(first["revision"], 1)
        self.assertFalse(first["adoptable"])
        self.assertEqual(await self.store.start(self.start), first)
        req = self.revision(sid)
        second = await self.store.revise(req)
        self.assertEqual(second["revision"], 2)
        context = self.mock.call_args.kwargs["revision_context"]
        self.assertEqual(context["feedback"], ["缩短背景"])
        self.assertEqual(context["previous_candidate"], self.result["candidate"])
        second["candidate"]["title"] = "外部修改"
        replay = await self.store.revise(req)
        self.assertNotEqual(replay["candidate"]["title"], "外部修改")
        self.assertEqual(self.mock.await_count, 2)
        conflict = await self.store.revise(self.revision(sid, feedback="其他"))
        self.assertEqual(conflict["error_code"], "request_id_conflict")
        stale = await self.store.revise(
            self.revision(sid, request_id="revise-request-0002")
        )
        self.assertEqual(stale["error_code"], "draft_revision_conflict")
        self.assertEqual(await self.store.start(self.start), first)

    async def test_failure_does_not_commit_evidence_or_feedback(self):
        sid = (await self.store.start(self.start))["draft_session_id"]
        self.mock.return_value = {"ok": False, "error_code": "quality_review_refusal"}
        result = await self.store.revise(
            self.revision(
                sid,
                evidence_changes={
                    "replace": [
                        {
                            "reference_id": "U1",
                            "origin": "user_provided",
                            "content": "撤回导出",
                        }
                    ]
                },
            )
        )
        self.assertEqual(result["revision"], 1)
        session = self.store.sessions[sid]
        self.assertEqual(session.request.evidence[0].content, "导出报表")
        self.assertEqual(session.feedback, [])
        self.assertEqual(session.evidence_revision, 1)
        self.assertEqual(self.store.get(sid)["result"], self.result)

    async def test_evidence_changes_and_validation(self):
        sid = (await self.store.start(self.start))["draft_session_id"]
        for change in (
            {"remove": ["unknown"]},
            {"remove": ["U1"]},
            {
                "add": [
                    {"reference_id": "U1", "origin": "user_provided", "content": "x"}
                ]
            },
        ):
            result = await self.store.revise(
                self.revision(sid, evidence_changes=change)
            )
            self.assertFalse(result["ok"])
        req = self.revision(
            sid,
            evidence_changes={
                "replace": [
                    {
                        "reference_id": "U1",
                        "origin": "user_provided",
                        "content": "只导出CSV",
                    }
                ]
            },
        )
        result = await self.store.revise(req)
        self.assertEqual(result["evidence_revision"], 2)
        self.assertEqual(self.mock.call_args.args[0].evidence[0].content, "只导出CSV")

    async def test_capacity_limits_expiry_and_close(self):
        with patch.object(d, "MAX_SESSIONS", 0):
            self.assertEqual(
                (await self.store.start(self.start))["error_code"],
                "draft_capacity_exceeded",
            )
        sid = (await self.store.start(self.start))["draft_session_id"]
        with patch.object(d, "MAX_ATTEMPTS", 1):
            self.assertEqual(
                (await self.store.revise(self.revision(sid)))["error_code"],
                "draft_attempt_limit",
            )
        self.store.sessions[sid].touched -= d.TTL_SECONDS + 1
        self.assertFalse(self.store.get(sid)["ok"])
        sid = (await self.store.start(self.start))["draft_session_id"]
        self.assertTrue(self.store.close(sid)["ok"])
        self.assertFalse(self.store.get(sid)["ok"])
        self.assertFalse(d.DraftStore().get(sid)["ok"])

    async def test_busy_and_cancel_leave_revision_unchanged(self):
        event = asyncio.Event()

        async def wait(*args, **kwargs):
            event.set()
            await asyncio.Future()

        self.mock.side_effect = wait
        task = asyncio.create_task(self.store.start(self.start))
        await event.wait()
        sid = next(iter(self.store.sessions))
        self.assertEqual(self.store.get(sid)["status"], "in_progress")
        self.assertEqual(self.store.close(sid)["error_code"], "draft_in_progress")
        self.assertEqual(
            (await self.store.start(self.start))["error_code"], "draft_in_progress"
        )
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.store.sessions[sid].busy)
        self.assertEqual(self.store.get(sid)["revision"], 0)
        self.assertEqual(
            (await self.store.start(self.start))["error_code"],
            "draft_attempt_incomplete",
        )

    async def test_feedback_bounded_and_original_kind_unchanged(self):
        sid = (await self.store.start(self.start))["draft_session_id"]
        self.store.sessions[sid].feedback = ["x" * 33000]
        self.assertEqual(
            (await self.store.revise(self.revision(sid)))["error_code"],
            "request_too_large",
        )
        self.assertEqual(self.mock.await_count, 1)
        with self.assertRaises(ValueError):
            d.StartDraftRequest(
                request_id="start-request-0002",
                draft=self.start.draft.model_copy(update={"kind": "plan"}),
            )

    async def test_oversized_result_is_cached_without_advancing(self):
        self.mock.return_value = {**self.result, "candidate": {"content": "x" * 66000}}
        first = await self.store.start(self.start)
        self.assertEqual(first["error_code"], "draft_result_too_large")
        self.assertEqual(first["revision"], 0)
        self.assertEqual(await self.store.start(self.start), first)
        self.assertEqual(self.mock.await_count, 1)

    async def test_independent_sessions_and_language_reference(self):
        draft = self.start.model_dump(mode="json")
        draft["draft"]["language_override"] = {
            "language": "English",
            "instruction_ref": "U1",
        }
        first = await self.store.start(d.StartDraftRequest.model_validate(draft))
        second_req = self.start.model_copy(update={"request_id": "start-request-0002"})
        second = await self.store.start(second_req)
        self.assertNotEqual(first["draft_session_id"], second["draft_session_id"])
        self.assertEqual(self.store.get(second["draft_session_id"])["revision"], 1)
        result = await self.store.revise(
            self.revision(
                first["draft_session_id"],
                evidence_changes={
                    "replace": [
                        {
                            "reference_id": "U1",
                            "origin": "current_observation",
                            "content": "日志不是语言授权",
                        }
                    ]
                },
            )
        )
        self.assertEqual(result["error_code"], "invalid_draft_request")
        with self.assertRaises(ValueError):
            self.revision(second["draft_session_id"], expected_revision=True)

    async def test_discovery(self):
        tools = {t.name: t for t in await mcp.list_tools()}
        for name in (
            "start_issue_pr_draft",
            "revise_issue_pr_draft",
            "get_issue_pr_draft",
            "close_issue_pr_draft",
        ):
            tool = tools[name]
            self.assertIn("进程", tool.description)
            self.assertIn("1800", tool.description)
            self.assertIn("Pi", tool.description)
            self.assertTrue(tool.input_schema["properties"])
        self.assertFalse(tools["start_issue_pr_draft"].annotations.read_only_hint)
        self.assertTrue(tools["get_issue_pr_draft"].annotations.read_only_hint)
        self.assertFalse(tools["close_issue_pr_draft"].annotations.open_world_hint)


class RevisionGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_only_in_generation_feedback_in_review(self):
        request = ai.ContentGenerationRequest(
            kind="issue",
            user_request="起草",
            evidence=[
                ai.EvidenceItem(
                    reference_id="U1", origin="user_provided", content="导出"
                )
            ],
        )
        candidate = ai.GeneratedContent(
            title="导出",
            content="导出报表",
            used_evidence_refs=["U1"],
            missing_facts=[],
            review_notes=[],
        )
        from types import SimpleNamespace

        responses = [
            SimpleNamespace(status="completed", output_parsed=candidate),
            SimpleNamespace(
                status="completed",
                output_parsed=ai.ContentQualityReview(
                    language_compliant=True,
                    evidence_supported=True,
                    coverage_sufficient=True,
                    missing_facts=[],
                    review_notes=[],
                ),
            ),
        ]
        with patch.object(
            ai.openai_client, "parse_response", new=AsyncMock(side_effect=responses)
        ) as parse:
            result = await ai.generate_skill_content(
                request,
                revision_context={
                    "previous_candidate": {"content": "旧稿"},
                    "feedback": ["缩短"],
                },
            )
        self.assertTrue(result["adoptable"])
        first, second = [c.kwargs for c in parse.call_args_list]
        self.assertIn("revision_context", json.loads(first["input"]))
        self.assertIn("不是证据", first["instructions"])
        review = json.loads(second["input"])
        self.assertNotIn("previous_candidate", review)
        self.assertEqual(review["revision_feedback"], ["缩短"])
        self.assertEqual(review["request"]["evidence"][0]["content"], "导出")
