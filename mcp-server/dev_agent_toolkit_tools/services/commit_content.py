"""Draft a commit message from the Git index without modifying it."""

from __future__ import annotations

import asyncio

from ..infrastructure.paths import _validated_repo_path
from . import ai_workflow
from .ai_workflow import ContentGenerationRequest
from .staged_commit import (
    StagedDiff,
    StagedDiffError,
    commit_snapshot,
    read_staged_diff,
)

_REQUEST = (
    "为当前整个暂存区起草一个简洁的提交标题，必要时附正文。证据覆盖各暂存文件和 hunk。改动行按 hunk 或按文件摘录。"
    "摘要只需说明证据支持的主要行为和范围。细节不够时概括到可证实的层级，省略次要实现、"
    "未验证的动机和测试运行结果。无需逐行审查、枚举每个文件或补齐可选正文。"
    "只有确实无法从证据判断主要变更时才记录必需的缺失事实。"
)


def _staged_request(staged: StagedDiff) -> ContentGenerationRequest:
    for compact, samples_by_budget in ((False, (5, 3, 2, 1, 0)), (True, (2, 1, 0))):
        for samples in samples_by_budget:
            evidence = staged.evidence(samples, compact=compact)
            if evidence is not None:
                request = ContentGenerationRequest(
                    kind="commit_message", user_request=_REQUEST, evidence=evidence
                )
                if ai_workflow.commit_request_fits(request):
                    return request
    raise StagedDiffError("staged_diff_too_large")


def _staged_error(code: str) -> dict:
    return {"ok": False, "adoptable": False, "error_code": code}


async def generate_from_staged_diff(repo_path: str) -> dict:
    try:
        root, _ = await asyncio.to_thread(_validated_repo_path, repo_path)
    except (OSError, UnicodeError):
        return _staged_error("staged_diff_unavailable")
    if root is None:
        return _staged_error("invalid_repo_path")
    try:
        staged = await read_staged_diff(root)
        snapshot = await asyncio.to_thread(commit_snapshot, root, staged.sha256)
        request = _staged_request(staged)
    except StagedDiffError as error:
        return _staged_error(str(error))

    result = await ai_workflow.generate_skill_content(request)
    if not result.get("ok"):
        return {**result, "adoptable": False}
    try:
        current = await read_staged_diff(root)
        current_snapshot = await asyncio.to_thread(
            commit_snapshot, root, current.sha256
        )
    except StagedDiffError as error:
        code = str(error)
        return _staged_error(
            "staged_diff_changed" if code == "no_staged_changes" else code
        )
    if current_snapshot != snapshot:
        return _staged_error("staged_diff_changed")

    candidate = result["candidate"]
    message = candidate["title"]
    if candidate["content"].strip():
        message += "\n\n" + candidate["content"]
    return {
        "ok": True,
        "adoptable": not candidate["missing_facts"],
        "message": message,
        "staged_paths": staged.paths,
        "staged_sha256": staged.sha256,
        "snapshot": snapshot.model_dump(),
        "missing_facts": candidate["missing_facts"],
        "review_notes": candidate["review_notes"],
        "requires_agent_review": True,
    }
