from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import BaseModel

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "tests" / "openai_official_smoke.py"
SPEC = importlib.util.spec_from_file_location("openai_official_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = smoke
SPEC.loader.exec_module(smoke)


TEST_KEY = "sk-test-official-key-value"
TEST_BASE_URL = "https://official.synthetic.invalid/v1"
TEST_PROXY = "http://proxy-user:proxy-pass@proxy.synthetic.invalid:8123"


def parsed_response(
    *,
    status: str = "completed",
    model: str = "gpt-6-luna",
    output_parsed: object | None = None,
    refusal: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        model=model,
        output_parsed=output_parsed or smoke.SmokeOutput(ok=True),
        refusal=refusal,
        output=[],
        usage=SimpleNamespace(input_tokens=12, output_tokens=4, total_tokens=16),
    )


class OfficialSmokeTests(unittest.TestCase):
    def official_env(self, **extra: str) -> dict[str, str]:
        return {
            smoke.OFFICIAL_API_KEY_ENV: TEST_KEY,
            smoke.OFFICIAL_BASE_URL_ENV: TEST_BASE_URL,
            **extra,
        }

    def invoke(
        self, response: object | None = None
    ) -> tuple[int, dict[str, object], str]:
        captured: list[str] = []

        def output(value: str) -> None:
            captured.append(value)

        with patch("builtins.print", side_effect=output):
            code = smoke.main(["--live"])
        result = json.loads(captured[0])
        return code, result, captured[0]

    def test_default_invocation_skips_without_calling_parse_response(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(smoke, "parse_response") as parse,
        ):
            output: list[str] = []
            with patch("builtins.print", side_effect=output.append):
                code = smoke.main([])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output[0])["status"], "skipped")
        parse.assert_not_called()

    def test_missing_official_values_never_fall_back_to_standard_values(self) -> None:
        for missing_name in (smoke.OFFICIAL_API_KEY_ENV, smoke.OFFICIAL_BASE_URL_ENV):
            env = {
                "OPENAI_API_KEY": TEST_KEY,
                "OPENAI_BASE_URL": TEST_BASE_URL,
                smoke.OFFICIAL_API_KEY_ENV: TEST_KEY,
                smoke.OFFICIAL_BASE_URL_ENV: TEST_BASE_URL,
            }
            env.pop(missing_name)
            with (
                self.subTest(missing=missing_name),
                patch.dict(os.environ, env, clear=True),
                patch.object(smoke, "parse_response") as parse,
            ):
                code, result, _ = self.invoke()
            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "failed")
            expected = (
                "missing_official_api_key"
                if missing_name == smoke.OFFICIAL_API_KEY_ENV
                else "missing_official_base_url"
            )
            self.assertEqual(result["error_code"], expected)
            parse.assert_not_called()

    def test_blank_official_values_never_fall_back_to_standard_values(self) -> None:
        for name in (smoke.OFFICIAL_API_KEY_ENV, smoke.OFFICIAL_BASE_URL_ENV):
            env = self.official_env(
                **{
                    name: "   ",
                    "OPENAI_API_KEY": TEST_KEY,
                    "OPENAI_BASE_URL": TEST_BASE_URL,
                }
            )
            with (
                self.subTest(name=name),
                patch.dict(os.environ, env, clear=True),
                patch.object(smoke, "parse_response") as parse,
            ):
                code, result, _ = self.invoke()
            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "failed")
            parse.assert_not_called()

    def test_reads_current_values_and_restores_standard_environment(self) -> None:
        observations: list[tuple[str, str]] = []

        def parse(**kwargs: object) -> SimpleNamespace:
            observations.append(
                (os.environ["OPENAI_API_KEY"], os.environ["OPENAI_BASE_URL"])
            )
            self.assertEqual(kwargs["text_format"], smoke.SmokeOutput)
            self.assertEqual(kwargs["reasoning_effort"], "medium")
            self.assertEqual(kwargs["max_output_tokens"], 512)
            self.assertEqual(
                kwargs["instructions"], "返回所要求的 JSON 对象，将 ok 设置为 true。"
            )
            self.assertEqual(
                kwargs["input"], "这是连通性冒烟检查。只返回请求指定的布尔字段。"
            )
            self.assertNotIn("model", kwargs)
            return parsed_response()

        first_env = self.official_env(
            OPENAI_API_KEY="old-standard-key",
            OPENAI_BASE_URL="https://old.synthetic.invalid/v1",
        )
        with (
            patch.dict(os.environ, first_env, clear=True),
            patch.object(smoke, "parse_response", side_effect=parse) as parse_mock,
        ):
            first = self.invoke()
            os.environ[smoke.OFFICIAL_API_KEY_ENV] = "sk-test-second-key"
            os.environ[smoke.OFFICIAL_BASE_URL_ENV] = (
                "https://second.synthetic.invalid/v1"
            )
            second = self.invoke()
            self.assertEqual(os.environ["OPENAI_API_KEY"], "old-standard-key")
            self.assertEqual(
                os.environ["OPENAI_BASE_URL"], "https://old.synthetic.invalid/v1"
            )
        self.assertEqual(first[0], 0)
        self.assertEqual(second[0], 0)
        self.assertEqual(
            observations,
            [
                (TEST_KEY, TEST_BASE_URL),
                ("sk-test-second-key", "https://second.synthetic.invalid/v1"),
            ],
        )
        self.assertEqual(parse_mock.call_count, 2)
        self.assertEqual(first[1]["model"], "gpt-6-luna")
        self.assertEqual(
            first[1]["usage"],
            {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
        )
        self.assertNotIn(TEST_KEY, first[2])
        self.assertNotIn(TEST_BASE_URL, first[2])

    def test_environment_is_restored_when_parse_raises(self) -> None:
        env = self.official_env(
            OPENAI_API_KEY="existing-key",
            OPENAI_BASE_URL="https://existing.synthetic.invalid/v1",
        )
        error = RuntimeError(f"raw failure {TEST_KEY} {TEST_BASE_URL} {TEST_PROXY}")
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(smoke, "parse_response", side_effect=error),
        ):
            code, result, output = self.invoke()
            self.assertEqual(os.environ["OPENAI_API_KEY"], "existing-key")
            self.assertEqual(
                os.environ["OPENAI_BASE_URL"], "https://existing.synthetic.invalid/v1"
            )
        self.assertEqual(code, 1)
        self.assertEqual(result["error_code"], "api_request_failed")
        for secret in (TEST_KEY, TEST_BASE_URL, TEST_PROXY, "raw failure"):
            self.assertNotIn(secret, output)

    def test_missing_standard_environment_is_removed_after_call(self) -> None:
        with (
            patch.dict(os.environ, self.official_env(), clear=True),
            patch.object(smoke, "parse_response", return_value=parsed_response()),
        ):
            code, _, _ = self.invoke()
            self.assertNotIn("OPENAI_API_KEY", os.environ)
            self.assertNotIn("OPENAI_BASE_URL", os.environ)
        self.assertEqual(code, 0)

    def test_incomplete_refusal_wrong_model_and_invalid_schema_fail_closed(
        self,
    ) -> None:
        class WrongSmokeOutput(BaseModel):
            ok: bool

        cases = (
            (parsed_response(status="incomplete"), "response_not_completed"),
            (parsed_response(refusal="synthetic refusal"), "response_refused"),
            (parsed_response(model="gpt-6-luna-snapshot"), "unexpected_model"),
            (
                parsed_response(output_parsed=WrongSmokeOutput(ok=True)),
                "invalid_output",
            ),
            (
                SimpleNamespace(
                    status="completed",
                    model="gpt-6-luna",
                    refusal=None,
                    output=[],
                    output_parsed=None,
                ),
                "invalid_output",
            ),
        )
        for response, error_code in cases:
            with (
                self.subTest(error_code=error_code),
                patch.dict(os.environ, self.official_env(), clear=True),
                patch.object(smoke, "parse_response", return_value=response),
            ):
                code, result, _ = self.invoke()
            self.assertEqual(code, 1)
            self.assertEqual(result["error_code"], error_code)

    def test_safe_errors_include_only_classification_and_valid_http_status(
        self,
    ) -> None:
        env = self.official_env()
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(
                smoke,
                "parse_response",
                side_effect=smoke.OpenAIWorkflowError("api_status_error", 502),
            ),
        ):
            code, result, output = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(result["error_code"], "api_status_error")
        self.assertEqual(result["status_code"], 502)
        for secret in (TEST_KEY, TEST_BASE_URL, TEST_PROXY):
            self.assertNotIn(secret, output)

    def test_unexpected_arguments_do_not_make_a_request(self) -> None:
        with (
            patch.object(smoke, "parse_response") as parse,
            patch("builtins.print") as output,
        ):
            code = smoke.main(["--live", "--base-url", TEST_BASE_URL])
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(output.call_args.args[0])["error_code"], "invalid_arguments"
        )
        parse.assert_not_called()


if __name__ == "__main__":
    unittest.main()
