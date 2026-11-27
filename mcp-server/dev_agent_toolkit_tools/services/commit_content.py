"""Commit-specific input and presentation over the shared content generator."""

from __future__ import annotations

from pydantic import Field, model_validator

from . import ai_workflow
from .ai_workflow import ContentGenerationRequest, EvidenceItem, StrictInput


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
