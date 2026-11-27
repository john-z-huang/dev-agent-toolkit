"""按 Skill 模板校验 Issue 或 PR 的 Markdown 正文。"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_ISSUE_REFERENCE = re.compile(
    r"(?im)^ {0,3}(?:[-*+][ \t]+)?(?:Closes|Fixes|Resolves)[ \t]+#[1-9][0-9]*\b"
)


def _sections(markdown: str, *, include_code: bool = True) -> list[tuple[str, str]]:
    """按二级标题分节，代码块内的示例标题属于正文。"""
    sections = []
    heading = ""
    lines = []
    fence = ""
    for line in markdown.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1].startswith(fence) and not marker[2].strip():
                fence = ""
        elif marker:
            fence = marker[1]
        elif line.startswith("## "):
            if heading:
                sections.append((heading, "\n".join(lines).strip()))
            heading = line[3:].strip()
            lines = []
            continue
        if include_code or (not fence and not marker):
            lines.append(line)
    if heading:
        sections.append((heading, "\n".join(lines).strip()))
    return sections



def validate_draft(kind: str, path: Path, template: Path | None = None) -> None:
    default_template = Path(__file__).resolve().parents[1] / "assets" / f"{kind}.md"
    source = (template or default_template).read_text(encoding="utf-8")
    draft = path.read_text(encoding="utf-8")
    if any(hint in draft for hint in _COMMENT.findall(source)):
        raise ValueError("草稿仍包含模板填写提示")

    visible_draft = _COMMENT.sub("", draft)
    sections = _sections(visible_draft)
    expected = [title for title, _ in _sections(_COMMENT.sub("", source))]
    actual = [title for title, _ in sections]
    if not expected:
        raise ValueError("模板须至少包含一个二级标题")
    if actual != expected:
        raise ValueError(f"草稿二级标题须依次为 {'、'.join(expected)}")
    for title, body in sections:
        if not body:
            raise ValueError(f"章节尚未填写：{title}")

    if kind == "pr" and (template or default_template).resolve() == default_template:
        issue_body = dict(_sections(visible_draft, include_code=False)).get("关联 Issue", "")
        if not _ISSUE_REFERENCE.search(issue_body):
            raise ValueError("关联 Issue 一节须包含 Closes、Fixes 或 Resolves 加 #编号")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("issue", "pr"))
    parser.add_argument("path", type=Path, help="待校验的 Markdown 文件")
    parser.add_argument("--template", type=Path, help="使用指定模板覆盖默认结构")
    args = parser.parse_args()
    try:
        validate_draft(args.kind, args.path, args.template)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(args.path.absolute())


if __name__ == "__main__":
    main()
