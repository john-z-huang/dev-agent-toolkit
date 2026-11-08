"""语义判断、候选生成和输入审核的异步 MCP 入口，不负责流程调度。"""

from __future__ import annotations

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from ..services import ai_workflow, api_input_review
from ..services.ai_workflow import (
    ContentGenerationRequest,
    SessionDecisionRequest,
)
from ..services.api_input_review import ApiInputReviewRequest
from ._registration import _register_adapter


async def decide_codex_session_action(request: SessionDecisionRequest) -> dict:
    """返回历史查询和持久化动作建议；不读取会话或写入 Serena Memory。"""
    return await ai_workflow.decide_codex_session_action(request)


async def generate_skill_content(request: ContentGenerationRequest) -> dict:
    """生成候选内容供 Agent 审阅；不会执行代码或外部操作。"""
    return await ai_workflow.generate_skill_content(request)


async def check_api_input(request: ApiInputReviewRequest) -> dict:
    """审核完整 purpose 与 content；不代发业务请求或授予其他操作权限。"""
    return await api_input_review.check_api_input(request)


def register_ai_workflow_tools(server: MCPServer) -> None:
    """注册只读但会访问外部 OpenAI API 的语义工具。"""
    annotations = ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )
    for service in (decide_codex_session_action, generate_skill_content, check_api_input):
        _register_adapter(server, service, annotations)
