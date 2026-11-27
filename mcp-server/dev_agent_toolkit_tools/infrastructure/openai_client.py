"""统一的异步 OpenAI 请求边界，负责出站审核、配置读取、重试和脱敏。"""

from __future__ import annotations

import json
import logging
import os
import traceback
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypedDict, TypeVar, cast
from urllib.parse import urlsplit

import anyio
import httpx2
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import BaseModel

from . import api_input_policy

if TYPE_CHECKING:
    from openai.types import DecisionCreateParams
    from openai.types.responses import WebSearchToolParam
    from openai.types.responses.response_create_params import (
        ResponseCreateParamsNonStreaming,
    )
    from openai.types.shared_params import Reasoning, ReasoningEffort

GPT_SOL_MODEL = "gpt-6.2-sol"
GPT_TERRA_MODEL = "gpt-6.1-terra"
GPT_LUNA_MODEL = "gpt-6-luna"

DECISIONS_MODEL_NAME = GPT_LUNA_MODEL
RESPONSES_MODEL_NAME = GPT_SOL_MODEL
OPENAI_TIMEOUT_SECONDS = 180.0
DEFAULT_OPENAI_TIMEOUT_MAX_RETRIES = 5
MAX_REQUEST_BYTES = 48 * 1024
T = TypeVar("T")
_LOG_REDACTION_MARKER = "[REDACTED]"
CLIENT_CLEANUP_SECONDS = 5.0
# 每个任务独立保存进行中请求的脱敏值；配置轮换不应让旧请求的诊断泄漏。
_active_secrets: ContextVar[tuple[str, ...]] = ContextVar(
    "openai_active_secrets", default=()
)


class _StructuredResponsePayload(TypedDict):
    model: str
    instructions: str
    input: str
    text_format: dict[str, Any]
    reasoning: Reasoning
    store: Literal[False]
    max_output_tokens: int
    truncation: Literal["disabled"]


class _JsonModelDump(Protocol):
    def model_dump(self, *, mode: Literal["json"]) -> object: ...


def _configuration_secrets() -> tuple[str, ...]:
    """收集当前配置的脱敏值，仅在进行中的请求上下文中保留。"""
    env_names = (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    )
    secrets: list[str] = [os.environ.get(name, "").strip() for name in env_names]
    proxy_names = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    )
    for name in proxy_names:
        proxy = os.environ.get(name, "").strip()
        if not proxy:
            continue
        try:
            parsed_proxy = urlsplit(proxy if "://" in proxy else f"http://{proxy}")
            secrets.extend((parsed_proxy.hostname or "", str(parsed_proxy.port or "")))
            if parsed_proxy.username:
                secrets.append(parsed_proxy.username)
            if parsed_proxy.password:
                secrets.append(parsed_proxy.password)
        except ValueError:
            continue
    return tuple(secret for secret in secrets if secret)


def _redact_log_text(value: str) -> str:
    """同时覆盖当前环境和进行中请求使用的配置，防止轮换后泄漏旧值。"""
    secrets = set(_configuration_secrets()) | set(_active_secrets.get())
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            value = value.replace(secret, _LOG_REDACTION_MARKER)
    return value


def _install_log_redaction() -> None:
    """在 LogRecord 创建时脱敏，覆盖子 logger 向上级 handler 传播的日志。"""
    current_factory = logging.getLogRecordFactory()
    if getattr(current_factory, "_openai_config_redactor", False):
        return

    def redacting_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = current_factory(*args, **kwargs)
        try:
            record.msg = _redact_log_text(record.getMessage())
        except Exception:  # noqa: BLE001 -- 日志工厂内部不能再次写日志；任何格式化异常都必须转成脱敏内容。
            record.msg = _redact_log_text(str(record.msg))
        record.args = ()
        if record.exc_info:
            try:
                exception_text = "".join(traceback.format_exception(*record.exc_info))
                record.exc_text = _redact_log_text(exception_text)
            except Exception:  # noqa: BLE001 -- 日志工厂内部不能再次写日志；任何格式化异常都必须转成脱敏内容。
                record.exc_text = _LOG_REDACTION_MARKER
        elif record.exc_text:
            record.exc_text = _redact_log_text(record.exc_text)
        if record.stack_info:
            record.stack_info = _redact_log_text(record.stack_info)
        return record

    setattr(redacting_factory, "_openai_config_redactor", True)
    logging.setLogRecordFactory(redacting_factory)


_install_log_redaction()


