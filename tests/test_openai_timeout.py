from __future__ import annotations

import json
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import httpx2
from dev_workflow_standards_tools.infrastructure import openai_client
from pydantic import BaseModel


class ParsedContent(BaseModel):
    value: str


class OpenAITimeoutTests(unittest.IsolatedAsyncioTestCase):
    @contextmanager
    def transport(self, handler, **environment):
        clients = []
        client_type = httpx2.AsyncClient

        class CapturedClient(client_type):
            def __init__(self, **kwargs):
                super().__init__(transport=httpx2.MockTransport(handler), **kwargs)
                clients.append(self)

        with (
            patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "sk-test-timeout-key",
                    "OPENAI_BASE_URL": "https://first.synthetic.invalid/v1",
                    **environment,
                },
                clear=True,
            ),
            patch.object(openai_client.httpx2, "AsyncClient", CapturedClient),
        ):
            yield clients
        self.assertTrue(all(client.is_closed for client in clients))

    async def test_decisions_and_responses_recover_after_timeout(self):
        for api in ("decisions", "responses"):
            requests = []

            def handler(request, requests=requests, api=api):
                requests.append(request)
                if len(requests) == 1:
                    raise httpx2.ReadTimeout("synthetic timeout", request=request)
                if api == "decisions":
                    return httpx2.Response(200, json={"answers": [], "refusal": None})
                return httpx2.Response(
                    200,
                    json={
                        "id": "resp_synthetic",
                        "object": "response",
                        "created_at": 0,
                        "model": "gpt-6-luna",
                        "status": "completed",
                        "output": [
                            {
                                "id": "msg_synthetic",
                                "type": "message",
                                "role": "assistant",
                                "status": "completed",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": '{"value":"ok"}',
                                        "annotations": [],
                                    }
                                ],
                            }
                        ],
                    },
                )

            with (
                self.subTest(api=api),
                self.transport(handler) as clients,
                patch(
                    "dev_workflow_standards_tools.services.api_input_review.review_api_input",
                    return_value={"passed": True},
                ) as review,
            ):
                if api == "decisions":
                    result = await openai_client.create_decision([], [])
                    self.assertEqual(result.answers, [])
                else:
                    result = await openai_client.parse_response(
                        instructions="返回合成数据",
                        input="Synthetic input",
                        text_format=ParsedContent,
                        reasoning_effort="medium",
                        max_output_tokens=64,
                    )
                    self.assertEqual(result.output_parsed.value, "ok")
                review.assert_called_once()
                self.assertEqual(len(clients), 2)
            self.assertEqual(len(requests), 2)
            for request in requests:
                self.assertEqual(
                    request.extensions["timeout"],
                    {
                        "connect": 180.0,
                        "read": 180.0,
                        "write": 180.0,
                        "pool": 180.0,
                    },
                )
                self.assertEqual(json.loads(request.content)["model"], "gpt-6-luna")
            self.assertEqual(requests[0].content, requests[1].content)

    async def test_default_custom_and_disabled_retry_budgets_exhaust_safely(self):
        for retries, attempts in ((None, 6), ("2", 3), ("0", 1)):
            requests = []

            def handler(request, requests=requests):
                requests.append(request)
                raise httpx2.ReadTimeout("synthetic timeout", request=request)

            environment = (
                {} if retries is None else {"OPENAI_TIMEOUT_MAX_RETRIES": retries}
            )
            with (
                self.subTest(retries=retries),
                self.transport(handler, **environment) as clients,
            ):
                # 审核本身已耗尽重试预算，业务请求不能启动，也不能从外层重跑审核。
                with self.assertRaises(openai_client.OpenAIWorkflowError) as raised:
                    await openai_client.create_decision([], [])
                self.assertEqual(raised.exception.error_code, "api_timeout")
                self.assertTrue(
                    raised.exception.api_input_review["external_review_performed"]
                )
                self.assertEqual(len(clients), attempts)
            self.assertEqual(len(requests), attempts)

    async def test_invalid_retry_configuration_sends_no_requests(self):
        for value in ("", "-1", "1.5", "true", "５", "secret-invalid-value"):
            with (
                self.subTest(value=value),
                patch.dict(
                    os.environ,
                    {
                        "OPENAI_TIMEOUT_MAX_RETRIES": value,
                    },
                    clear=True,
                ),
                patch.object(openai_client, "AsyncOpenAI") as sdk,
                patch.object(openai_client.httpx2, "AsyncClient") as http,
            ):
                with self.assertRaises(openai_client.OpenAIWorkflowError) as raised:
                    await openai_client.create_decision([], [])
                self.assertEqual(
                    raised.exception.as_result(),
                    {"error_code": "invalid_timeout_max_retries"},
                )
                sdk.assert_not_called()
                http.assert_not_called()

    async def test_connection_and_http_errors_are_not_retried(self):
        for failure in ("connection", 401, 429, 503):
            requests = []

            def handler(request, requests=requests, failure=failure):
                requests.append(request)
                if failure == "connection":
                    raise httpx2.ConnectError(
                        "synthetic connection failure", request=request
                    )
                return httpx2.Response(
                    failure, json={"error": {"message": "synthetic failure"}}
                )

            with (
                self.subTest(failure=failure),
                self.transport(handler),
                self.assertRaises(openai_client.OpenAIWorkflowError),
            ):
                await openai_client._create_policy_review_decision(
                    purpose="审核输入", content="Synthetic input", questions=[]
                )
            self.assertEqual(len(requests), 1)

    async def test_retry_reads_current_credentials_endpoint_and_budget_per_call(self):
        requests = []

        def handler(request):
            requests.append(request)
            if len(requests) == 1:
                os.environ["OPENAI_API_KEY"] = "sk-test-replacement-key"
                os.environ["OPENAI_BASE_URL"] = "https://second.synthetic.invalid/v1"
                raise httpx2.ReadTimeout("synthetic timeout", request=request)
            return httpx2.Response(200, json={"answers": [], "refusal": None})

        with self.transport(handler, OPENAI_TIMEOUT_MAX_RETRIES="1"):
            await openai_client._create_policy_review_decision(
                purpose="审核输入", content="Synthetic input", questions=[]
            )
            self.assertEqual(requests[0].url.host, "first.synthetic.invalid")
            self.assertEqual(requests[1].url.host, "second.synthetic.invalid")
            self.assertEqual(
                requests[1].headers["authorization"], "Bearer sk-test-replacement-key"
            )
            os.environ["OPENAI_TIMEOUT_MAX_RETRIES"] = "0"
            requests.clear()
            with self.assertRaises(openai_client.OpenAIWorkflowError):
                await openai_client._create_policy_review_decision(
                    purpose="审核输入", content="Synthetic input", questions=[]
                )
            self.assertEqual(len(requests), 1)


if __name__ == "__main__":
    unittest.main()
