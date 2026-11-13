"""固定 GitLab API 边界；主机和多级项目路径始终显式绑定。"""

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

from .paths import _validated_repo_path
from .process import _run_fixed


class GitLabError(ValueError):
    """可安全返回给调用方的 GitLab 协议错误。"""


@dataclass(frozen=True)
class GitLabContext:
    root: str
    host: str
    project: str

    @property
    def endpoint(self) -> str:
        return f"projects/{quote(self.project, safe='')}"


def gitlab_context(repo_path: str, repo: str) -> GitLabContext:
    """只接受 host/group[/subgroup]/project，不猜默认主机。"""
    host, separator, project = repo.partition("/")
    if (
        not separator
        or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host)
        or len(project.split("/")) < 2
        or any(
            not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", part)
            or part in {".", ".."}
            for part in project.split("/")
        )
        or project.endswith(".git")
    ):
        raise ValueError(
            "repo 必须为 host/group[/subgroup]/project，host 不含端口；不含协议、凭据或 .git 后缀"
        )
    root, error = _validated_repo_path(repo_path)
    if error:
        raise ValueError(error)
    assert root is not None
    return GitLabContext(root, host.lower(), project)


def gitlab_api(
    context: GitLabContext,
    suffix: str = "",
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    global_endpoint: str | None = None,
) -> Any:
    """仅供领域服务传固定 endpoint；错误不回显 CLI 正文或凭据。"""
    endpoint = global_endpoint or context.endpoint + suffix
    args = ["glab", "api", "--hostname", context.host, "--method", method, endpoint]
    if payload is not None:
        args.extend(["--input", "-"])
    try:
        result = _run_fixed(
            args,
            cwd=context.root,
            input_text=None if payload is None else json.dumps(payload),
        )
    except OSError:
        raise ValueError("glab 不可用；未回显认证信息") from None
    if result.returncode != 0:
        raise ValueError(
            f"GitLab API 请求失败（退出码 {result.returncode}）；写入结果须回读确认"
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ValueError("GitLab API 返回无效 JSON；写入结果须回读确认") from None
    if not isinstance(value, (dict, list)):
        raise GitLabError("GitLab API 响应必须为对象或列表")
    return value


def gitlab_object(
    context: GitLabContext, suffix: str = "", **kwargs: Any
) -> dict[str, Any]:
    value = gitlab_api(context, suffix, **kwargs)
    if not isinstance(value, dict):
        raise GitLabError("GitLab API 响应不是对象")
    for field in ("labels", "assignees"):
        if field in value and not isinstance(value[field], list):
            raise GitLabError("GitLab API 的 labels/assignees 必须为列表")
    if any(not isinstance(item, dict) for item in value.get("assignees", [])):
        raise GitLabError("GitLab API 的 assignees 必须为对象列表")
    if "labels" in value and any(not isinstance(item, str) for item in value["labels"]):
        raise GitLabError("GitLab API 的 labels 必须为字符串列表")
    if value.get("description") is not None and not isinstance(
        value["description"], str
    ):
        raise GitLabError("GitLab API 的 description 必须为字符串或 null")
    return value


def gitlab_list(context: GitLabContext, suffix: str) -> list[dict[str, Any]]:
    value = gitlab_api(context, suffix)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("GitLab API 响应不是对象列表")
    return value


def create_and_read(
    context: GitLabContext, collection: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """统一记录非幂等创建的结果；响应失败不能推定没有写入。"""
    created: bool | None = None
    number = None
    try:
        value = gitlab_object(context, collection, method="POST", payload=payload)
        created, number = True, value.get("iid")
        if not isinstance(number, int) or number <= 0:
            raise ValueError("创建命令成功但缺少有效 iid；须回读，禁止重复创建")
        details = gitlab_object(context, f"{collection}/{number}")
        if details.get("iid") != number:
            raise ValueError("创建成功，但回读 iid 不匹配；禁止重复创建")
        return {
            "ok": True,
            "created": True,
            "write_attempted": True,
            "number": number,
            "resource": details,
        }
    except ValueError as error:
        return {
            "ok": False,
            "created": created,
            "write_attempted": True,
            "number": number,
            "error": str(error),
        }


def require_origin(context: GitLabContext) -> None:
    """本地推送/同步前同时核对 fetch 和全部 push URL；不输出 URL。"""
    for arguments in (["get-url", "origin"], ["get-url", "--push", "--all", "origin"]):
        result = _run_fixed(["git", "remote", *arguments], cwd=context.root)
        urls = result.stdout.splitlines()
        if (
            result.returncode != 0
            or not urls
            or any(
                _remote_identity(url) != (context.host, context.project) for url in urls
            )
        ):
            raise ValueError(
                "origin 与显式 GitLab 项目不一致或无法核实；未输出 remote URL"
            )


def _remote_identity(url: str) -> tuple[str, str] | None:
    if "://" in url:
        parsed = urlsplit(url)
        if parsed.scheme not in {"https", "ssh"} or not parsed.hostname:
            return None
        host = parsed.hostname.lower()
        # SSH 端口不表示 API 主机端口。
        if parsed.scheme == "https" and parsed.port:
            host += f":{parsed.port}"
        path = parsed.path.lstrip("/")
    else:
        match = re.fullmatch(r"(?:[^@/:]+@)?([A-Za-z0-9.-]+):(.+)", url)
        if not match:
            return None
        host, path = match.group(1).lower(), match.group(2)
    return host, path.removesuffix(".git")


def require_positive(number: int) -> None:
    if number <= 0:
        raise ValueError("Issue/MR 编号必须为项目内正数 iid，不是全局 id")


def resource_summary(value: dict[str, Any]) -> dict[str, Any]:
    """只返回核对所需字段，不传播完整 API 响应。"""
    fields = (
        "iid",
        "title",
        "state",
        "labels",
        "source_branch",
        "target_branch",
        "sha",
        "merged_at",
        "detailed_merge_status",
        "source_project_id",
        "target_project_id",
    )
    result = {key: value[key] for key in fields if key in value}
    result["assignees"] = [
        item.get("username")
        for item in value.get("assignees", [])
        if isinstance(item, dict)
    ]
    return result
