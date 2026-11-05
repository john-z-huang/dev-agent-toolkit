"""Local, deterministic checks for data before it reaches the OpenAI client."""

from __future__ import annotations

import base64
import binascii
import os
import re
from typing import Any


POLICY_VERSION = "2026-11-05.1"
MAX_FIELD_BYTES = 32 * 1024
MAX_FINDINGS = 20
MAX_DECODE_BYTES = 8 * 1024

_TOKEN_VALUE = r"[A-Za-z0-9._~+/=-]{12,}"
_PLACEHOLDERS = {
    "placeholder", "redacted", "example", "sample", "changeme",
    "token_here", "replace_me", "dummy", "not_a_real_token",
}
_ENVIRONMENT_REFERENCE = re.compile(
    r"^(?:OPENAI_API_KEY|OPENAI_BASE_URL|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*(?:_API_KEY|_TOKEN|_SECRET))$"
)

_CREDENTIAL_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("credential.api_key", "credential", re.compile(r"\b(?:sk-(?:proj-|org-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})\b")),
    ("credential.bearer", "credential", re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._~+/=-]{12,})")),
    ("credential.basic_authorization", "credential", re.compile(r"(?i)\bAuthorization\s*:\s*Basic\s+([A-Za-z0-9+/=_-]{8,})")),
    ("credential.jwt", "credential", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("credential.url_query", "credential", re.compile(r"(?i)\b(?:https?|ftp)://[^\s/?#]+(?:/[^\s?#]*)?[?&](?:api[-_]?key|token|access[-_]?token|refresh[-_]?token|auth[-_]?token|session(?:id)?|password)=([^&#\s]{8,})")),
    ("credential.session_cookie", "credential", re.compile(rf"(?i)\b(?:session(?:id)?|auth(?:entication)?[-_]?token|sid|csrf[-_]?token)\s*=\s*[\"']?({_TOKEN_VALUE})")),
    ("credential.cookie_header", "credential", re.compile(rf"(?im)^\s*(?:cookie|set-cookie)\s*:\s*[^\r\n]*?(?:session|auth|token|sid)[-_a-z0-9]*\s*=\s*[\"']?({_TOKEN_VALUE})")),
    (
        "credential.assignment",
        "credential",
        re.compile(
            r"(?i)\b(?:[A-Za-z0-9]+[_-])*(?:api[-_ ]?key|token|password|passwd|secret)"
            r"\b\\?[\"']?\s*[:=]\s*\\?[\"']?([^\s,;\]}\"']+)"
        ),
    ),
    ("credential.private_key", "credential", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("credential.auth_url", "credential", re.compile(r"(?i)\b(?:https?|ftp)://[^\s/@]+@[^\s/]+")),
)

_LOCAL_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bfile://(?:localhost)?/(?:Users|home|private|tmp|var|etc|opt|Volumes|root|mnt|workspace|Library|Applications)/[^\s\"'<>]+"),
    re.compile(r"(?<![A-Za-z0-9])/(?:Users|home|private|tmp|var|etc|opt|Volumes|root|mnt|workspace|srv|Library|Applications)/[^\s\"'<>]+"),
    re.compile(r"(?<![A-Za-z0-9/])[A-Za-z]:(?:\\\\|\\|/)(?!/)(?:[^\\/\s:*?\"<>|]+(?:\\\\|\\|/))*[^\\/\s:*?\"<>|]+"),
    re.compile(r"(?:\\\\){1,2}[A-Za-z0-9._-]+(?:\\\\|\\)[^\s\"'<>]+"),
)
_SERIALIZED_CONTROL_ESCAPE_PREFIX = re.compile(r"^\\{2,}(?P<escape>[nrtbf]|u[0-9a-f]{4})", re.IGNORECASE)


def _looks_like_serialized_control_escape(value: str, start: int) -> bool:
    prefix = value[start:]
    marker = _SERIALIZED_CONTROL_ESCAPE_PREFIX.match(prefix)
    if marker is None:
        return False
    tail = prefix[marker.end():]
    slash_count = len(tail) - len(tail.lstrip("\\"))
    remainder = tail[slash_count:]
    repeated_escape = re.match(r"(?:[nrtbf]|u[0-9a-f]{4})", remainder, re.IGNORECASE)
    if repeated_escape is not None and repeated_escape.group(0).casefold() == marker.group("escape").casefold():
        return True
    # A JSON-escaped quote following a control escape has an odd backslash run;
    # a serialized UNC separator has an even run because each path slash is escaped.
    return slash_count > 0 and slash_count % 2 == 1 and remainder.startswith(('"', "'", ",", ":", "}", "]"))

_ENCODED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(?:base64(?:url)?|encoded|ciphertext|opaque[_ -]?payload)\s*[:=]\s*[\"']?([A-Za-z0-9+/=_-]{32,})"),
    re.compile(r"(?i)\bdata:[^,;\s]+(?:;[^,;\s]+)*;base64,([A-Za-z0-9+/=]{40,})"),
)


def _is_placeholder(value: str) -> bool:
    normalized = value.strip(" ._-/=\"'\\<>").casefold()
    return normalized in _PLACEHOLDERS or bool(_ENVIRONMENT_REFERENCE.fullmatch(normalized.upper()))


