"""显式启用的独立进程冒烟入口，复用统一 OpenAI 客户端及其安全约束。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any, Literal

from dev_workflow_standards_tools.infrastructure.openai_client import (
    MODEL_NAME,
    OpenAIWorkflowError,
    parse_response,
)
from pydantic import BaseModel, ConfigDict

OFFICIAL_API_KEY_ENV = "OPENAI_API_KEY_OFFICAL"
OFFICIAL_BASE_URL_ENV = "OPENAI_BASE_URL_OFFICAL"


class SmokeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: Literal[True]


def _usage_counts(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    counts: dict[str, int] = {}
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        value = getattr(usage, name, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            counts[name] = value
    return counts


def _has_refusal(response: Any) -> bool:
    if getattr(response, "refusal", None):
        return True
    for item in getattr(response, "output", ()) or ():
        if getattr(item, "type", None) == "refusal":
            return True
        for content in getattr(item, "content", ()) or ():
            if getattr(content, "type", None) == "refusal":
                return True
    return False


def _failure(error_code: str, status_code: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "failed",
        "model": MODEL_NAME,
        "error_code": error_code,
    }
    if (
        isinstance(status_code, int)
        and not isinstance(status_code, bool)
        and 100 <= status_code <= 599
    ):
        result["status_code"] = status_code
    return result


def _official_response_error(response: Any) -> str | None:
    """官方连通性结果必须同时满足完成状态、唯一模型和严格布尔输出。"""
    if getattr(response, "status", None) != "completed":
        return "response_not_completed"
    if _has_refusal(response):
        return "response_refused"
    if getattr(response, "model", None) != MODEL_NAME:
        return "unexpected_model"
    parsed = getattr(response, "output_parsed", None)
    if not isinstance(parsed, SmokeOutput) or parsed.model_dump(mode="json") != {
        "ok": True
    }:
        return "invalid_output"
    return None


async def _call_live() -> dict[str, Any]:
    """在独立测试入口临时映射官方配置，等待请求后恢复原环境。"""
    api_key = os.environ.get(OFFICIAL_API_KEY_ENV, "").strip()
    base_url = os.environ.get(OFFICIAL_BASE_URL_ENV, "").strip()
    if not api_key:
        return _failure("missing_official_api_key")
    if not base_url:
        return _failure("missing_official_base_url")

    previous_key = os.environ.get("OPENAI_API_KEY")
    previous_url = os.environ.get("OPENAI_BASE_URL")
    os.environ["OPENAI_API_KEY"] = api_key
    os.environ["OPENAI_BASE_URL"] = base_url
    try:
        response = await parse_response(
            instructions="Return the required JSON object with ok set to true.",
            input="This is a connectivity smoke check. Return only the requested boolean field.",
            text_format=SmokeOutput,
            reasoning_effort="medium",
            max_output_tokens=512,
        )
    except OpenAIWorkflowError as error:
        return _failure(error.error_code, error.status_code)
    except Exception:
        logging.getLogger(__name__).exception("api_request_failed", exc_info=False)
        return _failure("api_request_failed")
    finally:
        if previous_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = previous_key
        if previous_url is None:
            os.environ.pop("OPENAI_BASE_URL", None)
        else:
            os.environ["OPENAI_BASE_URL"] = previous_url

    response_error = _official_response_error(response)
    if response_error:
        return _failure(response_error)
    return {"status": "success", "model": MODEL_NAME, "usage": _usage_counts(response)}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["--live"]:
        status = "skipped" if not args else "failed"
        result = {"status": status, "model": MODEL_NAME}
        if status == "failed":
            result["error_code"] = "invalid_arguments"
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 2 if status != "success" else 0
    # 事件循环只在脚本边界创建；生产 MCP 服务不调用此入口或修改全局环境。
    result = asyncio.run(_call_live())
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
