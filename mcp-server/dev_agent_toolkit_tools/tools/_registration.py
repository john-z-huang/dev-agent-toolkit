"""按服务的同步/异步属性注册 MCP 适配器，保持参数 Schema 和注解。"""

import inspect
from functools import wraps
from operator import getitem
from typing import Annotated, Any, Protocol, get_type_hints

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from ..services.local_mcp import BRIDGE_METADATA_KEY
from ._descriptions import PARAMETER_DESCRIPTIONS, TOOL_DESCRIPTIONS


class _Service(Protocol):
    @property
    def __name__(self) -> str: ...

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


def _register_adapter(
    server: MCPServer,
    service: _Service,
    annotations: ToolAnnotations,
    *,
    local_stdio: bool = False,
) -> None:
    """合并领域参数说明，并保留 MCP 对协程函数的识别和等待能力。"""
    service_name = service.__name__
    descriptions = PARAMETER_DESCRIPTIONS[service_name]
    signature = inspect.signature(service, follow_wrapped=False)
    type_hints = get_type_hints(service, include_extras=True)
    if set(descriptions) != set(signature.parameters):
        raise ValueError(
            f"MCP parameter descriptions do not match {service_name} signature"
        )
    # 参数类型在运行时解析，供 MCP 从 Annotated 中提取说明。
    parameters = [
        parameter.replace(
            annotation=getitem(
                Annotated,
                (
                    type_hints[parameter.name],
                    Field(description=descriptions[parameter.name]),
                ),
            )
        )
        for parameter in signature.parameters.values()
    ]

    # MCP 根据包装器本身判断执行方式；仅使用 wraps 的同步包装器不能替代协程。
    if inspect.iscoroutinefunction(service):

        @wraps(service)
        async def adapter(*args: Any, **kwargs: Any) -> Any:
            return await service(*args, **kwargs)
    else:

        @wraps(service)
        def adapter(*args: Any, **kwargs: Any) -> Any:
            return service(*args, **kwargs)

    adapter_signature = signature.replace(
        parameters=parameters,
        return_annotation=type_hints.get("return", signature.return_annotation),
    )
    setattr(adapter, "__signature__", adapter_signature)
    server.tool(
        description=TOOL_DESCRIPTIONS[service_name],
        annotations=annotations,
        meta={BRIDGE_METADATA_KEY: True} if local_stdio else None,
    )(adapter)
