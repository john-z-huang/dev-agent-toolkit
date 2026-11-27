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
_HUNK = re.compile(r"(?m)^(@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@)([^\n]*)\n?")
_DECLARATION = re.compile(
    r"^[+-](?:(?:async\s+)?def|class|fn|func|function|struct|interface|enum)\s+([\w$]+)"
)


class StagedDiffError(Exception):
    """An error code safe to return without exposing a diff or Git diagnostics."""


@dataclass(frozen=True)
class StagedFile:
    path: str
    status: str
    patch: str


@dataclass(frozen=True)
class StagedDiff:
    files: list[StagedFile]
    sha256: str

    @property
    def paths(self) -> list[str]:
        return sorted(file.path for file in self.files)

    def evidence(self, samples: int) -> list[EvidenceItem] | None:
        evidence = []
        for index, file in enumerate(self.files, 1):
            content = f"{file.status} {file.path}\n{_excerpt(file.patch, samples)}"
            if len(content) > 16000:
                return None
            evidence.append(
                EvidenceItem(
                    reference_id=f"S{index}",
                    origin="current_observation",
                    content=content,
                )
            )
        return evidence


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


def _representative_lines(lines: list[str], limit: int) -> list[str]:
    candidates = [line for line in lines if any(c.isalnum() for c in line[1:])]
    if limit == 0 or not candidates:
        return []
    if len(candidates) <= limit:
        return candidates
    if limit == 1:
        return [candidates[0]]
    return [candidates[i * (len(candidates) - 1) // (limit - 1)] for i in range(limit)]


def _excerpt(section: str, samples: int) -> str:
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
    for span, context, body in zip(
        sections[1::3], sections[2::3], sections[3::3], strict=True
    ):
        lines = [
            line[0] + line[1:].strip()
            for line in body.split("\n")
            if line.startswith(("+", "-"))
        ]
        added = [line for line in lines if line.startswith("+")]
        removed = [line for line in lines if line.startswith("-")]
        symbols = list(
            dict.fromkeys(
                f"{line[0]}{match[1]}"
                for line in lines
                if (match := _DECLARATION.match(line))
            )
        )
        heading = f"{span} +{len(added)}/-{len(removed)} {context.strip()[:100]}"
        if symbols:
            heading += f" [{', '.join(symbols[:6])}]"
        excerpts.append(heading)
        # Keep evidence of both sides, even when one side has far more lines.
        for side in (removed, added):
            excerpts.extend(line[:200] for line in _representative_lines(side, samples))
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

    files = []
    for metadata, filename, section in zip(
        records[::2], records[1::2], sections, strict=True
    ):
        try:
            path = filename.decode("utf-8")
            status = metadata.decode("ascii").split()[-1]
        except (UnicodeError, IndexError):
            raise StagedDiffError("staged_diff_unavailable") from None
        files.append(
            StagedFile(path, status, section.decode("utf-8", errors="replace"))
        )
    return StagedDiff(files, hashlib.sha256(patch).hexdigest())


async def read_staged_diff(root: str) -> StagedDiff:
    return _parse_patch(await _read_patch(root))
