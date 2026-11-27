"""Async execution API shared by standalone and interactive clients."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .batch import parse_steps, prepare_step
from .registry import ClientError, RegisteredServer, Registry

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]
InputHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class _Call:
    method: str
    params: dict[str, Any]
    result: asyncio.Future[dict[str, Any]]


def request_outcome(method: str, result: dict[str, Any]) -> dict[str, Any]:
    if method == "tools/call" and result.get("isError") is True:
        error = ClientError("tool_error", "The server tool returned an error")
        return {"ok": False, "error": error.as_dict(), "result": result}
    return {"ok": True, "result": result}


class Session:
    """A lazy connection limited to one server snapshot and working directory."""

    def __init__(
        self,
        registry: Registry,
        server: str,
        snapshot: RegisteredServer,
        on_event: EventHandler | None,
        on_input: InputHandler | None,
    ) -> None:
        self._registry = registry
        self._server = server
        self._snapshot = snapshot
        self._config = snapshot.config.model_copy(deep=True)
        if self._config.cwd is None:
            self._config.cwd = Path.cwd().resolve()
        self._on_event = on_event
        self._on_input = on_input
        self._queue: asyncio.Queue[_Call] = asyncio.Queue()
        self._active: _Call | None = None
        self._operation: asyncio.Task[dict[str, Any]] | None = None
        self._ended = asyncio.Event()
        self._closing = False
        self._loop = asyncio.get_running_loop()
        self._deadline = self._loop.time() + self._config.max_session_age
        self._actor = asyncio.create_task(self._serve())
        self._actor.add_done_callback(self._finish)

    @property
    def closed(self) -> bool:
        return self._closing or self._ended.is_set()

    async def wait_closed(self) -> None:
        await self._ended.wait()

    async def close(self) -> None:
        if not self.closed:
            self._closing = True
            self._actor.cancel()
        await self.wait_closed()

    async def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if self.closed:
            raise ClientError("session_closed", "The session is closed")
        if (
            not isinstance(method, str)
            or not method
            or (params is not None and not isinstance(params, dict))
        ):
            raise ClientError(
                "invalid_request", "Expected a method and an object of parameters"
            )
        result: asyncio.Future[dict[str, Any]] = self._loop.create_future()
        self._queue.put_nowait(
            _Call(method, deepcopy(params) if params is not None else {}, result)
        )
        return await result

    async def batch(self, requests: list[dict[str, Any]]) -> dict[str, Any]:
        steps = parse_steps(requests)
        items: list[dict[str, Any]] = []
        for index, step in enumerate(steps):
            try:
                method, params = prepare_step(step, items)
                reply = request_outcome(method, await self.request(method, params))
            except ClientError as error:
                reply = {"ok": False, "error": error.as_dict()}
            items.append({"index": index, **reply})
            if not reply["ok"]:
                return {
                    "ok": False,
                    "items": items,
                    "skipped": len(steps) - len(items),
                }
        return {"ok": True, "items": items, "skipped": 0}

    def _check_registered(self) -> None:
        try:
            registered = self._registry.get(self._server)
        except ClientError as error:
            if error.code == "server_not_found":
                raise ClientError(
                    "server_removed", "The session's server was removed"
                ) from None
            raise
        if registered.identity != self._snapshot.identity:
            raise ClientError("server_removed", "The session's server was replaced")

    def _cancel_call(self, future: asyncio.Future[dict[str, Any]]) -> None:
        if (
            not future.cancelled()
            or self._active is None
            or self._active.result is not future
        ):
            return
        if self._operation is not None:
            self._operation.cancel()
        elif not self.closed:
            self._closing = True
            self._actor.cancel()

    def _finish(self, actor: asyncio.Task[None]) -> None:
        if not actor.cancelled():
            actor.exception()
        calls = [self._active] if self._active is not None else []
        while not self._queue.empty():
            calls.append(self._queue.get_nowait())
        for call in calls:
            if not call.result.done():
                call.result.set_exception(
                    ClientError("session_closed", "The session is closed")
                )
        self._active = None
        self._ended.set()

    async def _serve(self) -> None:
        from .protocol import connect

        idle_deadline = self._loop.time() + self._config.idle_timeout
        async with AsyncExitStack() as stack:
            connection = None
            while True:
                try:
                    async with asyncio.timeout_at(min(idle_deadline, self._deadline)):
                        call = await self._queue.get()
                except TimeoutError:
                    return
                if call.result.cancelled():
                    continue

                self._active = call
                call.result.add_done_callback(self._cancel_call)
                phase = "startup"
                try:
                    self._check_registered()
                    if connection is None:
                        end = min(
                            self._deadline,
                            self._loop.time() + self._config.startup_timeout,
                        )
                        async with asyncio.timeout_at(end):
                            connection = await stack.enter_async_context(
                                connect(
                                    self._config,
                                    on_event=self._on_event,
                                    on_input=self._on_input,
                                )
                            )
                        self._check_registered()
                    phase = "request"
                    if self._loop.time() >= self._deadline:
                        raise ClientError(
                            "session_expired", "The session exceeded its maximum age"
                        )
                    end = min(
                        self._deadline, self._loop.time() + self._config.request_timeout
                    )
                    self._operation = asyncio.create_task(
                        connection.request(call.method, call.params)
                    )
                    async with asyncio.timeout_at(end):
                        result = await self._operation
                    if not call.result.done():
                        call.result.set_result(result)
                except TimeoutError:
                    error = ClientError(
                        f"{phase}_timeout",
                        f"MCP {phase} timed out",
                        outcome_unknown=phase == "request"
                        and call.method == "tools/call",
                    )
                    if not call.result.done():
                        call.result.set_exception(error)
                    return
                except ClientError as error:
                    if not call.result.done():
                        # Keep the running transport task's frames out of the caller's traceback.
                        call.result.set_exception(ClientError(**error.as_dict()))
                    if (
                        connection is None
                        or error.outcome_unknown
                        or error.code
                        in {"server_removed", "connection_lost", "session_expired"}
                    ):
                        return
                except asyncio.CancelledError:
                    if not call.result.done():
                        call.result.set_exception(
                            ClientError(
                                "cancelled",
                                "The request was cancelled",
                                outcome_unknown=phase == "request"
                                and call.method == "tools/call",
                            )
                        )
                    return
                except Exception:
                    if not call.result.done():
                        call.result.set_exception(
                            ClientError(
                                "client_error",
                                f"MCP {phase} failed",
                                outcome_unknown=phase == "request"
                                and call.method == "tools/call",
                            )
                        )
                    return
                finally:
                    call.result.remove_done_callback(self._cancel_call)
                    self._operation = None
                    self._active = None
                idle_deadline = self._loop.time() + self._config.idle_timeout


@asynccontextmanager
async def open_session(
    registry: Registry,
    server: str,
    *,
    on_event: EventHandler | None = None,
    on_input: InputHandler | None = None,
    snapshot: RegisteredServer | None = None,
) -> AsyncGenerator[Session, None]:
    """Reserve a session. Open the transport only when its first request arrives."""
    session = Session(
        registry, server, snapshot or registry.get(server), on_event, on_input
    )
    try:
        yield session
    finally:
        await session.close()


async def execute(
    registry: Registry,
    server: str,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    on_event: EventHandler | None = None,
    on_input: InputHandler | None = None,
) -> dict[str, Any]:
    async with open_session(
        registry, server, on_event=on_event, on_input=on_input
    ) as session:
        return await session.request(method, params)


async def execute_batch(
    registry: Registry,
    server: str,
    requests: list[dict[str, Any]],
    *,
    on_event: EventHandler | None = None,
    on_input: InputHandler | None = None,
) -> dict[str, Any]:
    async with open_session(
        registry, server, on_event=on_event, on_input=on_input
    ) as session:
        return await session.batch(requests)