class OpenAIWorkflowError(Exception):
    """仅携带安全错误分类和必要状态，不保留原始 SDK 异常或凭据。"""

    def __init__(
        self,
        error_code: str,
        status_code: int | None = None,
        *,
        request_attempted: bool = False,
        api_input_review: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.status_code = status_code
        self.request_attempted = request_attempted
        self.api_input_review = api_input_review

    def as_result(self) -> dict[str, Any]:
        result: dict[str, Any] = {"error_code": self.error_code}
        if self.status_code is not None:
            result["status_code"] = self.status_code
        if self.api_input_review is not None:
            result["api_input_review"] = self.api_input_review
        return result


def _read_configuration() -> tuple[str, str]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    if not api_key:
        raise OpenAIWorkflowError("missing_api_key")
    if not base_url:
        raise OpenAIWorkflowError("missing_base_url")
    try:
        parsed = urlsplit(base_url)
        _ = parsed.port
    except ValueError:
        raise OpenAIWorkflowError("invalid_base_url") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise OpenAIWorkflowError("invalid_base_url")
    return api_key, base_url


def _payload_text(payload: Any) -> str:
    try:
        return json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), default=str
        )
    except Exception:
        logging.getLogger(__name__).exception("invalid_request_payload", exc_info=False)
        raise OpenAIWorkflowError("invalid_request_payload") from None


def _read_timeout_max_retries() -> int:
    value = os.environ.get("OPENAI_TIMEOUT_MAX_RETRIES")
    if value is None:
        return DEFAULT_OPENAI_TIMEOUT_MAX_RETRIES
    value = value.strip()
    if not value or not value.isascii() or not value.isdecimal():
        raise OpenAIWorkflowError("invalid_timeout_max_retries")
    try:
        return int(value)
    except ValueError:
        raise OpenAIWorkflowError("invalid_timeout_max_retries") from None


async def _close_resource(close: Callable[[], Awaitable[None]]) -> None:
    """在取消屏蔽区等待清理，最长等待 CLIENT_CLEANUP_SECONDS。

    清理失败或超时只记录安全分类，不用清理错误覆盖原请求的结果或取消。
    """
    with anyio.move_on_after(CLIENT_CLEANUP_SECONDS, shield=True) as scope:
        try:
            await close()
        except Exception:
            logging.getLogger(__name__).exception(
                "OpenAI client cleanup failed", exc_info=False
            )
    if scope.cancel_called:
        logging.getLogger(__name__).warning("OpenAI client cleanup timed out")


async def _make_client(payload: Any) -> tuple[AsyncOpenAI, str, str]:
    """每次尝试重新读取环境配置，并独立创建 HTTP 与 SDK 客户端。

    配置或内容检查失败时不创建客户端；SDK 初始化失败时清理已创建的传输。
    """
    api_key, base_url = _read_configuration()
    payload_text = _payload_text(payload)
    if len(payload_text.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise OpenAIWorkflowError("request_too_large")
    if api_key in payload_text or base_url in payload_text:
        raise OpenAIWorkflowError("sensitive_value_in_request")
    http_client: httpx2.AsyncClient | None = None
    try:
        http_client = httpx2.AsyncClient(trust_env=True)
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=OPENAI_TIMEOUT_SECONDS,
            max_retries=0,
            http_client=http_client,
        )
        return client, api_key, base_url
    except Exception:
        logging.getLogger(__name__).exception(
            "client_initialization_failed", exc_info=False
        )
        if http_client is not None:
            await _close_resource(http_client.aclose)
        raise OpenAIWorkflowError("client_initialization_failed") from None


def _safe_api_error(
    error: Exception, *, request_attempted: bool = False
) -> OpenAIWorkflowError:
    if isinstance(error, AuthenticationError):
        code = "api_authentication_failed"
    elif isinstance(error, PermissionDeniedError):
        code = "api_permission_denied"
    elif isinstance(error, RateLimitError):
        code = "api_rate_limited"
    elif isinstance(error, APITimeoutError):
        code = "api_timeout"
    elif isinstance(error, APIConnectionError):
        code = "api_connection_failed"
    elif isinstance(error, APIStatusError):
        code = "api_status_error"
    else:
        code = "api_request_failed"
    status = getattr(error, "status_code", None)
    return OpenAIWorkflowError(
        code,
        status if isinstance(status, int) and not isinstance(status, bool) else None,
        request_attempted=request_attempted,
    )


