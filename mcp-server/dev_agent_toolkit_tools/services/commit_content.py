"""Commit-specific input and presentation over the shared content generator."""

from __future__ import annotations

import asyncio

from pydantic import Field, model_validator

from ..infrastructure.paths import _validated_repo_path
from . import ai_workflow
from .ai_workflow import ContentGenerationRequest, EvidenceItem, StrictInput
from .staged_commit import StagedDiffError, read_staged_diff


class CommitMessageRequest(StrictInput):
    user_request: str = Field(
        min_length=1,
        max_length=12000,
        description="本次提交目标、原因、关注点；不是已完成事实或提交授权。用户已有完整message时直接检查原文，不要求重写。",
    )
    evidence: list[EvidenceItem] = Field(
        min_length=1,
        max_length=100,
        description="本次选定提交的全部patch/hunk、准确路径及前后行为/原因的有界事实摘要和来源指针；ref唯一。已暂存时以实际cached diff为准；未暂存时明确拟提交范围。不要用整个PR、未选中改动或最后一次历史commit代替。不传全仓库/会话或凭据；未运行测试如实标注。工具不会读取Git。",
    )
    focus_questions: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description="可选1–20个非空关注问题，优先默认重点；省略/null用默认，不增加事实。",
    )
    output_format: str | None = Field(
        default=None,
        min_length=1,
        max_length=12000,
        description="可选非空正文结构，省略/null使用默认。不能覆盖完整中文标题、允许type、证据或禁止署名规则；正文可以为空。",
    )

    @model_validator(mode="after")
    def validate_shared_contract(self):
        ContentGenerationRequest(kind="commit_message", **self.model_dump())
        return self


async def generate_git_commit_message(request: CommitMessageRequest) -> dict:
    """Generate, never commit; all model calls and validation stay on the shared path."""
    request = CommitMessageRequest.model_validate(request).model_copy(deep=True)
    result = await ai_workflow.generate_skill_content(
        ContentGenerationRequest(kind="commit_message", **request.model_dump())
    )
    if result.get("ok") is not True:
        return {**result, "adoptable": False}
    candidate = result["candidate"]
    message = candidate["title"]
    if candidate["content"].strip():
        message += "\n\n" + candidate["content"]
    return {
        **result,
        "message": message,
        "adoptable": not candidate["missing_facts"],
        "validation_scope": "local_format_and_attribution",
        "requires_agent_review": True,
    }


def _staged_error(code: str) -> dict:
    return {"ok": False, "adoptable": False, "error_code": code}


async def generate_from_staged_diff(repo_path: str, verification: str | None) -> dict:
    try:
        root, _ = await asyncio.to_thread(_validated_repo_path, repo_path)
    except (OSError, UnicodeError):
        return _staged_error("staged_diff_unavailable")
    if root is None:
        return _staged_error("invalid_repo_path")
    try:
        staged = await read_staged_diff(root)
    except StagedDiffError as error:
        return _staged_error(str(error))

    evidence = list(staged.evidence)
    if verification and verification.strip():
        evidence.append(
            EvidenceItem(
                reference_id="V1",
                origin="user_provided",
                content=f"调用方报告的实际验证结果：{verification.strip()}",
            )
        )
    result = await generate_git_commit_message(
        CommitMessageRequest(
            user_request=(
                "依据 staged diff 的路径、各 hunk 范围和变更行摘录，为整个暂存区起草单个提交。"
                "摘录只支持可直接核对的主张；未提供验证结果时省略测试事实，有重要缺口时明确列出。"
            ),
            evidence=evidence,
        )
    )
    if not result.get("ok"):
        return result
    try:
        current = await read_staged_diff(root)
    except StagedDiffError as error:
        code = str(error)
        return _staged_error(
            "staged_diff_changed" if code == "no_staged_changes" else code
        )
    if current.sha256 != staged.sha256:
        return _staged_error("staged_diff_changed")

    candidate = result["candidate"]
    return {
        "ok": True,
        "adoptable": result["adoptable"],
        "message": result["message"],
        "staged_paths": staged.paths,
        "staged_sha256": staged.sha256,
        "missing_facts": candidate["missing_facts"],
        "review_notes": candidate["review_notes"],
        "requires_agent_review": True,
    }
