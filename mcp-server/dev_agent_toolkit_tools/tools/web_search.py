"""公开网络搜索的 MCP 适配器。"""

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from ..services import web_search as service
from ..services.web_search import WebSearchRequest
from ._registration import _register_adapter


async def web_search(request: WebSearchRequest) -> dict:
    """联网检索公开资料并返回来源，不读取本地项目或执行写入。"""
    return await service.web_search(request)


def register_web_search_tools(server: MCPServer) -> None:
    _register_adapter(
        server,
        web_search,
        ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=True,
        ),
    )
