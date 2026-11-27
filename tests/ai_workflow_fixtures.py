from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from dev_agent_toolkit_tools.services.ai_workflow import (
    ContentQualityReview,
    GeneratedContent,
)

API_KEY_A = "sk-test-key-value-aaaaaaaaaaaaaaaa"


API_KEY_B = "sk-test-key-value-bbbbbbbbbbbbbbbb"


BASE_URL_A = "https://api-a.example.invalid/v1"


BASE_URL_B = "https://api-b.example.invalid/v1"


THREAD = "00000000-0000-4000-8000-000000000011"


def choice_answer(name: str, choice: str, values: tuple[str, ...]) -> SimpleNamespace:
    return SimpleNamespace(
        type="choice",
        name=name,
        choice=choice,
        confidence=0.71,
        probabilities=[
            SimpleNamespace(value=value, probability=1 / len(values))
            for value in values
        ],
    )


def decision_response(*answers: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(answers=list(answers), refusal=None)


def configured_env(**overrides: str) -> dict[str, str]:
    return {"OPENAI_API_KEY": API_KEY_A, "OPENAI_BASE_URL": BASE_URL_A, **overrides}


def sdk_client() -> Mock:
    """构造网络方法和 close 可等待的 SDK 替身，客户端构造本身仍为同步。"""
    client = Mock()
    client.decisions.create = AsyncMock()
    client.responses.parse = AsyncMock()
    client.close = AsyncMock()
    return client


class ContentGenerationTestCase(unittest.IsolatedAsyncioTestCase):
    """提供结构化候选和质量审查响应，不执行被测行为。"""

    def _review(self, **changes) -> ContentQualityReview:
        return ContentQualityReview(
            **{
                "language_compliant": True,
                "evidence_supported": True,
                "coverage_sufficient": True,
                "missing_facts": [],
                "review_notes": [],
                **changes,
            }
        )

    def _generated(self, refs: list[str] | None = None) -> GeneratedContent:
        return GeneratedContent(
            title="候选标题",
            content="候选正文。",
            used_evidence_refs=refs or [],
            missing_facts=["缺少结果证据"],
            review_notes=["需Agent核对"],
        )

    def _completed(
        self,
        parsed: GeneratedContent | None,
        *,
        status: str = "completed",
        refusal: bool = False,
    ):
        content = [SimpleNamespace(type="refusal", refusal="no")] if refusal else []
        return SimpleNamespace(
            status=status,
            output_parsed=parsed,
            output=[SimpleNamespace(content=content)] if content else [],
            usage=SimpleNamespace(
                input_tokens=10, output_tokens=20, total_tokens=30, secret="ignored"
            ),
        )