async def _invoke(
    payload: Any,
    operation: Callable[[AsyncOpenAI], Awaitable[T]],
    *,
    purpose: str = "依据已提供的策略问题，评估结构化的开发工作流事实。",
    _skip_semantic_review: bool = False,
) -> T:
    """先审核出站快照，再执行该请求的超时重试和资源清理。

    私有审核请求只豁免递归语义审核，本地检测和配置约束仍然生效。
    """
    timeout_max_retries = _read_timeout_max_retries()
    payload_text = _payload_text(payload)
    if len(payload_text.encode("utf-8", errors="replace")) > MAX_REQUEST_BYTES:
        raise OpenAIWorkflowError("request_too_large")
    # 审核服务也使用本客户端；延迟导入避免初始化环，私有入口阻止递归审核。
    from ..services.api_input_review import review_api_input

    if not _skip_semantic_review:
        review = await review_api_input(purpose, payload_text)
        if review.get("passed") is not True:
            status = review.get("status")
            error_code = review.get("error_code") or {
                "blocked_local": "api_input_blocked_local",
                "needs_revision": "api_input_needs_revision",
                "insufficient_evidence": "api_input_insufficient_evidence",
                "unavailable": "api_input_review_unavailable",
            }.get(status, "api_input_review_unavailable")
            details = {
                key: review[key]
                for key in (
                    "status",
                    "stage",
                    "findings",
                    "input_hash",
                    "policy_version",
                    "external_review_performed",
                )
                if key in review
            }
            api_status = review.get("api_status_code")
            raise OpenAIWorkflowError(
                error_code,
                api_status
                if isinstance(api_status, int) and not isinstance(api_status, bool)
                else None,
                api_input_review=details,
            )
    else:
        local = api_input_policy.inspect_api_input(purpose, payload_text)
        if not local["passed"]:
            # 已知本地检查不通过；复用审核服务生成诊断，此分支不会发送审核请求。
            blocked = await review_api_input(purpose, payload_text)
            details = {
                key: blocked[key]
                for key in (
                    "status",
                    "stage",
                    "findings",
                    "input_hash",
                    "policy_version",
                    "external_review_performed",
                )
                if key in blocked
            }
            raise OpenAIWorkflowError(
                blocked.get("error_code")
                or local.get("error_code")
                or "sensitive_input_detected",
                api_input_review=details,
            )
    # 即使初值相同也保存 token，确保重试期间追加的脱敏值在本次调用结束后释放。
    token = _active_secrets.set(_active_secrets.get())
    try:
        return await _request_attempts(payload, operation, timeout_max_retries)
    finally:
        _active_secrets.reset(token)


async def _request_attempts(
    payload: Any,
    operation: Callable[[AsyncOpenAI], Awaitable[T]],
    timeout_max_retries: int,
) -> T:
    """仅重发已审核的请求快照；每次尝试重新读取配置并关闭独立客户端。

    只有 APITimeoutError 消耗重试预算，取消直接向上传播，仍执行 finally 清理。
    """
    request_attempted = False
    for attempt in range(timeout_max_retries + 1):
        try:
            _active_secrets.set(_active_secrets.get() + _configuration_secrets())
            client, api_key, base_url = await _make_client(payload)
        except OpenAIWorkflowError as error:
            if request_attempted:
                # 重新读取配置失败不代表之前的超时请求从未发送。
                error.request_attempted = True
            raise
        try:
            # 超时请求可能已到达服务端；不重跑外围审核、生成或质量审查。
            request_attempted = True
            response = await operation(client)
            response_text = _payload_text(
                cast(_JsonModelDump, response).model_dump(mode="json")
                if hasattr(response, "model_dump")
                else response
            )
            if api_key in response_text or base_url in response_text:
                raise OpenAIWorkflowError("sensitive_value_in_response")
            return response
        except APITimeoutError as error:
            if attempt == timeout_max_retries:
                raise _safe_api_error(error, request_attempted=True) from None
        except OpenAIWorkflowError as error:
            if not error.request_attempted:
                raise OpenAIWorkflowError(
                    error.error_code,
                    error.status_code,
                    request_attempted=True,
                    api_input_review=error.api_input_review,
                ) from None
            raise
        except Exception as error:
            logging.getLogger(__name__).exception(
                "unexpected_boundary_failure", exc_info=False
            )
            raise _safe_api_error(error, request_attempted=True) from None
        finally:
            await _close_resource(client.close)
    raise OpenAIWorkflowError("api_request_failed", request_attempted=request_attempted)


