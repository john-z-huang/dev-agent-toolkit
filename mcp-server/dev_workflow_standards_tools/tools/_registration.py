"""按服务的同步/异步属性注册 MCP 适配器，保持参数 Schema 和注解。"""

import inspect
from collections.abc import Callable
from functools import wraps
from typing import Annotated, Any, get_type_hints

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from ._descriptions import PARAMETER_DESCRIPTIONS, TOOL_DESCRIPTIONS


def _register_adapter(
    server: MCPServer, service: Callable[..., Any], annotations: ToolAnnotations
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
    parameters = [
        parameter.replace(
            annotation=Annotated[
                type_hints[parameter.name],
                Field(description=descriptions[parameter.name]),
            ]
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

    adapter.__signature__ = signature.replace(
        parameters=parameters,
        return_annotation=type_hints.get("return", signature.return_annotation),
    )
    server.tool(description=TOOL_DESCRIPTIONS[service_name], annotations=annotations)(
        adapter
    )
