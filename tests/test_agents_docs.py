from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]

LINK = re.compile(r"\]\(\s*(<[^>]*>|[^)\s]+)")
FENCE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$", re.MULTILINE | re.DOTALL)
HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)


def strip_fences(text: str) -> str:
    """去掉围栏代码块，避免把示例里的链接写法当成真实链接。"""
    return FENCE.sub("", text)


def anchor_slug(heading: str) -> str:
    text = re.sub(r"[^\w\s-]", "", heading.strip().lower())
    return re.sub(r"\s+", "-", text)


class AgentsDocsTests(unittest.TestCase):
    """开发入口与 .agents/ 文档必须自洽，且不依赖仓库外的文件。"""

    def assert_links_resolve(self, document: Path) -> None:
        text = strip_fences(document.read_text())
        for target in LINK.findall(text):
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            url = urlsplit(target)
            if url.scheme or not url.path:
                continue
            linked = (document.parent / unquote(url.path)).resolve()
            self.assertTrue(linked.is_relative_to(ROOT), (document, target))
            self.assertTrue(linked.exists(), (document, target))
            if url.fragment and linked.is_file() and linked.suffix == ".md":
                anchors = {
                    anchor_slug(heading)
                    for heading in HEADING.findall(strip_fences(linked.read_text()))
                }
                self.assertIn(unquote(url.fragment), anchors, (document, target))

    def test_root_agents_navigation_links(self) -> None:
        self.assert_links_resolve(ROOT / "AGENTS.md")

    def test_root_readme_links(self) -> None:
        self.assert_links_resolve(ROOT / "README.md")

    def test_agents_directory_links(self) -> None:
        documents = sorted((ROOT / ".agents").rglob("*.md"))
        self.assertTrue(documents)
        for document in documents:
            with self.subTest(document=document.name):
                self.assert_links_resolve(document)


if __name__ == "__main__":
    unittest.main()
