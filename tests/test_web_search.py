"""覆盖搜索完整调用链、失败关闭和实际 stdio 元数据；默认全部离线。"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx2
from mcp import Client, StdioServerParameters
from pydantic import ValidationError

from ai_workflow_fixtures import choice_answer, configured_env, decision_response
from codex_session_fixtures import tool_json
from dev_agent_toolkit_tools.infrastructure import openai_client
from dev_agent_toolkit_tools.server import mcp
from dev_agent_toolkit_tools.services import web_search as service


def search_response():
    return {
        "id": "resp_synthetic", "created_at": 1, "model": openai_client.GPT_SOL_MODEL,
        "object": "response", "status": "completed",
        "output": [
            {"id": "ws_synthetic", "type": "web_search_call", "status": "completed",
             "action": {"type": "search", "query": "asyncio docs", "sources": [
                 {"type": "url", "url": "https://docs.python.org/3/library/asyncio.html"},
                 {"type": "url", "url": "https://docs.python.org/3/library/asyncio.html"},
             ]}},
            {"id": "msg_synthetic", "type": "message", "status": "completed", "role": "assistant",
             "content": [{"type": "output_text", "text": "官方文档提供 asyncio 说明。", "annotations": [
                 {"type": "url_citation", "start_index": 0, "end_index": 4,
                  "url": "https://docs.python.org/3/library/asyncio.html", "title": "asyncio"},
             ]}]},
        ],
    }


class WebSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_routing_and_search_use_same_query_and_enforced_controls(self):
        for effort in ("low", "medium", "high"):
            with self.subTest(effort=effort):
                requests, clients = [], []

                async def handler(request):
                    payload = json.loads(request.content)
                    requests.append((request.url.path, payload))
                    if request.url.path.endswith("/decisions"):
                        answer = decision_response(choice_answer(
                            "search_effort", effort, ("low", "medium", "high")
                        ))
                        data = json.loads(json.dumps(answer, default=lambda value: vars(value)))
                    else:
                        data = search_response()
                    return httpx2.Response(200, json=data)

                client_type = httpx2.AsyncClient

                class CapturedClient(client_type):
                    def __init__(self, **kwargs):
                        super().__init__(transport=httpx2.MockTransport(handler), **kwargs)
                        clients.append(self)

                review = AsyncMock(return_value={"passed": True})
                with (
                    patch.dict(os.environ, configured_env(), clear=True),
                    patch.object(openai_client.httpx2, "AsyncClient", CapturedClient),
                    patch("dev_agent_toolkit_tools.services.api_input_review.review_api_input", review),
                ):
                    async with Client(mcp) as client:
                        result = tool_json(await client.call_tool("web_search", {"request": {
                            "query": "查找 asyncio 官方文档", "allowed_domains": ["DOCS.python.org"]
                        }}))
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["model"], openai_client.GPT_SOL_MODEL)
                self.assertEqual(result["reasoning_effort"], effort)
                self.assertEqual(result["citations"][0]["block_index"], 0)
                self.assertEqual(result["search_call_count"], 1)
                self.assertEqual(len(result["sources"]), 1)
                self.assertEqual(review.await_count, 2)
                self.assertEqual(len(requests), 2)
                self.assertTrue(all(client.is_closed for client in clients))
                decision, search = requests[0][1], requests[1][1]
                self.assertEqual(decision["model"], openai_client.GPT_LUNA_MODEL)
                self.assertNotIn("reasoning", decision)
                self.assertEqual(decision["questions"][0]["type"], "choice")
                self.assertEqual(json.loads(decision["input"][0]["content"]), json.loads(search["input"]))
                self.assertEqual(search["model"], openai_client.GPT_SOL_MODEL)
                self.assertEqual(search["reasoning"], {"effort": effort})
                self.assertEqual(search["tool_choice"], "required")
                self.assertEqual(search["include"], ["web_search_call.action.sources"])
                self.assertEqual(search["tools"][0]["filters"], {"allowed_domains": ["docs.python.org"]})
                self.assertTrue(search["tools"][0]["external_web_access"])
                self.assertFalse(search["store"])
                self.assertEqual(json.loads(review.call_args_list[1].args[1]), search)

    async def test_failed_classification_never_starts_search(self):
        for response in (
            decision_response(),
            decision_response(choice_answer("search_effort", "max", ("max",))),
            SimpleNamespace(refusal="refused", answers=[]),
        ):
            with (
                patch.object(openai_client, "create_decision", AsyncMock(return_value=response)),
                patch.object(openai_client, "create_web_search_response", AsyncMock()) as search,
            ):
                result = await service.web_search(service.WebSearchRequest(query="公开问题"))
            self.assertFalse(result["ok"])
            self.assertEqual(result["stage"], "effort_selection")
            search.assert_not_awaited()

    async def test_missing_configuration_and_rejected_review_send_zero_search_requests(self):
        for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
            for value in (None, "", "   "):
                env = configured_env()
                env.pop(name)
                if value is not None:
                    env[name] = value
                with (
                    patch.dict(os.environ, env, clear=True),
                    patch.object(openai_client, "AsyncOpenAI") as sdk,
                    patch("dev_agent_toolkit_tools.services.api_input_review.review_api_input",
                          AsyncMock(return_value={"passed": True})),
                ):
                    with self.assertRaises(openai_client.OpenAIWorkflowError):
                        await openai_client.create_web_search_response(
                            instructions="搜索公开资料", input="asyncio", allowed_domains=[], reasoning_effort="low"
                        )
                    sdk.assert_not_called()
        with (
            patch.dict(os.environ, configured_env(), clear=True),
            patch.object(openai_client, "AsyncOpenAI") as sdk,
            patch("dev_agent_toolkit_tools.services.api_input_review.review_api_input",
                  AsyncMock(return_value={"passed": False, "status": "needs_revision"})),
        ):
            with self.assertRaises(openai_client.OpenAIWorkflowError):
                await openai_client.create_web_search_response(
                    instructions="公开搜索", input="公开问题", allowed_domains=[], reasoning_effort="low"
                )
            sdk.assert_not_called()

    def test_response_failures_cannot_be_reported_as_success(self):
        cases = []
        data = search_response()
        data["status"] = "incomplete"
        cases.append((data, "search_response_incomplete"))
        data = search_response()
        data["output"].pop(0)
        cases.append((data, "search_not_completed"))
        data = search_response()
        data["output"][1]["content"][0]["annotations"] = []
        cases.append((data, "search_evidence_missing"))
        data = search_response()
        data["output"][1]["content"] = [{"type": "refusal", "refusal": "refused"}]
        cases.append((data, "search_refused"))
        for url, end in (("javascript:alert(1)", 4), ("https://example.com", 999)):
            data = search_response()
            data["output"][1]["content"][0]["annotations"][0].update(url=url, end_index=end)
            cases.append((data, "invalid_search_citation"))
        for data, code in cases:
            result = service._search_result(SimpleNamespace(model_dump=lambda **kwargs: data))
            self.assertEqual(result, {"ok": False, "error_code": code})
        data = copy.deepcopy(search_response())
        data["output"][0]["action"]["sources"] = None
        self.assertTrue(service._search_result(SimpleNamespace(model_dump=lambda **kwargs: data))["ok"])

    def test_input_constraints(self):
        for changes in (
            {"query": " "}, {"query": "x" * 8001}, {"allowed_domains": None},
            {"response_language": " "}, {"model": "other"}, {"reasoning_effort": "high"},
            *({"allowed_domains": [domain]} for domain in (
                "https://example.com", "example.com/path", "example.com:443", "*.example.com", "127.0.0.1"
            )),
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                service.WebSearchRequest(**({"query": "公开问题"} | changes))

    async def test_real_stdio_initialize_and_search_discovery(self):
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "dev_agent_toolkit_tools.server"],
            cwd=Path(__file__).resolve().parents[1] / "mcp-server", env={},
        )
        async with asyncio.timeout(20), Client(params) as client:
            self.assertIn("公开网络搜索", client.instructions)
            tools = {item.name: item for item in (await client.list_tools()).tools}
            tool = tools["web_search"]
            for phrase in (
                openai_client.GPT_LUNA_MODEL,
                openai_client.GPT_SOL_MODEL,
                "Decisions",
                "OPENAI_BASE_URL",
                "search_evidence_missing",
                "Pi",
            ):
                self.assertIn(phrase, tool.description)
            self.assertTrue(tool.annotations.read_only_hint)
            self.assertTrue(tool.annotations.open_world_hint)
            self.assertFalse(tool.annotations.idempotent_hint)
            schema = tool.input_schema
            self.assertEqual(schema["required"], ["request"])
            request = schema["$defs"]["WebSearchRequest"]
            self.assertFalse(request["additionalProperties"])
            self.assertEqual(request["required"], ["query"])
            self.assertTrue(all(field["description"] for field in request["properties"].values()))


if __name__ == "__main__":
    unittest.main()
