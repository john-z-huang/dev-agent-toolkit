"""Register the startup-project Serena Memory readers."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from ..services.serena_memory import (
    MAX_CHANGED_CONTENT_CHARS,
    MAX_TAIL_LINES,
    SerenaMemoryReadService,
)

MemoryPath = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=4096,
        description="启动项目 .serena/memories 下的相对名称，可带 mem: 前缀和 .md 后缀。",
    ),
]
TailLines = Annotated[
    int,
    Field(
        strict=True,
        ge=0,
        le=MAX_TAIL_LINES,
        description="从末尾读取的逻辑行数。0 返回空文本及总行数。",
    ),
]
ChangedContent = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=MAX_CHANGED_CONTENT_CHARS,
        description="在所选尾部查找的非空文本，按原字符和大小写匹配。",
    ),
]


def register_serena_memory_tools(server: MCPServer) -> None:
    reader = SerenaMemoryReadService()
    annotations = ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )

    @server.tool(
        name="serena_memory_tail_read",
        description=(
            "只读查看项目 Memory 的最后若干逻辑行。先确认 MCP 启动目录是目标项目根。"
            "仅打开该项目 .serena/memories 内的普通 UTF-8 文件。绝对路径、越界引用、"
            "全局 Memory 和符号链接均拒绝。返回规范名称、文件路径、总行数、所读范围及原始行尾；"
            "所选文本超过 64000 字符或文件不可读时返回 unavailable 和 reason_code。"
            "不写文件、不调用 Serena、宿主会话或网络。"
            '示例：{"memory_path":"mem:plans/PLAN-example","tail_lines":20}。'
        ),
        annotations=annotations,
        structured_output=False,
    )
    def tail_read(memory_path: MemoryPath, tail_lines: TailLines) -> dict[str, Any]:
        return reader.tail_read(memory_path, tail_lines)

    @server.tool(
        name="serena_memory_write_check",
        description=(
            "只读核对预期文本是否出现在项目 Memory 文件尾部。"
            "使用与 serena_memory_tail_read 相同的启动项目、路径限制和行数窗口。"
            "仅对该窗口做区分大小写的字面匹配，返回 success、reason_code、行数和匹配偏移，"
            "不回显正文。匹配表示文本出现在所读范围，无法判断何时写入。"
            "文件不可读或窗口超限时返回 unavailable。不写文件、不调用 Serena、宿主会话或网络。"
            '示例：{"memory_path":"plans/PLAN-example","changed_content":"验证通过","tail_lines":20}。'
        ),
        annotations=annotations,
        structured_output=False,
    )
    def write_check(
        memory_path: MemoryPath, changed_content: ChangedContent, tail_lines: TailLines
    ) -> dict[str, Any]:
        return reader.write_check(memory_path, changed_content, tail_lines)
