"""离线验证异步请求的并发、取消、配置轮换，以及服务与 MCP 的等待关系。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio
import httpx2
from mcp.client import Client

from dev_workflow_standards_tools.infrastructure import openai_client
from dev_workflow_standards_tools.server import mcp
from dev_workflow_standards_tools.services import ai_workflow

ENVIRONMENT = {
    "OPENAI_API_KEY": "sk-test-async-original-key",
    "OPENAI_BASE_URL": "https://async.synthetic.invalid/v1",
}


class AsyncOpenAITransportTests(unittest.IsolatedAsyncioTestCase):
    """使用真实异步 SDK 和模拟 HTTP 传输，核对请求生命周期。"""

    @asynccontextmanager
    async def transport(self, handler, *, skip_review=True):
        """隔离模拟配置并记录客户端；默认替换语义审核以单独测试业务请求。

        skip_review=False 时保留真实审核调用链，仍由模拟传输拦截全部 HTTP 请求。
        """
        clients = []
        client_type = httpx2.AsyncClient

        class CapturedClient(client_type):
            def __init__(self, **kwargs):
                super().__init__(transport=httpx2.MockTransport(handler), **kwargs)
                clients.append(self)

        with (
            patch.dict(os.environ, ENVIRONMENT, clear=True),
            patch.object(openai_client.httpx2, "AsyncClient", CapturedClient),
        ):
            if skip_review:
                with patch(
                    "dev_workflow_standards_tools.services.api_input_review.review_api_input",
                    new=AsyncMock(return_value={"passed": True}),
                ):
                    yield clients
            else:
                yield clients

    async def test_independent_request_completes_while_another_waits(self):
        """慢请求停在网络等待点时，独立请求仍能完成，两个客户端最终均关闭。"""
        entered = asyncio.Event()
        release = asyncio.Event()

        async def handler(request):
            if json.loads(request.content)["input"][0]["content"] == "slow":
                entered.set()
                await release.wait()
            return httpx2.Response(200, json={"answers": [], "refusal": None})

        async with self.transport(handler) as clients:
            slow = asyncio.create_task(
                openai_client.create_decision([{"role": "user", "content": "slow"}], [])
            )
            try:
                # 用事件确认请求已进入等待，不通过睡眠时长推测调度顺序。
                await asyncio.wait_for(entered.wait(), 2)
                fast = await asyncio.wait_for(
                    openai_client.create_decision(
                        [{"role": "user", "content": "fast"}], []
                    ),
                    2,
                )
                self.assertEqual(fast.answers, [])
                self.assertFalse(slow.done())
            finally:
                release.set()
                await slow
        self.assertEqual(len(clients), 2)
        self.assertTrue(all(client.is_closed for client in clients))

    async def test_cancellation_during_review_closes_client_without_business_request(
        self,
    ):
        """审核期间取消调用，只留下已尝试的审核请求，业务请求不得启动。"""
        entered = asyncio.Event()
        requests = []

        async def handler(request):
            requests.append(json.loads(request.content))
            entered.set()
            await asyncio.Event().wait()

        async with self.transport(handler, skip_review=False) as clients:
            task = asyncio.create_task(openai_client.create_decision([], []))
            try:
                await asyncio.wait_for(entered.wait(), 2)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            [q["name"] for q in requests[0]["questions"]], ["purpose", "content"]
        )
        self.assertTrue(all(client.is_closed for client in clients))

    async def test_anyio_cancellation_shields_asynchronous_cleanup(self):
        """AnyIO 持续取消整个作用域时，关闭连接仍可在屏蔽区完成。"""
        entered = anyio.Event()
        requests = []

        async def handler(request):
            requests.append(request)
            entered.set()
            await anyio.sleep_forever()

        async with (
            self.transport(handler) as clients,
            anyio.create_task_group() as group,
        ):
            group.start_soon(openai_client.create_decision, [], [])
            with anyio.fail_after(2):
                await entered.wait()
            group.cancel_scope.cancel()
        self.assertEqual(len(requests), 1)
        self.assertTrue(all(client.is_closed for client in clients))

    async def test_retry_reuses_payload_but_reads_rotated_configuration_and_redacts_old_values(
        self,
    ):
        """超时重试复用请求正文、读取新配置，并继续掩蔽进行中请求的旧配置。"""
        requests = []
        logger = logging.getLogger("openai.async_rotation_test")

        async def handler(request):
            requests.append(request)
            if len(requests) == 1:
                # 仅在隔离测试中模拟环境轮换；生产请求不修改 os.environ。
                os.environ["OPENAI_API_KEY"] = "sk-test-async-rotated-key"
                os.environ["OPENAI_BASE_URL"] = "https://rotated.synthetic.invalid/v1"
                logger.warning(
                    "old request %s %s",
                    ENVIRONMENT["OPENAI_API_KEY"],
                    ENVIRONMENT["OPENAI_BASE_URL"],
                )
                raise httpx2.ReadTimeout("synthetic timeout", request=request)
            return httpx2.Response(200, json={"answers": [], "refusal": None})

        async with self.transport(handler) as clients:
            with self.assertLogs(logger, "WARNING") as captured:
                response = await openai_client.create_decision([], [])
        self.assertEqual(response.answers, [])
        self.assertEqual(requests[0].content, requests[1].content)
        self.assertEqual(requests[0].url.host, "async.synthetic.invalid")
        self.assertEqual(requests[1].url.host, "rotated.synthetic.invalid")
        self.assertEqual(
            requests[1].headers["authorization"], "Bearer sk-test-async-rotated-key"
        )
        self.assertTrue(all(client.is_closed for client in clients))
        self.assertNotIn(ENVIRONMENT["OPENAI_API_KEY"], str(captured.output))
        self.assertNotIn(ENVIRONMENT["OPENAI_BASE_URL"], str(captured.output))
        self.assertEqual(openai_client._active_secrets.get(), ())

    async def test_cleanup_timeout_is_bounded_without_raw_diagnostics(self):
        """清理永久等待时也能在设定上限内结束，只记录安全的超时分类。"""
        completed = asyncio.Event()

        async def close():
            try:
                await anyio.sleep_forever()
            finally:
                completed.set()

        with (
            patch.object(openai_client, "CLIENT_CLEANUP_SECONDS", 0.01),
            self.assertLogs(openai_client.__name__, "WARNING") as captured,
        ):
            await asyncio.wait_for(openai_client._close_resource(close), 1)
        self.assertTrue(completed.is_set())
        self.assertIn("cleanup timed out", str(captured.output))


class AsyncServiceAndMCPTests(unittest.IsolatedAsyncioTestCase):
    """验证生成与审查的数据依赖，以及 MCP 对异步服务的真实等待。"""

    def request(self):
        """为每个测试提供独立的 Issue 生成请求，避免共享可变证据。"""
        return ai_workflow.ContentGenerationRequest(
            kind="issue",
            user_request="记录空输入修复",
            evidence=[
                {
                    "reference_id": "F1",
                    "content": "original fact",
                    "origin": "current_observation",
                }
            ],
        )

    async def test_cancelling_generation_never_starts_quality_review(self):
        """首次生成尚未完成便取消时，不调用依赖其结果的质量审查。"""
        entered = asyncio.Event()

        async def parse(**kwargs):
            entered.set()
            await asyncio.Event().wait()

        with (
            patch.object(
                openai_client, "parse_response", side_effect=parse
            ) as parse_mock,
            patch.object(ai_workflow, "_review_issue_pr") as review,
        ):
            task = asyncio.create_task(
                ai_workflow.generate_skill_content(self.request())
            )
            try:
                await asyncio.wait_for(entered.wait(), 2)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        parse_mock.assert_awaited_once()
        review.assert_not_awaited()

    async def test_generation_and_quality_review_use_same_facts_after_caller_mutates_request(
        self,
    ):
        """调用方在生成等待期间修改嵌套证据，不影响生成和审查使用的事实快照。"""
        entered = asyncio.Event()
        release = asyncio.Event()
        inputs = []
        request = self.request()
        generated = ai_workflow.GeneratedContent(
            title="修复空输入",
            content="original fact",
            used_evidence_refs=["F1"],
            missing_facts=[],
            review_notes=[],
        )
        quality = ai_workflow.ContentQualityReview(
            language_compliant=True,
            evidence_supported=True,
            coverage_sufficient=True,
            missing_facts=[],
            review_notes=[],
        )

        async def parse(**kwargs):
            inputs.append(kwargs["input"])
            if len(inputs) == 1:
                entered.set()
                await release.wait()
            return SimpleNamespace(
                status="completed",
                refusal=None,
                output_parsed=generated if len(inputs) == 1 else quality,
            )

        with patch.object(openai_client, "parse_response", side_effect=parse):
            task = asyncio.create_task(ai_workflow.generate_skill_content(request))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                request.evidence[0].content = "changed after first await"
            finally:
                release.set()
                result = await task
        self.assertTrue(result["adoptable"])
        self.assertEqual(len(inputs), 2)
        self.assertTrue(
            all(
                "original fact" in value and "changed after first await" not in value
                for value in inputs
            )
        )

    async def test_mcp_adapter_awaits_api_service_and_preserves_result(self):
        """通过 MCP 实际调用工具，取得校验结果，并确认异步 API 边界被等待。"""
        values = ai_workflow.DECISION_CHOICES
        response = SimpleNamespace(
            refusal=None,
            answers=[
                SimpleNamespace(
                    type="choice",
                    name="commit_policy",
                    choice="compliant",
                    confidence=1.0,
                    probabilities=[
                        SimpleNamespace(value=value, probability=1 / len(values))
                        for value in values
                    ],
                )
            ],
        )
        with patch.object(
            openai_client, "create_decision", return_value=response
        ) as decide:
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_commit_message", {"message": "fix: 修复空输入"}
                )
        self.assertFalse(result.is_error)
        self.assertTrue(json.loads(result.content[0].text)["passed"])
        decide.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
