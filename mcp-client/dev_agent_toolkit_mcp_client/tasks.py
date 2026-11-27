"""Resolve opt-in 2026-07-28 Tasks through the SDK extension API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from typing import Any, Literal

import anyio
from mcp import types
from mcp.client import ClaimContext, ClientExtension, ClientRequestContext, ResultClaim
from mcp.shared.exceptions import MCPError
from pydantic import Field

from .registry import ClientError


class _TaskState(types.Result):
    task_id: str = Field(min_length=1)
    status: Literal["working", "input_required", "completed", "cancelled", "failed"]
    status_message: str | None = None
    created_at: str
    last_updated_at: str
    ttl_ms: int | None = Field(ge=0)
    poll_interval_ms: int | None = Field(default=None, ge=0)


class _CreateTaskResult(_TaskState):
    result_type: Literal["task"]


class _GetTaskResult(_TaskState):
    result_type: Literal["complete"]
    result: types.CallToolResult | None = None
    error: types.ErrorData | None = None
    input_requests: types.InputRequests | None = None


class _TaskParams(types.RequestParams):
    task_id: str


class _TaskRequest(types.Request[_TaskParams, Literal["tasks/get", "tasks/cancel"]]):
    name_param = "taskId"


class _UpdateParams(_TaskParams):
    input_responses: types.InputResponses


class _UpdateRequest(types.Request[_UpdateParams, Literal["tasks/update"]]):
    method: Literal["tasks/update"] = "tasks/update"
    name_param = "taskId"


class TasksExtension(ClientExtension):
    identifier = "io.modelcontextprotocol/tasks"

    def __init__(self, emit: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._emit = emit

    def claims(self) -> Sequence[ResultClaim[_CreateTaskResult]]:
        return (
            ResultClaim(
                result_type="task",
                model=_CreateTaskResult,
                resolve=self._resolve,
                protocol_versions=frozenset({"2026-07-28"}),
            ),
        )

    async def _resolve(
        self, initial: _CreateTaskResult, claim: ClaimContext
    ) -> types.CallToolResult:
        session = claim.session
        if session.server_capabilities is None or self.identifier not in (
            session.server_capabilities.extensions or {}
        ):
            raise ClientError(
                "protocol_error",
                "Server returned a task without advertising the extension",
                outcome_unknown=True,
            )

        params = _TaskParams(task_id=initial.task_id)
        get = _TaskRequest(method="tasks/get", params=params)
        cancel = _TaskRequest(method="tasks/cancel", params=params)
        context = ClientRequestContext(session=session, request_id=initial.task_id)
        answered: set[str] = set()
        previous = _task_event(initial)
        state: _TaskState = initial
        terminal = False
        try:
            await self._emit(previous)
            while True:
                if state.status in {"working", "input_required"}:
                    interval = (
                        1000
                        if state.poll_interval_ms is None
                        else state.poll_interval_ms
                    )
                    await anyio.sleep(max(interval / 1000, 0.05))
                polled = await session.send_request(get, _GetTaskResult)
                if polled.task_id != initial.task_id:
                    raise ClientError(
                        "protocol_error",
                        "Task response changed the task identifier",
                        outcome_unknown=True,
                    )
                terminal = polled.status in {"completed", "cancelled", "failed"}
                event = _task_event(polled)
                if event != previous:
                    await self._emit(event)
                    previous = event
                if terminal:
                    return _task_result(polled)
                if polled.status == "input_required":
                    if not polled.input_requests:
                        raise ClientError(
                            "protocol_error",
                            "Task omitted the required input requests",
                            outcome_unknown=True,
                        )
                    responses: types.InputResponses = {}
                    for key, request in polled.input_requests.items():
                        if key in answered:
                            continue
                        response = await session.dispatch_input_request(
                            context, request
                        )
                        if isinstance(response, types.ErrorData):
                            raise MCPError.from_error_data(response)
                        responses[key] = response
                    if responses:
                        update = _UpdateRequest(
                            params=_UpdateParams(
                                task_id=params.task_id, input_responses=responses
                            )
                        )
                        await session.send_request(update, types.EmptyResult)
                        answered.update(responses)
                state = polled
        finally:
            if not terminal:
                # Cancellation is cooperative and cannot delay the owning session indefinitely.
                with anyio.move_on_after(0.5, shield=True), suppress(Exception):
                    await session.send_request(cancel, types.EmptyResult)


def _task_event(task: _TaskState) -> dict[str, Any]:
    return {
        "type": "task",
        **task.model_dump(
            mode="json",
            by_alias=True,
            exclude_unset=True,
            exclude={"result_type", "result", "error", "input_requests"},
        ),
    }


def _task_result(task: _GetTaskResult) -> types.CallToolResult:
    if task.status == "completed" and task.result is not None:
        return task.result
    if task.status == "failed" and task.error is not None:
        raise MCPError.from_error_data(task.error)
    if task.status == "cancelled":
        raise ClientError("task_cancelled", "Server cancelled the MCP task")
    raise ClientError(
        "protocol_error",
        "Terminal task omitted its result or error",
        outcome_unknown=True,
    )
