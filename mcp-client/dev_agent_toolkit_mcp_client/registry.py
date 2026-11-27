"""Persistent configuration for explicitly trusted local MCP servers."""

from __future__ import annotations

import builtins
import fcntl
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


class ClientError(Exception):
    """A stable client error safe to present without a traceback."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        rpc_code: int | None = None,
        outcome_unknown: bool = False,
    ) -> None:
        self.code = code
        self.rpc_code = rpc_code
        self.outcome_unknown = outcome_unknown
        super().__init__(message or code)

    def as_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.rpc_code is not None:
            error["rpc_code"] = self.rpc_code
        if self.outcome_unknown:
            error["outcome_unknown"] = True
        return error


class ServerConfig(BaseModel):
    """Configuration for an explicitly trusted local executable."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    transport: Literal["stdio"] = "stdio"
    command: str
    args: list[str] = Field(default_factory=list)
    cwd: Path | None = None
    mode: Literal["auto", "legacy"] = "auto"
    startup_timeout: float = Field(default=15, gt=0)
    request_timeout: float = Field(default=120, gt=0)
    idle_timeout: float = Field(default=60, gt=0)
    max_session_age: float = Field(default=3600, gt=0)
    input_timeout: float = Field(default=60, gt=0)
    elicitation: bool = False
    roots: list[Path] = Field(default_factory=list)
    sampling: bool = False
    tasks: bool = False

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_settings(cls, value: Any) -> Any:
        if isinstance(value, dict):
            obsolete = {"allowed_tools", "env", "env_vars"}
            return {key: item for key, item in value.items() if key not in obsolete}
        return value

    @field_validator("command")
    @classmethod
    def absolute_command(cls, value: str) -> str:
        if not Path(value).is_absolute() or "\0" in value:
            raise ValueError("command must be an absolute executable path")
        return value

    @field_validator("cwd", "roots")
    @classmethod
    def absolute_paths(
        cls, value: Path | list[Path] | None
    ) -> Path | list[Path] | None:
        paths = value if isinstance(value, list) else [] if value is None else [value]
        if any(not path.is_absolute() or "\0" in str(path) for path in paths):
            raise ValueError("paths must be absolute")
        return value

    @field_validator("args")
    @classmethod
    def valid_arguments(cls, args: list[str]) -> list[str]:
        if any("\0" in arg for arg in args):
            raise ValueError("arguments cannot contain NUL")
        return args


class RegisteredServer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: str
    config: ServerConfig


class _RegistryData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    servers: dict[str, RegisteredServer] = Field(default_factory=dict)


def default_registry_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "dev-agent-toolkit" / "mcp-servers.json"


def _check_name(name: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name) is None:
        raise ClientError("invalid_server", "Invalid server identifier")


class Registry:
    """Read snapshots atomically and serialize mutations across CLI processes."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or default_registry_path()).expanduser().resolve()

    def _read(self) -> _RegistryData:
        try:
            return _RegistryData.model_validate_json(self.path.read_bytes())
        except FileNotFoundError:
            return _RegistryData()
        except (OSError, ValidationError):
            raise ClientError(
                "registry_error", "Cannot read the server registry"
            ) from None

    def list(self) -> builtins.list[str]:
        return sorted(self._read().servers)

    def get(self, name: str) -> RegisteredServer:
        _check_name(name)
        try:
            return self._read().servers[name]
        except KeyError:
            raise ClientError("server_not_found", "Server is not registered") from None

    def add(self, name: str, config: ServerConfig) -> RegisteredServer:
        return self._mutate("add", name, config)

    def update(self, name: str, config: ServerConfig) -> RegisteredServer:
        return self._mutate("update", name, config)

    def remove(self, name: str) -> None:
        self._mutate("remove", name, None)

    def _mutate(
        self,
        action: Literal["add", "update", "remove"],
        name: str,
        config: ServerConfig | None,
    ) -> RegisteredServer:
        _check_name(name)
        lock_path = self.path.with_name(self.path.name + ".lock")
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "rb+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                data = self._read()
                previous = data.servers.get(name)
                if action == "add" and previous is not None:
                    raise ClientError("server_exists", "Server is already registered")
                if action != "add" and previous is None:
                    raise ClientError("server_not_found", "Server is not registered")
                if config is None:
                    saved = data.servers.pop(name)
                else:
                    saved = RegisteredServer(
                        identity=previous.identity
                        if previous is not None
                        else uuid4().hex,
                        config=config,
                    )
                    data.servers[name] = saved
                self._replace(data)
                return saved
        except OSError:
            raise ClientError(
                "registry_error", "Cannot update the server registry"
            ) from None

    def _replace(self, data: _RegistryData) -> None:
        with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                payload = json.dumps(
                    data.model_dump(mode="json"), indent=2, ensure_ascii=False
                )
                stream.write((payload + "\n").encode())
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
