"""GitLab 领域服务的 MCP 注册。"""

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from ..services import gitlab_issues, gitlab_merge_requests, gitlab_repository
from ._registration import _register_adapter


def register_gitlab_tools(server: MCPServer) -> None:
    read = ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
    write = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )
    destructive = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=True,
    )
    for service, annotations in (
        (gitlab_repository.audit_gitlab_repository_state, read),
        (gitlab_repository.audit_issue_mr_policy, read),
        (gitlab_issues.list_gitlab_issue_labels, read),
        (gitlab_issues.create_gitlab_issue, write),
        (gitlab_issues.push_gitlab_issue_branch_to_origin, write),
        (gitlab_merge_requests.create_gitlab_merge_request, write),
        (gitlab_merge_requests.merge_gitlab_merge_request, destructive),
        (gitlab_repository.push_gitlab_fork_main_fast_forward, write),
        (gitlab_repository.cleanup_merged_mr_local_branch, destructive),
    ):
        _register_adapter(server, service, annotations)