async def create_decision(
    input: list[dict[str, str]],
    questions: list[dict[str, Any]],
    *,
    purpose: str = "依据已提供的判断问题，评估结构化的开发工作流事实。",
) -> Any:
    """请求 Decisions 判断；仅发送固定模型、事实和问题，不添加不支持的选项。"""
    # 首次等待前复制输入；审核、发送和超时重试均使用同一份内容快照。
    payload: DecisionCreateParams = {
        "model": DECISIONS_MODEL_NAME,
        "input": json.loads(_payload_text(input)),
        "questions": json.loads(_payload_text(questions)),
    }
    return await _invoke(
        payload,
        lambda client: client.decisions.create(
            model=payload["model"],
            input=payload["input"],
            questions=payload["questions"],
        ),
        purpose=purpose,
    )


async def _create_policy_review_decision(
    *, purpose: str, content: str, questions: list[dict[str, Any]]
) -> Any:
    """审核专用私有入口：保留统一配置和本地检测，仅避免再次触发语义审核。"""
    payload: DecisionCreateParams = {
        "model": DECISIONS_MODEL_NAME,
        "input": [{"role": "user", "content": content}],
        "questions": json.loads(_payload_text(questions)),
    }
    return await _invoke(
        payload,
        lambda client: client.decisions.create(
            model=payload["model"],
            input=payload["input"],
            questions=payload["questions"],
        ),
        purpose=purpose,
        _skip_semantic_review=True,
    )


async def parse_response(
    *,
    instructions: str,
    input: str,
    text_format: type[BaseModel],
    reasoning_effort: str,
    max_output_tokens: int,
    purpose: str = "依据调用方提供的来源材料，生成结构化候选。",
) -> Any:
    """生成结构化候选，固定模型及推理强度，不存储响应或静默截断输入。

    JSON Schema 与正文一起冻结，确保 SDK 实际发送的结构与审核内容一致。
    """
    if not hasattr(text_format, "model_json_schema"):
        raise OpenAIWorkflowError("invalid_response_schema")
    try:
        schema = json.loads(_payload_text(text_format.model_json_schema()))
        schema_snapshot = _payload_text(schema)
    except Exception:
        logging.getLogger(__name__).exception("invalid_response_schema", exc_info=False)
        raise OpenAIWorkflowError("invalid_response_schema") from None

    def frozen_model_json_schema(
        cls: type, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        # SDK 从此方法生成出站 Schema；每次返回快照的副本，隔离调用期间的类元数据变化。
        return json.loads(schema_snapshot)

    frozen_text_format = type(
        f"{text_format.__name__}OutboundSnapshot",
        (text_format,),
        {"model_json_schema": classmethod(frozen_model_json_schema)},
    )
    payload: _StructuredResponsePayload = {
        "model": RESPONSES_MODEL_NAME,
        "instructions": str(instructions),
        "input": str(input),
        "text_format": schema,
        "reasoning": {"effort": cast("ReasoningEffort", str(reasoning_effort))},
        "store": False,
        "max_output_tokens": int(max_output_tokens),
        "truncation": "disabled",
    }
    return await _invoke(
        payload,
        lambda client: client.responses.parse(
            model=payload["model"],
            instructions=payload["instructions"],
            input=payload["input"],
            text_format=frozen_text_format,
            reasoning=payload["reasoning"],
            store=payload["store"],
            max_output_tokens=payload["max_output_tokens"],
            truncation=payload["truncation"],
        ),
        purpose=purpose,
    )


async def create_web_search_response(
    *, instructions: str, input: str, allowed_domains: list[str], reasoning_effort: str
) -> Any:
    """通过统一审核与重试边界执行搜索，不接受任意工具或模型覆盖。"""
    budgets = {"low": 4096, "medium": 8192, "high": 16384}
    if reasoning_effort not in budgets:
        raise OpenAIWorkflowError("invalid_search_effort")
    search_tool: WebSearchToolParam = {
        "type": "web_search",
        "external_web_access": True,
        "search_context_size": "medium",
    }
    if allowed_domains:
        search_tool["filters"] = {"allowed_domains": list(allowed_domains)}
    payload: ResponseCreateParamsNonStreaming = {
        "model": RESPONSES_MODEL_NAME,
        "instructions": str(instructions),
        "input": str(input),
        "tools": [search_tool],
        "tool_choice": "required",
        "include": ["web_search_call.action.sources"],
        "reasoning": {"effort": cast("ReasoningEffort", reasoning_effort)},
        "max_output_tokens": budgets[reasoning_effort],
        "store": False,
        "truncation": "disabled",
    }
    # 审核、实际发送和重试共享同一快照，避免等待期间调用者修改域名列表。
    return await _invoke(
        payload,
        lambda client: client.responses.create(**payload),
        purpose="根据公开查询执行联网搜索，返回有来源支撑的摘要和引用。",
    )
