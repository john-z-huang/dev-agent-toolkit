"""Run a local MCP server in a process group supervised by a short-lived child."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager, closing, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.client._transport import TransportStreams

    from .registry import ServerConfig


_SERVER_ENV = "_DEV_AGENT_TOOLKIT_MCP_SERVER_ENV"
_POLL_MS = 40
_EOF_GRACE = 0.4
_TERM_GRACE = 0.25
_REAP_TIMEOUT = 0.5


@asynccontextmanager
async def managed_stdio(
    config: ServerConfig, *, environment: dict[str, str] | None = None
) -> AsyncGenerator[TransportStreams, None]:
    """Use the SDK's STDIO framing with an independent process group supervisor."""
    from mcp.client.stdio import StdioServerParameters, stdio_client

    from .registry import ClientError

    if sys.platform not in {"darwin", "linux"}:
        raise ClientError(
            "unsupported_platform", "Managed STDIO requires macOS or Linux."
        )

    # Pass the configured environment to the server only. Values must not affect
    # interpreter startup in the supervisor or appear in its command line.
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-I", "-S", str(Path(__file__).resolve()), config.command, *config.args],
        cwd=config.cwd,
        env={_SERVER_ENV: json.dumps(environment)} if environment else None,
    )
    async with stdio_client(parameters) as streams:
        yield streams


@contextmanager
def _leader_exit_check(pid: int) -> Generator[Callable[[], bool], None, None]:
    # Keep the leader unreaped until after group signals so its process group
    # ID cannot be reused, even if it exited before its descendants.
    if sys.platform == "linux":
        yield (
            lambda: (
                os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
                is not None
            )
        )
        return

    # Python 3.11 on macOS does not expose waitid().
    with closing(select.kqueue()) as queue:
        event = select.kevent(
            pid,
            filter=select.KQ_FILTER_PROC,
            flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
            fflags=select.KQ_NOTE_EXIT,
        )
        try:
            queue.control([event], 0)
        except ProcessLookupError:
            # A short-lived child can exit before the watch is registered.
            yield lambda: True
            return

        exited = False

        def check_exit() -> bool:
            nonlocal exited
            exited = exited or bool(queue.control(None, 1, 0))
            return exited

        yield check_exit


def _signal_group(group: int, signum: signal.Signals) -> bool:
    try:
        os.killpg(group, signum)
    except ProcessLookupError:
        return False
    except PermissionError:
        # macOS can report EPERM when the only remaining member is the
        # unreaped leader. Still attempt escalation and reap the leader.
        pass
    return True


def _reap_group(process: subprocess.Popen[bytes]) -> int:
    if _signal_group(process.pid, signal.SIGTERM):
        time.sleep(_TERM_GRACE)
        _signal_group(process.pid, signal.SIGKILL)
    try:
        return process.wait(timeout=_REAP_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("MCP server did not exit during cleanup.", file=sys.stderr)
        return 1


def _supervise(command: list[str]) -> int:
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    parent = select.poll()
    # The server reads this pipe directly. Observe writer closure without
    # consuming bytes, even if the pipe still contains unread requests.
    parent.register(sys.stdin.fileno(), select.POLLHUP)
    if stopping or parent.poll(0):
        return 0

    environment = os.environ.copy()
    environment.update(json.loads(environment.pop(_SERVER_ENV, "{}")))
    try:
        process = subprocess.Popen(command, env=environment, start_new_session=True)
    except (OSError, ValueError):
        print("MCP server could not be started.", file=sys.stderr)
        return 1

    try:
        with _leader_exit_check(process.pid) as leader_exited:
            while not stopping and not leader_exited():
                if parent.poll(_POLL_MS):
                    # Closing the SDK writer delivers EOF directly to the server.
                    # Keep both grace periods inside the SDK's shutdown window.
                    deadline = time.monotonic() + _EOF_GRACE
                    while not leader_exited() and time.monotonic() < deadline:
                        time.sleep(_POLL_MS / 1000)
                    break
    finally:
        status = _reap_group(process)
    return status if status >= 0 else 128 - status


if __name__ == "__main__":
    raise SystemExit(_supervise(sys.argv[1:]))