def _inside_public_url(value: str, start: int) -> bool:
    prefix = value[:start]
    scheme_start = max(prefix.rfind("https://"), prefix.rfind("http://"), prefix.rfind("ftp://"))
    if scheme_start < 0:
        return False
    url_start = max(prefix.rfind(" "), prefix.rfind("\n"), prefix.rfind("\t"), prefix.rfind('"'), prefix.rfind("'")) + 1
    if scheme_start < url_start:
        return False
    # A path in a query value is still data being sent; ignore only a URL's ordinary route path.
    query_start = value.find("?", scheme_start, start)
    fragment_start = value.find("#", scheme_start, start)
    return query_start < 0 and fragment_start < 0


def _append_finding(
    findings: list[dict[str, Any]],
    *,
    field: str,
    start: int,
    end: int,
    rule_id: str,
    category: str,
) -> None:
    if len(findings) >= MAX_FINDINGS:
        return
    key = (field, start, end, rule_id)
    if any((item["field"], item["start"], item["end"], item["rule_id"]) == key for item in findings):
        return
    findings.append({
        "field": field,
        "start": start,
        "end": end,
        "rule_id": rule_id,
        "category": category,
    })


def _configured_values() -> tuple[str, ...]:
    """Read only the two explicitly configured values needed for exact-match blocking."""
    return tuple(value for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL") if (value := os.environ.get(name, "").strip()))


def inspect_api_input(purpose: Any, content: Any) -> dict[str, Any]:
    """Inspect two fields locally; findings contain positions and rule IDs, never source text."""
    findings: list[dict[str, Any]] = []
    values = (("purpose", purpose), ("content", content))
    invalid = False
    for field, value in values:
        if not isinstance(value, str) or not value.strip():
            invalid = True
            _append_finding(findings, field=field, start=0, end=0, rule_id="input.required_nonblank", category="invalid_input")
            continue
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            invalid = True
            _append_finding(findings, field=field, start=0, end=0, rule_id="input.invalid_unicode", category="invalid_input")
            continue
        if len(value) > MAX_FIELD_BYTES or len(encoded) > MAX_FIELD_BYTES:
            _append_finding(findings, field=field, start=0, end=len(value), rule_id="input.field_too_large", category="size_limit")
            continue

        for secret in _configured_values():
            start = value.find(secret)
            while start >= 0:
                _append_finding(findings, field=field, start=start, end=start + len(secret), rule_id="credential.exact_configuration", category="credential")
                start = value.find(secret, start + max(1, len(secret)))

        for rule_id, category, pattern in _CREDENTIAL_PATTERNS:
            for match in pattern.finditer(value):
                candidate = match.group(1) if match.lastindex else match.group(0)
                if _is_placeholder(candidate):
                    continue
                _append_finding(findings, field=field, start=match.start(), end=match.end(), rule_id=rule_id, category=category)

        for pattern in _LOCAL_PATH_PATTERNS:
            for match in pattern.finditer(value):
                if _inside_public_url(value, match.start()):
                    continue
                # Multiple JSON serializations turn newline escapes into `\\n`. Those
                # sequences can resemble a UNC host/share pair; they are not filesystem paths.
                if _looks_like_serialized_control_escape(value, match.start()):
                    continue
                _append_finding(findings, field=field, start=match.start(), end=match.end(), rule_id="path.absolute_local", category="local_path")

        for pattern in _ENCODED_PATTERNS:
            for match in pattern.finditer(value):
                blob = match.group(1)
                # Bound both encoded and decoded work; opaque labeled data is rejected even when
                # it cannot be decoded, while decoded text is checked for obvious nested markers.
                if len(blob) > 4 * MAX_DECODE_BYTES:
                    _append_finding(findings, field=field, start=match.start(), end=match.end(), rule_id="opaque.encoding_too_large", category="opaque_or_encoded")
                    continue
                _append_finding(findings, field=field, start=match.start(), end=match.end(), rule_id="opaque.encoded_payload", category="opaque_or_encoded")
                try:
                    decoded = base64.b64decode(blob[: 4 * MAX_DECODE_BYTES], validate=False)[:MAX_DECODE_BYTES]
                except (binascii.Error, ValueError):
                    decoded = b""
                if decoded:
                    try:
                        decoded_text = decoded.decode("utf-8", errors="strict")
                    except UnicodeDecodeError:
                        decoded_text = ""
                    if decoded_text:
                        for rule_id, category, nested_pattern in _CREDENTIAL_PATTERNS:
                            if nested_pattern.search(decoded_text):
                                _append_finding(findings, field=field, start=match.start(), end=match.end(), rule_id=f"{rule_id}.inside_encoding", category=category)
                                break

    has_size_finding = any(item["category"] == "size_limit" for item in findings)
    has_sensitive_finding = any(item["category"] in {"credential", "local_path", "opaque_or_encoded"} for item in findings)
    return {
        "passed": not findings and not invalid,
        "findings": findings,
        "error_code": "invalid_input" if invalid else ("request_too_large" if has_size_finding else ("sensitive_input_detected" if has_sensitive_finding else None)),
    }
