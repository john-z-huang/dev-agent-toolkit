from __future__ import annotations

import logging
import os
import unittest
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from ai_workflow_fixtures import (
    API_KEY_A,
    API_KEY_B,
    BASE_URL_A,
    BASE_URL_B,
    choice_answer,
    configured_env,
    decision_response,
    sdk_client,
)
from dev_workflow_standards_tools.infrastructure import openai_client
from dev_workflow_standards_tools.services.ai_workflow import (
    GeneratedContent,
)


class OpenAIClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.http_clients: list[Mock] = []

        def make_http_client(**kwargs: object) -> Mock:
            client = Mock(aclose=AsyncMock())
            client.trust_env = kwargs.get("trust_env")
            self.http_clients.append(client)
            return client

        client_patcher = patch.object(
            openai_client.httpx2, "AsyncClient", side_effect=make_http_client
        )
        client_patcher.start()
        self.addCleanup(client_patcher.stop)
        self.addAsyncCleanup(self.close_http_clients)

    async def close_http_clients(self) -> None:
        """清理未交给真实 SDK 管理的模拟传输，避免测试替身留下资源。"""
        for client in self.http_clients:
            if not client.aclose.called:
                await client.aclose()

    async def test_missing_or_blank_environment_prevents_client_creation(self) -> None:
        cases = [
            {"OPENAI_API_KEY": "", "OPENAI_BASE_URL": BASE_URL_A},
            {"OPENAI_API_KEY": API_KEY_A, "OPENAI_BASE_URL": "   "},
            {},
        ]
        for environment in cases:
            with (
                self.subTest(environment_keys=list(environment)),
                patch.dict(os.environ, environment, clear=True),
                patch.object(openai_client, "AsyncOpenAI") as factory,
            ):
                with self.assertRaises(openai_client.OpenAIWorkflowError):
                    await openai_client.create_decision([], [])
                factory.assert_not_called()
                with patch.object(openai_client.httpx2, "AsyncClient") as http_factory:
                    with self.assertRaises(openai_client.OpenAIWorkflowError):
                        await openai_client.create_decision([], [])
                    http_factory.assert_not_called()

    async def test_bad_base_url_is_rejected_without_echoing_it(self) -> None:
        for url in (
            "ftp://api.example.invalid/v1",
            "https://user:password@api.example.invalid/v1",
            "https://api.example.invalid/v1?secret=token",
            "https://api.example.invalid/v1#fragment",
        ):
            with (
                self.subTest(url_kind=url.split(":", 1)[0]),
                patch.dict(os.environ, configured_env(OPENAI_BASE_URL=url), clear=True),
                patch.object(openai_client, "AsyncOpenAI") as factory,
            ):
                with self.assertRaises(openai_client.OpenAIWorkflowError) as raised:
                    await openai_client.create_decision([], [])
                self.assertEqual(raised.exception.error_code, "invalid_base_url")
                self.assertNotIn(url, str(raised.exception))
                factory.assert_not_called()

    async def test_each_request_reads_environment_and_passes_explicit_config(
        self,
    ) -> None:
        answer = decision_response(choice_answer("q", "compliant", ("compliant",)))
        first = sdk_client()
        first.decisions.create.return_value = answer
        second = sdk_client()
        second.decisions.create.return_value = answer
        transport_a = Mock(aclose=AsyncMock())
        transport_b = Mock(aclose=AsyncMock())
        with (
            patch.dict(os.environ, configured_env(), clear=True),
            patch.object(
                openai_client, "AsyncOpenAI", side_effect=[first, second]
            ) as factory,
            patch.object(
                openai_client.httpx2,
                "AsyncClient",
                side_effect=[transport_a, transport_b],
            ) as transport_factory,
            patch(
                "dev_workflow_standards_tools.services.api_input_review.review_api_input",
                return_value={"passed": True},
            ),
        ):
            await openai_client.create_decision([], [])
            os.environ["OPENAI_API_KEY"] = API_KEY_B
            os.environ["OPENAI_BASE_URL"] = BASE_URL_B
            await openai_client.create_decision([], [])
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(factory.call_args_list[0].kwargs["api_key"], API_KEY_A)
        self.assertEqual(factory.call_args_list[0].kwargs["base_url"], BASE_URL_A)
        self.assertEqual(factory.call_args_list[1].kwargs["api_key"], API_KEY_B)
        self.assertEqual(factory.call_args_list[1].kwargs["base_url"], BASE_URL_B)
        for call in factory.call_args_list:
            self.assertEqual(
                call.kwargs["timeout"], openai_client.OPENAI_TIMEOUT_SECONDS
            )
            self.assertEqual(call.kwargs["max_retries"], 0)
            self.assertEqual(
                set(call.kwargs),
                {"api_key", "base_url", "timeout", "max_retries", "http_client"},
            )
        self.assertEqual(factory.call_args_list[0].kwargs["http_client"], transport_a)
        self.assertEqual(factory.call_args_list[1].kwargs["http_client"], transport_b)
        self.assertEqual(transport_factory.call_count, 2)
        self.assertTrue(
            all(
                call.kwargs == {"trust_env": True}
                for call in transport_factory.call_args_list
            )
        )
        first.close.assert_awaited_once()
        second.close.assert_awaited_once()
        await transport_a.aclose()
        await transport_b.aclose()

    async def test_secret_or_endpoint_in_payload_is_blocked_before_client_creation(
        self,
    ) -> None:
        for sensitive_value in (API_KEY_A, BASE_URL_A):
            with (
                self.subTest(
                    kind="secret" if sensitive_value == API_KEY_A else "endpoint"
                ),
                patch.dict(os.environ, configured_env(), clear=True),
                patch.object(openai_client, "AsyncOpenAI") as factory,
            ):
                with self.assertRaises(openai_client.OpenAIWorkflowError) as raised:
                    await openai_client.create_decision(
                        [{"role": "user", "content": sensitive_value}], []
                    )
                self.assertEqual(
                    raised.exception.error_code, "sensitive_input_detected"
                )
                self.assertNotIn(sensitive_value, str(raised.exception))
                factory.assert_not_called()

    async def test_api_errors_and_sensitive_responses_are_sanitized(self) -> None:
        fake = sdk_client()
        fake.decisions.create.side_effect = RuntimeError(f"{API_KEY_A} {BASE_URL_A}")
        with (
            patch.dict(os.environ, configured_env(), clear=True),
            patch.object(openai_client, "AsyncOpenAI", return_value=fake),
            patch(
                "dev_workflow_standards_tools.services.api_input_review.review_api_input",
                return_value={"passed": True},
            ),
            self.assertRaises(openai_client.OpenAIWorkflowError) as raised,
        ):
            await openai_client.create_decision([], [])
        self.assertEqual(raised.exception.error_code, "api_request_failed")
        self.assertNotIn(API_KEY_A, str(raised.exception))
        self.assertNotIn(BASE_URL_A, str(raised.exception))

        sensitive_response = SimpleNamespace(secret=API_KEY_A)
        fake = sdk_client()
        fake.decisions.create.return_value = sensitive_response
        with (
            patch.dict(os.environ, configured_env(), clear=True),
            patch.object(openai_client, "AsyncOpenAI", return_value=fake),
            patch(
                "dev_workflow_standards_tools.services.api_input_review.review_api_input",
                return_value={"passed": True},
            ),
            self.assertRaises(openai_client.OpenAIWorkflowError) as raised,
        ):
            await openai_client.create_decision([], [])
        self.assertEqual(raised.exception.error_code, "sensitive_value_in_response")

    def test_log_redaction_survives_broken_message_and_traceback_formatting(
        self,
    ) -> None:
        original_factory = logging.getLogRecordFactory()
        self.addCleanup(logging.setLogRecordFactory, original_factory)
        with patch.dict(os.environ, configured_env(), clear=True):
            openai_client._install_log_redaction()
            factory = logging.getLogRecordFactory()
            exc_info = (RuntimeError, RuntimeError(API_KEY_A), None)
            with (
                patch.object(
                    logging.LogRecord, "getMessage", side_effect=RuntimeError(API_KEY_A)
                ),
                patch.object(
                    openai_client.traceback,
                    "format_exception",
                    side_effect=RuntimeError(BASE_URL_A),
                ),
            ):
                record = factory(
                    "synthetic",
                    logging.ERROR,
                    __file__,
                    1,
                    f"{API_KEY_A} {BASE_URL_A}",
                    (),
                    exc_info,
                )

        self.assertNotIn(API_KEY_A, record.msg)
        self.assertNotIn(BASE_URL_A, record.msg)
        self.assertEqual(record.args, ())
        self.assertEqual(record.exc_text, "[REDACTED]")

    def test_log_records_redact_current_api_and_proxy_settings(self) -> None:
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger = logging.getLogger("openai.httpx.redaction_test")
        root_logger = logging.getLogger()
        previous_root_handlers = root_logger.handlers[:]
        previous_level = logger.level
        previous_propagate = logger.propagate
        logger.setLevel(logging.DEBUG)
        logger.propagate = True
        for existing_handler in previous_root_handlers:
            root_logger.removeHandler(existing_handler)
        root_logger.addHandler(handler)
        try:
            proxy_setting = "http://proxy-user:proxy-pass@proxy.example.invalid:8123"
            with patch.dict(
                os.environ, configured_env(http_proxy=proxy_setting), clear=True
            ):
                logger.info("request configuration %s", API_KEY_A)
                logger.debug("selected endpoint %s", BASE_URL_A)
                logger.debug("selected proxy %s", proxy_setting)
                logger.debug(
                    "connect_tcp.started host=%r port=%s",
                    "proxy.example.invalid",
                    "8123",
                )
                try:
                    raise RuntimeError(
                        f"transport failed for {API_KEY_A} at {BASE_URL_A} via {proxy_setting}"
                    )
                except RuntimeError:
                    logger.exception("request failed")
            output = stream.getvalue()
            self.assertIn("INFO", output)
            self.assertIn("DEBUG", output)
            self.assertIn("RuntimeError", output)
            self.assertNotIn(API_KEY_A, output)
            self.assertNotIn(BASE_URL_A, output)
            self.assertNotIn(proxy_setting, output)
            self.assertEqual(output.count("[REDACTED]"), 8)
        finally:
            root_logger.removeHandler(handler)
            for existing_handler in previous_root_handlers:
                root_logger.addHandler(existing_handler)
            logger.setLevel(previous_level)
            logger.propagate = previous_propagate
            handler.close()

    async def test_decisions_uses_fixed_model_and_no_reasoning_or_store_options(
        self,
    ) -> None:
        fake = sdk_client()
        fake.decisions.create.return_value = decision_response(
            choice_answer("q", "compliant", ("compliant",))
        )
        question = [
            {
                "type": "choice",
                "name": "q",
                "instructions": "fixed",
                "choices": [{"value": "compliant"}],
            }
        ]
        with (
            patch.dict(os.environ, configured_env(), clear=True),
            patch.object(openai_client, "AsyncOpenAI", return_value=fake),
            patch(
                "dev_workflow_standards_tools.services.api_input_review.review_api_input",
                return_value={"passed": True},
            ),
        ):
            await openai_client.create_decision(
                [{"role": "user", "content": "{}"}], question
            )
        kwargs = fake.decisions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-6-luna")
        self.assertEqual(kwargs["questions"], question)
        self.assertEqual(set(kwargs), {"model", "input", "questions"})

    async def test_responses_parse_uses_effort_store_disabled_and_no_auto_truncation(
        self,
    ) -> None:
        fake = sdk_client()
        fake.responses.parse.return_value = SimpleNamespace(status="completed")
        schema = GeneratedContent
        with (
            patch.dict(os.environ, configured_env(), clear=True),
            patch.object(openai_client, "AsyncOpenAI", return_value=fake),
            patch(
                "dev_workflow_standards_tools.services.api_input_review.review_api_input",
                return_value={"passed": True},
            ),
        ):
            await openai_client.parse_response(
                instructions="fixed",
                input="{}",
                text_format=schema,
                reasoning_effort="medium",
                max_output_tokens=400,
            )
        kwargs = fake.responses.parse.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-6-luna")
        self.assertEqual(kwargs["reasoning"], {"effort": "medium"})
        self.assertFalse(kwargs["store"])
        self.assertEqual(kwargs["truncation"], "disabled")
        self.assertEqual(
            kwargs["text_format"].model_json_schema(), schema.model_json_schema()
        )
        self.assertNotIn("tools", kwargs)
        self.assertEqual(
            set(kwargs),
            {
                "model",
                "instructions",
                "input",
                "text_format",
                "reasoning",
                "store",
                "max_output_tokens",
                "truncation",
            },
        )


if __name__ == "__main__":
    unittest.main()
