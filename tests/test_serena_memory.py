from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from mcp import Client, StdioServerParameters


class SerenaMemoryTests(IsolatedAsyncioTestCase):
    async def test_stdio_memory_tools_stay_in_the_startup_project(self) -> None:
        package_root = Path(__file__).resolve().parents[1] / "mcp-server"
        bootstrap = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from dev_workflow_standards_tools.server import main; main()"
        )
        with TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            memory = project / ".serena" / "memories"
            memory.mkdir(parents=True)
            file = memory / "plan.md"
            original = "旧记录\r\nResult\r\n完成".encode()
            file.write_bytes(original)
            outside = root / "outside.md"
            outside.write_text("outside", encoding="utf-8")
            (memory / "link.md").symlink_to(outside)

            params = StdioServerParameters(
                command=sys.executable,
                args=["-B", "-c", bootstrap, str(package_root)],
                cwd=project,
                env={},
            )
            async with asyncio.timeout(20), Client(params) as client:
                async def call(name: str, **arguments):
                    result = await client.call_tool(name, arguments)
                    self.assertFalse(result.is_error, result.content)
                    self.assertIsNone(result.structured_content)
                    return json.loads(result.content[0].text)

                tail = await call(
                    "serena_memory_tail_read", memory_path="mem:plan.md", tail_lines=2
                )
                self.assertEqual(tail["content"], "Result\r\n完成")
                self.assertEqual(
                    (tail["total_lines"], tail["start_line"], tail["end_line"]), (3, 2, 3)
                )
                for expected, matches in (("Result", True), ("result", False)):
                    check = await call(
                        "serena_memory_write_check",
                        memory_path="plan",
                        changed_content=expected,
                        tail_lines=2,
                    )
                    self.assertIs(check["success"], matches)
                    self.assertNotIn("content", check)

                for name, reason in (
                    ("../outside", "memory_path_invalid"),
                    ("global/example", "memory_path_invalid"),
                    ("link", "memory_symlink_rejected"),
                ):
                    rejected = await call(
                        "serena_memory_tail_read", memory_path=name, tail_lines=1
                    )
                    self.assertEqual(
                        (rejected["status"], rejected["reason_code"]), ("unavailable", reason)
                    )
                invalid = await client.call_tool(
                    "serena_memory_tail_read", {"memory_path": "plan", "tail_lines": "2"}
                )
                self.assertTrue(invalid.is_error)
            self.assertEqual(file.read_bytes(), original)
