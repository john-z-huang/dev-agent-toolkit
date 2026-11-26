"""Build facts captured once for this MCP process."""

import re
from importlib.metadata import PackageNotFoundError, distribution

from .. import SERVER_NAME


def _load_build_info() -> tuple[str | None, str | None]:
    try:
        package = distribution(SERVER_NAME)
    except PackageNotFoundError:
        return None, None
    try:
        commit = (package.read_text("extra_metadata/git-commit.txt") or "").strip()
    except (OSError, UnicodeError):
        commit = ""
    if re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", commit):
        return package.version, commit
    return package.version, None


SERVER_VERSION, _GIT_COMMIT = _load_build_info()


def get_mcp_server_build_info() -> dict[str, str | None]:
    return {"server_version": SERVER_VERSION, "git_commit": _GIT_COMMIT}
