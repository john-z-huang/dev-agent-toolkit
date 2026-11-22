"""MCP server composition root and stdio entrypoint."""

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.server import Context
from pydantic import ValidationError

from .tools._descriptions import SERVER_DESCRIPTION, SERVER_INSTRUCTIONS
from .tools.ai_workflow import register_ai_workflow_tools
from .tools.codex_session_facts import register_codex_session_fact_tools
from .tools.git import register_git_tools
from .tools.github import register_github_tools
from .tools.gitlab import register_gitlab_tools
from .tools.repository import register_repository_tools
from .tools.serena_memory import register_serena_memory_tools
from .tools.web_search import register_web_search_tools


class _SafeMCPServer(MCPServer):
    """Hide rejected argument values from tool errors and server logs."""

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context | None = None
    ) -> Any:
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as error:
            if isinstance(error.__cause__, ValidationError):
                raise ToolError(
                    "Invalid tool arguments; review the published input schema."
                ) from None
            raise


mcp = _SafeMCPServer(
    "dev-workflow-standards-tools",
    description=SERVER_DESCRIPTION,
    instructions=SERVER_INSTRUCTIONS,
)

register_git_tools(mcp)
register_repository_tools(mcp)
register_github_tools(mcp)
register_gitlab_tools(mcp)
register_codex_session_fact_tools(mcp)
register_ai_workflow_tools(mcp)
register_web_search_tools(mcp)
register_serena_memory_tools(mcp)


def main() -> None:
    """Start the local Codex MCP server using stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
