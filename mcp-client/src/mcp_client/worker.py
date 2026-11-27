"""Temporary per-session CLI workers and their private JSON Lines IPC."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import stat
import subprocess
import sys
import threading
from collections import deque
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

from .api import EventHandler, Session, open_session
from .registry import ClientError, Registry

_IPC_LIMIT = 16 * 1024 * 1024
_STARTUP_SECONDS = 10.0
_CONTROL_SECONDS = 10.0


def _session_directory(session_id: str, *, create: bool = False) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", session_id):
        raise ClientError("invalid_request", "Invalid session ID")
    # A short path also fits the smaller macOS Unix socket address limit.
    uid = os.geteuid()
    root = Path("/tmp") / f"datk-mcp-{uid}"
    directory = root / session_id
    try:
        if create:
            root.mkdir(mode=0o700, exist_ok=True)
        root_info = root.lstat()
        if (
            not stat.S_ISDIR(root_info.st_mode)
            or root_info.st_uid != uid
            or root_info.st_mode & 0o077
        ):
            raise ClientError("invalid_session_directory", "Unsafe session directory")
        if create:
            directory.mkdir(mode=0o700)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
            raise ClientError("invalid_session_directory", "Unsafe session directory")
    except OSError:
        raise ClientError(
            "session_unavailable", "Session directory unavailable"
        ) from None
    return directory


def _remove_session_directory(directory: Path) -> None:
    (directory / "control.sock").unlink(missing_ok=True)
    with suppress(FileNotFoundError):
        directory.rmdir()


async def _receive(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    try:
        line = await reader.readline()
        if not line:
            return None
        value = json.loads(line)
    except (ValueError, RecursionError):
        raise ClientError(
            "invalid_request", "Invalid or oversized IPC message"
        ) from None
    if not isinstance(value, dict):
        raise ClientError("invalid_request", "IPC message must be an object")
    return value


async def _send(writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
    try:
        line = json.dumps(message, ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        raise ClientError("invalid_request", "IPC message must be valid JSON") from None
    if len(line) >= _IPC_LIMIT:
        raise ClientError("message_too_large", "IPC message exceeds 16 MiB")
    writer.write(line + b"\n")
    await writer.drain()


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with suppress(OSError, TimeoutError):
        async with asyncio.timeout(1):
            await writer.wait_closed()


async def worker_request(
    session_id: str,
    action: str,
    payload: dict[str, Any] | None = None,
    on_event: EventHandler | None = None,
) -> dict[str, Any]:
    """Send one command to a live worker, delivering any events in order."""
    socket = _session_directory(session_id) / "control.sock"
    payload = {} if payload is None else payload
    attempted = False
    try:
        async with asyncio.timeout(_CONTROL_SECONDS):
            reader, writer = await asyncio.open_unix_connection(
                socket, limit=_IPC_LIMIT
            )
        try:
            async with asyncio.timeout(
                None if action == "request" else _CONTROL_SECONDS
            ):
                attempted = True
                await _send(writer, {"action": action, "payload": payload})
                while (message := await _receive(reader)) is not None:
                    match message.get("type"):
                        case "result":
                            return message["result"]
                        case "error":
                            raise ClientError(**message["error"])
                        case "event":
                            if on_event is not None:
                                await on_event(message["event"])
        finally:
            await _close_writer(writer)
    except TimeoutError:
        raise ClientError("session_control_timeout", "Worker did not respond") from None
    except OSError:
        pass
    raise ClientError(
        "session_unavailable",
        "Session worker is unavailable",
        outcome_unknown=attempted and payload.get("method") == "tools/call",
    )


async def open_worker(registry: Registry, server: str) -> dict[str, Any]:
    """Start a worker and return its status after its IPC socket is ready."""
    snapshot = registry.get(server)
    session_id = uuid4().hex
    directory = _session_directory(session_id, create=True)
    process: subprocess.Popen[bytes] | None = None
    ready = False
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-m",
                f"{__package__}.worker",
                session_id,
                os.fspath(registry.path),
                server,
                snapshot.identity,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        async with asyncio.timeout(_STARTUP_SECONDS):
            while process.poll() is None:
                if (directory / "control.sock").is_socket():
                    try:
                        status = await worker_request(session_id, "status")
                    except ClientError as error:
                        if error.code != "session_unavailable":
                            raise
                    else:
                        ready = True
                        return status
                await asyncio.sleep(0.025)
        raise ClientError(
            "session_start_failed", "Session worker exited during startup"
        )
    except TimeoutError:
        raise ClientError(
            "session_start_timeout", "Session worker did not start"
        ) from None
    except OSError:
        raise ClientError(
            "session_start_failed", "Could not start the session worker"
        ) from None
    finally:
        if ready and process is not None:
            # The opening CLI may exit immediately. A Python caller that remains
            # alive still needs to reap its worker when that worker eventually exits.
            threading.Thread(target=process.wait, daemon=True).start()
        else:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, 2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait)
            _remove_session_directory(directory)


class _Worker:
    def __init__(self, session_id: str, server: str) -> None:
        self.session_id = session_id
        self.server = server
        self.session: Session | None = None
        self.stopping = asyncio.Event()
        self.finished = asyncio.Event()
        self.connections: set[asyncio.Task[None]] = set()
        self.active: asyncio.Task[dict[str, Any]] | None = None
        self.event_writer: asyncio.StreamWriter | None = None
        self.lock = asyncio.Lock()
        self.inputs: dict[
            str, tuple[dict[str, Any], asyncio.Future[dict[str, Any]]]
        ] = {}
        self.notifications: deque[dict[str, Any]] = deque(maxlen=128)

    def status(self) -> dict[str, Any]:
        if self.finished.is_set():
            state = "closed"
        elif self.stopping.is_set():
            state = "closing"
        else:
            state = "busy" if self.active is not None else "idle"
        return {
            "session_id": self.session_id,
            "server": self.server,
            "state": state,
            "pid": os.getpid(),
            "pending_inputs": [
                event for event, future in self.inputs.values() if not future.done()
            ],
            "notifications": list(self.notifications),
        }

    async def emit(self, event: dict[str, Any]) -> None:
        if event.get("type") == "notification" and len(json.dumps(event)) <= 65536:
            self.notifications.append(event)
        if self.event_writer is not None:
            with suppress(OSError):
                await _send(self.event_writer, {"type": "event", "event": event})

    async def input(self, event: dict[str, Any]) -> dict[str, Any]:
        input_id = uuid4().hex
        pending = {**event, "input_id": input_id}
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self.inputs[input_id] = (pending, future)
        try:
            await self.emit(pending)
            return await future
        finally:
            del self.inputs[input_id]

    def respond(self, payload: dict[str, Any]) -> dict[str, Any]:
        input_id, response = payload.get("input_id"), payload.get("response")
        if not isinstance(input_id, str) or not isinstance(response, dict):
            raise ClientError(
                "invalid_request", "Expected an input ID and a response object"
            )
        match = self.inputs.get(input_id)
        if match is None or match[1].done():
            raise ClientError(
                "input_not_pending", "Session has no matching pending input"
            )
        match[1].set_result(response)
        return {"session_id": self.session_id, "input_id": input_id, "accepted": True}

    async def execute(
        self, method: str, params: dict[str, Any], writer: asyncio.StreamWriter
    ) -> dict[str, Any]:
        async with self.lock:
            assert self.session is not None
            if self.stopping.is_set() or self.session.closed:
                raise ClientError("session_closed", "Session is closing")
            self.active = asyncio.current_task()
            self.event_writer = writer
            try:
                return await self.session.request(method, params)
            except asyncio.CancelledError:
                self.stopping.set()
                raise
            finally:
                self.active = None
                self.event_writer = None

    async def request(
        self,
        payload: dict[str, Any],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> dict[str, Any]:
        method, params = payload.get("method"), payload.get("params", {})
        if not isinstance(method, str) or not isinstance(params, dict):
            raise ClientError(
                "invalid_request", "Expected a method and a parameter object"
            )
        operation = asyncio.create_task(self.execute(method, params, writer))
        disconnect = asyncio.create_task(reader.read(1))
        try:
            done, _ = await asyncio.wait(
                (operation, disconnect), return_when=asyncio.FIRST_COMPLETED
            )
            if operation in done and not operation.cancelled():
                return operation.result()
            raise ClientError(
                "cancelled",
                "Session request cancelled",
                outcome_unknown=method == "tools/call",
            )
        finally:
            if not operation.cancelling():
                operation.cancel()
            disconnect.cancel()
            await asyncio.gather(operation, disconnect, return_exceptions=True)

    async def dispatch(
        self,
        message: dict[str, Any],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> dict[str, Any]:
        payload = message.get("payload", {})
        if not isinstance(payload, dict):
            raise ClientError("invalid_request", "IPC payload must be an object")
        match message.get("action"):
            case "status":
                return self.status()
            case "request":
                return await self.request(payload, reader, writer)
            case "respond":
                return self.respond(payload)
            case "cancel":
                active = self.active
                if active is None or active.done():
                    return {**self.status(), "cancelled": False}
                self.stopping.set()
                await self.finished.wait()
                return {**self.status(), "cancelled": True}
            case "close":
                self.stopping.set()
                await self.finished.wait()
                return self.status()
            case _:
                raise ClientError("invalid_request", "Unknown session command")

    def accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.create_task(self.handle(reader, writer))
        self.connections.add(task)
        task.add_done_callback(self.connections.discard)

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            async with asyncio.timeout(_CONTROL_SECONDS):
                message = await _receive(reader)
            if message is not None:
                result = await self.dispatch(message, reader, writer)
                await _send(writer, {"type": "result", "result": result})
        except ClientError as error:
            with suppress(OSError):
                await _send(writer, {"type": "error", "error": error.as_dict()})
        except (OSError, TimeoutError):
            pass
        finally:
            await _close_writer(writer)


async def _serve(session_id: str, path: Path, server: str, identity: str) -> None:
    directory = _session_directory(session_id)
    socket = directory / "control.sock"
    try:
        registry = Registry(path)
        snapshot = registry.get(server)
        if snapshot.identity != identity:
            raise ClientError(
                "server_removed", "Server registration changed during startup"
            )
        worker = _Worker(session_id, server)
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, worker.stopping.set)
        listener: asyncio.Server | None = None
        try:
            async with open_session(
                registry,
                server,
                on_event=worker.emit,
                on_input=worker.input,
                snapshot=snapshot,
            ) as session:
                worker.session = session
                listener = await asyncio.start_unix_server(
                    worker.accept, socket, limit=_IPC_LIMIT
                )
                socket.chmod(0o600)
                stop = asyncio.create_task(worker.stopping.wait())
                expired = asyncio.create_task(session.wait_closed())
                try:
                    await asyncio.wait(
                        (stop, expired), return_when=asyncio.FIRST_COMPLETED
                    )
                finally:
                    worker.stopping.set()
                    active = worker.active
                    if (
                        not session.closed
                        and active is not None
                        and not active.cancelling()
                    ):
                        active.cancel()
                    listener.close()
                    stop.cancel()
                    expired.cancel()
                    await asyncio.gather(stop, expired, return_exceptions=True)
        finally:
            if listener is not None:
                listener.close()
            worker.finished.set()
            if worker.connections:
                with suppress(TimeoutError):
                    async with asyncio.timeout(1):
                        await asyncio.gather(
                            *worker.connections, return_exceptions=True
                        )
            if listener is not None:
                with suppress(TimeoutError):
                    async with asyncio.timeout(1):
                        await listener.wait_closed()
    finally:
        _remove_session_directory(directory)


if __name__ == "__main__":
    worker_id, registry_path, worker_server, server_identity = sys.argv[1:]
    asyncio.run(_serve(worker_id, Path(registry_path), worker_server, server_identity))
