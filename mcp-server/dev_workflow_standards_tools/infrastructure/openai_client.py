"""Explicit, fail-closed OpenAI SDK access for semantic workflow helpers."""

from __future__ import annotations

import json
import logging
import os
import traceback
from collections.abc import Callable
from typing import Any, TypeVar
from urllib.parse import urlsplit

import httpx2

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

from . import api_input_policy


MODEL_NAME = "gpt-6-luna"
OPENAI_TIMEOUT_SECONDS = 30.0
MAX_REQUEST_BYTES = 48 * 1024
T = TypeVar("T")
_LOG_REDACTION_MARKER = "[REDACTED]"


def _redact_log_text(value: str) -> str:
    """Redact current API and proxy settings without retaining them between records."""
    env_names = (
        "OPENAI_API_KEY", "OPENAI_BASE_URL",
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    )
    secrets: list[str] = [os.environ.get(name, "").strip() for name in env_names]
    proxy_names = (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
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
    for secret in secrets:
        if secret:
            value = value.replace(secret, _LOG_REDACTION_MARKER)
    return value


def _install_log_redaction() -> None:
    """Sanitize records at creation so child logger propagation cannot bypass redaction."""
    current_factory = logging.getLogRecordFactory()
    if getattr(current_factory, "_openai_config_redactor", False):
        return

    def redacting_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = current_factory(*args, **kwargs)
        try:
            record.msg = _redact_log_text(record.getMessage())
        except Exception:
            record.msg = _redact_log_text(str(record.msg))
        record.args = ()
        if record.exc_info:
            try:
                exception_text = "".join(traceback.format_exception(*record.exc_info))
                record.exc_text = _redact_log_text(exception_text)
            except Exception:
                record.exc_text = _LOG_REDACTION_MARKER
        elif record.exc_text:
            record.exc_text = _redact_log_text(record.exc_text)
        if record.stack_info:
            record.stack_info = _redact_log_text(record.stack_info)
        return record

    redacting_factory._openai_config_redactor = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(redacting_factory)


_install_log_redaction()


class OpenAIWorkflowError(Exception):
    """Sanitized API failure with no raw SDK exception or credential details."""

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
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        raise OpenAIWorkflowError("invalid_request_payload") from None


def _make_client(payload: Any) -> tuple[OpenAI, str, str]:
    api_key, base_url = _read_configuration()
    payload_text = _payload_text(payload)
    if len(payload_text.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise OpenAIWorkflowError("request_too_large")
    if api_key in payload_text or base_url in payload_text:
        raise OpenAIWorkflowError("sensitive_value_in_request")
    http_client: httpx2.Client | None = None
    try:
        http_client = httpx2.Client(trust_env=True)
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=OPENAI_TIMEOUT_SECONDS,
            max_retries=0,
            http_client=http_client,
        )
        return client, api_key, base_url
    except Exception:
        if http_client is not None:
            try:
                http_client.close()
            except Exception:
                pass
        raise OpenAIWorkflowError("client_initialization_failed") from None


def _safe_api_error(error: Exception, *, request_attempted: bool = False) -> OpenAIWorkflowError:
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


def _invoke(
    payload: Any,
    operation: Callable[[OpenAI], T],
    *,
    purpose: str = "Assess structured development workflow facts under the supplied policy question.",
    _skip_semantic_review: bool = False,
) -> T:
    payload_text = _payload_text(payload)
    if len(payload_text.encode("utf-8", errors="replace")) > MAX_REQUEST_BYTES:
        raise OpenAIWorkflowError("request_too_large")
    # Delayed import keeps the one-way service -> client dependency intact. The reviewer
    # uses this same boundary with a private recursion guard and cannot create a client itself.
    from ..services.api_input_review import review_api_input

    if not _skip_semantic_review:
        review = review_api_input(purpose, payload_text)
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
                    "status", "stage", "findings", "input_hash", "policy_version", "external_review_performed"
                )
                if key in review
            }
            api_status = review.get("api_status_code")
            raise OpenAIWorkflowError(
                error_code,
                api_status if isinstance(api_status, int) and not isinstance(api_status, bool) else None,
                api_input_review=details,
            )
    else:
        local = api_input_policy.inspect_api_input(purpose, payload_text)
        if not local["passed"]:
            blocked = review_api_input(purpose, payload_text)
            details = {
                key: blocked[key]
                for key in ("status", "stage", "findings", "input_hash", "policy_version", "external_review_performed")
                if key in blocked
            }
            raise OpenAIWorkflowError(
                blocked.get("error_code") or local.get("error_code") or "sensitive_input_detected",
                api_input_review=details,
            )
    client, api_key, base_url = _make_client(payload)
    request_attempted = False
    try:
        # From this point the SDK may have transmitted the request even when it later times out.
        request_attempted = True
        response = operation(client)
        response_text = _payload_text(response.model_dump(mode="json") if hasattr(response, "model_dump") else response)
        if api_key in response_text or base_url in response_text:
            raise OpenAIWorkflowError("sensitive_value_in_response")
        return response
    except OpenAIWorkflowError as error:
        if request_attempted and not error.request_attempted:
            raise OpenAIWorkflowError(
                error.error_code,
                error.status_code,
                request_attempted=True,
                api_input_review=error.api_input_review,
            ) from None
        raise
    except Exception as error:
        raise _safe_api_error(error, request_attempted=request_attempted) from None
    finally:
        try:
            client.close()
        except Exception:
            pass


