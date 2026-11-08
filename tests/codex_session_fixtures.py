from __future__ import annotations

import json
from pathlib import Path

from dev_workflow_standards_tools.services.codex_session_facts import (
    CodexSessionSource,
)

ROOT = Path(__file__).parents[1]

DOC = (
    ROOT / "skills" / "dev-workflow-standards" / "references" / "codex-session-facts.md"
)


def tool_json(result) -> dict:
    return json.loads(result.content[0].text)


def source(
    thread_id: str,
    *,
    created_at: str | None = "2026-01-01T00:00:00Z",
    ended_at: str | None = None,
    title: str | None = "示例 会话",
) -> CodexSessionSource:
    return CodexSessionSource(
        source_link=f"codex://threads/{thread_id}",
        created_at=created_at,
        ended_at=ended_at,
        title=title,
    )
