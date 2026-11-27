"""Read a bounded, immutable view of the staged changes for commit drafting."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from contextlib import suppress
from dataclasses import dataclass

from .ai_workflow import EvidenceItem

_MAX_DIFF_BYTES = 256 * 1024
_MAX_EVIDENCE_BYTES = 24 * 1024
_HUNK = re.compile(r"(?m)(^@@ [^\n]+$)\n?")


class StagedDiffError(Exception):
    """An error code safe to return without exposing a diff or Git diagnostics."""


@dataclass(frozen=True)
class StagedDiff:
    paths: list[str]
    sha256: str
    evidence: list[EvidenceItem]


async def _read_patch(root: str) -> bytes:
    try:
        async with asyncio.timeout(15):
            process = await asyncio.create_subprocess_exec(
                "git",
                "--no-pager",
                "--no-optional-locks",
                "--no-lazy-fetch",
                "diff",
                "--cached",
                "--no-ext-diff",
                "--no-textconv",
                "--no-color",
                "--no-renames",
                "--submodule=short",
                "--ignore-submodules=dirty",
                "--src-prefix=a/",
                "--dst-prefix=b/",
                "--no-abbrev",
                "--full-index",
                "--patch-with-raw",
                "--unified=0",
                "-z",
                "--",
                cwd=root,
                env={**os.environ, "LC_ALL": "C"},
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                assert process.stdout is not None
                try:
                    await process.stdout.readexactly(_MAX_DIFF_BYTES + 1)
                except asyncio.IncompleteReadError as end:
                    if await process.wait() != 0:
                        raise StagedDiffError("staged_diff_unavailable") from None
                    return end.partial
                raise StagedDiffError("staged_diff_too_large")
            finally:
                if process.returncode is None:
                    with suppress(ProcessLookupError):
                        process.kill()
                    await process.communicate()
    except (OSError, TimeoutError) as error:
        raise StagedDiffError("staged_diff_unavailable") from error


def _excerpt(section: str) -> str:
    sections = _HUNK.split(section)
    if len(sections) == 1:
        return "\n".join(
            line
            for line in section.split("\n")
            if line.startswith(
                ("old mode ", "new mode ", "Binary files ", "Submodule ")
            )
        )
    excerpts = []
    for header, body in zip(sections[1::2], sections[2::2], strict=True):
        lines = [line for line in body.split("\n") if line.startswith(("+", "-"))]
        if len(lines) > 6:
            lines = [lines[i * (len(lines) - 1) // 5] for i in range(6)]
        excerpts.extend([header[:240], *(line[:200] for line in lines)])
    return "\n".join(excerpts)


def _parse_patch(patch: bytes) -> StagedDiff:
    if not patch:
        raise StagedDiffError("no_staged_changes")
    raw, separator, unified = patch.partition(b"\0\0")
    records = raw.split(b"\0")
    sections = re.split(rb"(?m)^diff --git ", unified)[1:]
    if not separator or len(records) % 2 or len(records) // 2 != len(sections):
        raise StagedDiffError("staged_diff_unavailable")
    if len(sections) > 99:
        raise StagedDiffError("staged_diff_too_large")

    evidence = []
    paths = []
    size = 0
    for index, (metadata, filename, section) in enumerate(
        zip(records[::2], records[1::2], sections, strict=True), 1
    ):
        try:
            path = filename.decode("utf-8")
            status = metadata.decode("ascii").split()[-1]
        except (UnicodeError, IndexError):
            raise StagedDiffError("staged_diff_unavailable") from None
        content = (
            f"暂存路径 {path}，Git 状态 {status}。以下保留各 hunk 的范围与变更行摘录。\n"
            + _excerpt(section.decode("utf-8", errors="replace"))
        )
        size += len(content.encode("utf-8"))
        if len(content) > 16000 or size > _MAX_EVIDENCE_BYTES:
            raise StagedDiffError("staged_diff_too_large")
        evidence.append(
            EvidenceItem(
                reference_id=f"S{index}",
                origin="current_observation",
                content=content,
            )
        )
        paths.append(path)
    return StagedDiff(sorted(paths), hashlib.sha256(patch).hexdigest(), evidence)


async def read_staged_diff(root: str) -> StagedDiff:
    return _parse_patch(await _read_patch(root))