def create_decision(
    input: list[dict[str, str]],
    questions: list[dict[str, Any]],
    *,
    purpose: str = "Assess structured development workflow facts under the supplied decision question.",
) -> Any:
    """Call the Decisions API without reasoning, store, or arbitrary option fields."""
    # Freeze one JSON-safe snapshot and send those exact copied values after the gate.
    payload = {
        "model": MODEL_NAME,
        "input": json.loads(_payload_text(input)),
        "questions": json.loads(_payload_text(questions)),
    }
    return _invoke(
        payload,
        lambda client: client.decisions.create(
            model=MODEL_NAME,
            input=payload["input"],
            questions=payload["questions"],
        ),
        purpose=purpose,
    )


def _create_policy_review_decision(*, purpose: str, content: str, questions: list[dict[str, Any]]) -> Any:
    """Private semantic-review path: same client/config/local gates, without recursive review."""
    payload = {
        "model": MODEL_NAME,
        "input": [{"role": "user", "content": content}],
        "questions": json.loads(_payload_text(questions)),
    }
    return _invoke(
        payload,
        lambda client: client.decisions.create(
            model=MODEL_NAME,
            input=payload["input"],
            questions=payload["questions"],
        ),
        purpose=purpose,
        _skip_semantic_review=True,
    )


def parse_response(
    *,
    instructions: str,
    input: str,
    text_format: type,
    reasoning_effort: str,
    max_output_tokens: int,
    purpose: str = "Generate a structured candidate from caller-provided source material.",
) -> Any:
    """Call Responses.parse with fixed model, explicit effort, and no storage/truncation."""
    if not hasattr(text_format, "model_json_schema"):
        raise OpenAIWorkflowError("invalid_response_schema")
    try:
        schema = json.loads(_payload_text(text_format.model_json_schema()))
        schema_snapshot = _payload_text(schema)
    except Exception:
        raise OpenAIWorkflowError("invalid_response_schema") from None

    def frozen_model_json_schema(cls: type, *args: Any, **kwargs: Any) -> dict[str, Any]:
        # The SDK's parse helper derives its strict wire schema from this method. Return a fresh
        # copy of the already checked snapshot so mutable class metadata cannot diverge mid-call.
        return json.loads(schema_snapshot)

    frozen_text_format = type(
        f"{text_format.__name__}OutboundSnapshot",
        (text_format,),
        {"model_json_schema": classmethod(frozen_model_json_schema)},
    )
    payload = {
        "model": MODEL_NAME,
        "instructions": str(instructions),
        "input": str(input),
        "text_format": schema,
        "reasoning": {"effort": str(reasoning_effort)},
        "store": False,
        "max_output_tokens": int(max_output_tokens),
        "truncation": "disabled",
    }
    return _invoke(
        payload,
        lambda client: client.responses.parse(
            model=MODEL_NAME,
            instructions=payload["instructions"],
            input=payload["input"],
            text_format=frozen_text_format,
            reasoning=payload["reasoning"],
            store=False,
            max_output_tokens=payload["max_output_tokens"],
            truncation="disabled",
        ),
        purpose=purpose,
    )
