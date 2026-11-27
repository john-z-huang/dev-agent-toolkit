"""Translate the public client requests to the negotiated MCP SDK session."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, TypeVar

import anyio
from mcp import types
from mcp.client import (
    Client,
    ClientRequestContext,
    IncomingMessage,
    InputRequiredRoundsExceededError,
)
from mcp.client.subscriptions import SubscriptionLost
from mcp.shared.exceptions import MCPError
from mcp.shared.subscriptions import SUBSCRIPTION_ID_META_KEY, event_to_notification
from pydantic import BaseModel, ValidationError

from .process import managed_stdio
from .registry import ClientError, ServerConfig
from .tasks import TasksExtension

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]
InputHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

LEGACY_VERSION = "2025-11-25"
MODERN_VERSION = "2026-07-28"
ENVIRONMENT_TOOL = "get_mcp_environment"
_VERSIONS = {LEGACY_VERSION, MODERN_VERSION}
_LIST_METHODS = {
    "tools/list": "list_tools",
    "resources/list": "list_resources",
    "resources/templates/list": "list_resource_templates",
    "prompts/list": "list_prompts",
}
_CAPABILITIES = {
    "tools/list": "tools",
    "tools/schema": "tools",
    "tools/call": "tools",
    "resources/list": "resources",
    "resources/templates/list": "resources",
    "resources/read": "resources",
    "resources/subscribe": "resources",
    "resources/unsubscribe": "resources",
    "prompts/list": "prompts",
    "prompts/get": "prompts",
    "completion/complete": "completions",
    "logging/setLevel": "logging",
}
_LEGACY_METHODS = {
    "ping",
    "resources/subscribe",
    "resources/unsubscribe",
    "logging/setLevel",
}
_INPUT_TIMEOUT_MESSAGE = "Client input timed out"
_Model = TypeVar("_Model", bound=BaseModel)
_SESSION_ERRORS = (
    MCPError,
    SubscriptionLost,
    ValidationError,
    InputRequiredRoundsExceededError,
    anyio.BrokenResourceError,
    anyio.ClosedResourceError,
    anyio.EndOfStream,
    ExceptionGroup,
)


def _wire(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True, exclude_unset=True)


def _checked(model: type[_Model], params: dict[str, Any], *keys: str) -> _Model:
    if params.keys() - set(keys):
        raise ClientError("invalid_params", "Unexpected request parameter")
    try:
        return model.model_validate(params, strict=True)
    except ValidationError:
        raise ClientError("invalid_params", "Invalid request parameters") from None


def _no_params(params: dict[str, Any]) -> None:
    if params:
        raise ClientError("invalid_params", "This method takes no parameters")


def _translate(error: Exception, *, tool_call: bool = False) -> ClientError:
    if isinstance(error, ClientError):
        return error
    if isinstance(error, MCPError):
        if error.code == types.CONNECTION_CLOSED:
            return ClientError(
                "connection_lost", "MCP connection closed", outcome_unknown=tool_call
            )
        if error.code == types.REQUEST_TIMEOUT:
            code = (
                "input_timeout"
                if error.message == _INPUT_TIMEOUT_MESSAGE
                else "request_timeout"
            )
            return ClientError(
                code,
                "MCP request timed out",
                rpc_code=error.code,
                outcome_unknown=tool_call,
            )
        return ClientError(
            "rpc_error", "MCP server returned a JSON-RPC error", rpc_code=error.code
        )
    if isinstance(
        error,
        (
            SubscriptionLost,
            anyio.BrokenResourceError,
            anyio.ClosedResourceError,
            anyio.EndOfStream,
        ),
    ):
        return ClientError(
            "connection_lost", "MCP connection closed", outcome_unknown=tool_call
        )
    if isinstance(error, InputRequiredRoundsExceededError):
        return ClientError(
            "input_rounds_exceeded",
            "MCP input round limit reached",
            outcome_unknown=tool_call,
        )
    if isinstance(error, ExceptionGroup):
        return _translate(error.exceptions[0], tool_call=tool_call)
    return ClientError(
        "protocol_error", "Invalid MCP response", outcome_unknown=tool_call
    )


class _Callbacks:
    def __init__(
        self,
        config: ServerConfig,
        on_event: EventHandler | None,
        on_input: InputHandler | None,
    ) -> None:
        self.config = config
        self.on_event = on_event
        self.on_input = on_input
        self.known_tools: set[str] = set()

    async def emit(self, event: dict[str, Any]) -> None:
        if self.on_event is not None:
            await self.on_event(event)

    async def progress(
        self, progress: float, total: float | None, message: str | None
    ) -> None:
        event: dict[str, Any] = {"type": "progress", "progress": progress}
        if total is not None:
            event["total"] = total
        if message is not None:
            event["message"] = message
        await self.emit(event)

    async def notification(self, message: IncomingMessage) -> None:
        if isinstance(message, (Exception, types.ProgressNotification)):
            return
        if isinstance(message, types.ToolListChangedNotification):
            self.known_tools.clear()
        notification = _wire(message)
        if SUBSCRIPTION_ID_META_KEY not in (
            (notification.get("params") or {}).get("_meta") or {}
        ):
            await self.emit(
                {**notification, "type": "notification", "method": message.method}
            )

    async def _ask(
        self, method: str, params: BaseModel, result_model: type[_Model]
    ) -> _Model | types.ErrorData:
        if self.on_input is None:
            return types.ErrorData(
                code=types.INVALID_REQUEST, message="Client input unavailable"
            )
        try:
            with anyio.fail_after(self.config.input_timeout):
                result = await self.on_input(
                    {
                        "type": "input_required",
                        "method": method,
                        "params": _wire(params),
                    }
                )
            return result_model.model_validate(result)
        except TimeoutError:
            return types.ErrorData(
                code=types.REQUEST_TIMEOUT, message=_INPUT_TIMEOUT_MESSAGE
            )
        except (ClientError, ValidationError):
            return types.ErrorData(
                code=types.INVALID_PARAMS, message="Invalid client input response"
            )

    async def elicit(
        self, context: ClientRequestContext, params: types.ElicitRequestParams
    ) -> types.ElicitResult | types.ErrorData:
        result = await self._ask("elicitation/create", params, types.ElicitResult)
        if isinstance(result, types.ErrorData):
            return result
        if result.action == "accept" and isinstance(
            params, types.ElicitRequestFormParams
        ):
            from jsonschema import Draft202012Validator
            from jsonschema.exceptions import SchemaError
            from referencing import Registry
            from referencing.exceptions import Unresolvable

            validator = Draft202012Validator(
                params.requested_schema, registry=Registry()
            )
            try:
                validator.check_schema(params.requested_schema)
                if result.content is not None and validator.is_valid(result.content):
                    return result
            except (SchemaError, Unresolvable):
                pass
            return types.ErrorData(
                code=types.INVALID_PARAMS,
                message="Client input does not match the requested schema",
            )
        # The caller handles URL navigation. The response carries only the action.
        return types.ElicitResult(action=result.action)

    async def sample(
        self, context: ClientRequestContext, params: types.CreateMessageRequestParams
    ) -> types.CreateMessageResult | types.ErrorData:
        return await self._ask(
            "sampling/createMessage", params, types.CreateMessageResult
        )

    async def roots(self, context: ClientRequestContext) -> types.ListRootsResult:
        return types.ListRootsResult(
            roots=[
                types.Root.model_validate({"uri": root.as_uri(), "name": root.name})
                for root in self.config.roots
            ]
        )


class ProtocolConnection:
    def __init__(self, client: Client, callbacks: _Callbacks) -> None:
        self._client = client
        self._callbacks = callbacks

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Run a supported request and preserve the wire-style result fields."""
        client = self._client
        if method in _LEGACY_METHODS and client.protocol_version != LEGACY_VERSION:
            raise ClientError(
                "unsupported_method", "Method is unavailable in the negotiated protocol"
            )
        capability = _CAPABILITIES.get(method)
        if (
            capability is not None
            and getattr(client.server_capabilities, capability) is None
        ):
            raise ClientError(
                "unsupported_capability",
                "Server did not declare the required capability",
            )
        try:
            return await self._request(method, params)
        except _SESSION_ERRORS as error:
            raise _translate(error) from None

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        client = self._client
        if method in _LIST_METHODS:
            page = _checked(types.PaginatedRequestParams, params, "cursor")
            if method == "tools/list":
                return _wire(await self._list_tools(page.cursor))
            return _wire(
                await getattr(client, _LIST_METHODS[method])(cursor=page.cursor)
            )

        match method:
            case "server/info":
                _no_params(params)
                info: dict[str, Any] = {
                    "protocolVersion": client.protocol_version,
                    "capabilities": _wire(client.server_capabilities),
                }
                if client.server_info is not None:
                    info["serverInfo"] = _wire(client.server_info)
                if client.instructions is not None:
                    info["instructions"] = client.instructions
                return info
            case "ping":
                _no_params(params)
                return _wire(await client.session.send_ping())
            case "tools/schema":
                tool = _checked(types.CallToolRequestParams, params, "name")
                return await self._tool_schema(tool.name)
            case "tools/call":
                tool = _checked(
                    types.CallToolRequestParams, params, "name", "arguments"
                )
                if tool.name not in self._callbacks.known_tools:
                    await self._tool_schema(tool.name)
                progress = (
                    self._callbacks.progress
                    if self._callbacks.on_event is not None
                    else None
                )
                try:
                    return _wire(
                        await client.call_tool(
                            tool.name, tool.arguments, progress_callback=progress
                        )
                    )
                except _SESSION_ERRORS as error:
                    raise _translate(error, tool_call=True) from None
            case "resources/read":
                resource = _checked(types.ReadResourceRequestParams, params, "uri")
                return _wire(await client.read_resource(str(resource.uri)))
            case "resources/subscribe" | "resources/unsubscribe":
                return await self._legacy_subscription(method, params)
            case "subscriptions/listen":
                return await self._listen(params)
            case "prompts/get":
                prompt = _checked(
                    types.GetPromptRequestParams, params, "name", "arguments"
                )
                return _wire(await client.get_prompt(prompt.name, prompt.arguments))
            case "completion/complete":
                completion = _checked(
                    types.CompleteRequestParams, params, "ref", "argument", "context"
                )
                request = types.CompleteRequest(params=completion)
                return _wire(
                    await client.session.send_request(request, types.CompleteResult)
                )
            case "logging/setLevel":
                log = _checked(types.SetLevelRequestParams, params, "level")
                return _wire(
                    await client.session.send_request(
                        types.SetLevelRequest(params=log), types.EmptyResult
                    )
                )
            case _:
                raise ClientError(
                    "unsupported_method", "Unsupported client request method"
                )

    async def _list_tools(self, cursor: str | None) -> types.ListToolsResult:
        page = await self._client.list_tools(cursor=cursor)
        if cursor is None and page.next_cursor is None:
            self._callbacks.known_tools.clear()
        self._callbacks.known_tools.update(tool.name for tool in page.tools)
        return page

    async def _tool_schema(self, name: str) -> dict[str, Any]:
        cursor = None
        seen: set[str] = set()
        while True:
            page = await self._list_tools(cursor)
            for tool in page.tools:
                if tool.name == name:
                    return _wire(tool)
            cursor = page.next_cursor
            if cursor is None:
                raise ClientError(
                    "tool_not_found", "Tool is absent from the server catalog"
                )
            if cursor in seen:
                raise ClientError(
                    "protocol_error", "Server repeated a pagination cursor"
                )
            seen.add(cursor)

    async def _legacy_subscription(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        resources = self._client.server_capabilities.resources
        if resources is None or not resources.subscribe:
            raise ClientError(
                "unsupported_capability",
                "Server did not declare resource subscriptions",
            )
        resource = _checked(types.SubscribeRequestParams, params, "uri")
        request = (
            types.SubscribeRequest(params=resource)
            if method == "resources/subscribe"
            else types.UnsubscribeRequest(
                params=types.UnsubscribeRequestParams(uri=resource.uri)
            )
        )
        return _wire(
            await self._client.session.send_request(request, types.EmptyResult)
        )

    async def _listen(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._client.protocol_version != MODERN_VERSION:
            raise ClientError(
                "unsupported_method", "Subscription streams require protocol 2026-07-28"
            )
        request = _checked(
            types.SubscriptionsListenRequestParams, params, "notifications"
        )
        filters = request.notifications
        if filters.model_extra:
            raise ClientError("invalid_params", "Unsupported subscription filter")
        async with self._client.listen(
            tools_list_changed=bool(filters.tools_list_changed),
            prompts_list_changed=bool(filters.prompts_list_changed),
            resources_list_changed=bool(filters.resources_list_changed),
            resource_subscriptions=filters.resource_subscriptions or (),
        ) as subscription:
            acknowledgement = {
                "subscriptionId": subscription.subscription_id,
                "notifications": _wire(subscription.honored),
            }
            await self._callbacks.emit({"type": "subscription", **acknowledgement})
            async for event in subscription:
                meta = {SUBSCRIPTION_ID_META_KEY: subscription.subscription_id}
                notification = event_to_notification(event, meta)
                if isinstance(notification, types.ToolListChangedNotification):
                    self._callbacks.known_tools.clear()
                await self._callbacks.emit(
                    {
                        "type": "notification",
                        **_wire(notification),
                        "method": notification.method,
                    }
                )
        return acknowledgement


@asynccontextmanager
async def _connected_client(
    config: ServerConfig,
    callbacks: _Callbacks,
    environment: dict[str, str] | None = None,
) -> AsyncGenerator[Client, None]:
    pending: Exception | None = None
    async with AsyncExitStack() as stack:
        try:
            client = await stack.enter_async_context(
                Client(
                    managed_stdio(config, environment=environment),
                    mode=config.mode,
                    cache=None,
                    message_handler=callbacks.notification,
                    elicitation_callback=callbacks.elicit
                    if config.elicitation and callbacks.on_input is not None
                    else None,
                    sampling_callback=callbacks.sample
                    if config.sampling and callbacks.on_input is not None
                    else None,
                    list_roots_callback=callbacks.roots if config.roots else None,
                    extensions=[TasksExtension(callbacks.emit)]
                    if config.tasks
                    else None,
                )
            )
        except OSError:
            raise ClientError("startup_failed", "Cannot start the MCP server") from None
        except (ClientError, MCPError, ValidationError, ExceptionGroup) as error:
            raise _translate(error) from None

        if client.protocol_version not in _VERSIONS:
            pending = ClientError(
                "unsupported_protocol", "Server negotiated an unsupported MCP version"
            )
        else:
            try:
                yield client
            except Exception as error:
                # Close the SDK's task groups before returning the caller's exception.
                pending = error
    if pending is not None:
        raise pending


async def _requested_environment(connection: ProtocolConnection) -> dict[str, str]:
    try:
        tool = await connection.request("tools/schema", {"name": ENVIRONMENT_TOOL})
    except ClientError as error:
        if error.code not in {"tool_not_found", "unsupported_capability"}:
            raise
        return {}

    annotations = tool.get("annotations") or {}
    if annotations.get("readOnlyHint") is not True:
        raise ClientError(
            "invalid_environment_declaration",
            "Environment discovery must be declared read-only",
        )
    try:
        result = await connection.request("tools/call", {"name": ENVIRONMENT_TOOL})
    except ClientError as error:
        raise ClientError(error.code, str(error), rpc_code=error.rpc_code) from None
    declaration = result.get("structuredContent")
    if result.get("isError") or not isinstance(declaration, dict):
        raise ClientError(
            "invalid_environment_declaration",
            "Environment discovery did not return a structured result",
        )
    names = declaration.get("names")
    if not isinstance(names, list) or any(
        not isinstance(name, str) or not name or "=" in name or "\0" in name
        for name in names
    ):
        raise ClientError(
            "invalid_environment_declaration",
            "Server declared invalid environment variable names",
        )
    return {
        name: value for name in names if (value := os.environ.get(name)) is not None
    }


@asynccontextmanager
async def connect(
    config: ServerConfig,
    on_event: EventHandler | None = None,
    on_input: InputHandler | None = None,
) -> AsyncGenerator[ProtocolConnection, None]:
    """Discover a server's environment needs before sending application requests."""
    callbacks = _Callbacks(config, on_event, on_input)
    async with _connected_client(config, callbacks) as probe:
        connection = ProtocolConnection(probe, callbacks)
        environment = await _requested_environment(connection)
        if not environment:
            yield connection
            return

    callbacks.known_tools.clear()
    async with _connected_client(config, callbacks, environment) as client:
        yield ProtocolConnection(client, callbacks)
