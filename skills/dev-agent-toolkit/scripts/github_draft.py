"""创建和检查本地 Issue/PR 草稿的标题文件与 Markdown 正文。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _create_files(body: Path, title: Path, template: str) -> None:
    created = []
    try:
        for path, content in ((body, template), (title, "")):
            with open(
                path,
                "x",
                encoding="utf-8",
                opener=lambda name, flags: os.open(name, flags, 0o600),
            ) as output:
                created.append(path)
                output.write(content)
    except OSError:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "check"))
    parser.add_argument("kind", choices=("issue", "pr"))
    parser.add_argument("path", type=Path, help="Markdown 正文路径，父目录须已存在")
    parser.add_argument(
        "--title-file",
        type=Path,
        help="标题文件路径，默认同目录 <正文文件名去后缀>.title.txt",
    )
    parser.add_argument("--template", type=Path, help="使用指定模板覆盖默认结构")
    args = parser.parse_args()
    try:
        title_file = args.title_file or args.path.with_suffix(".title.txt")
        if args.action == "create":
            default_template = (
                Path(__file__).resolve().parents[1] / "assets" / f"{args.kind}.md"
            )
            source = (args.template or default_template).read_text(encoding="utf-8")
            _create_files(args.path, title_file, source)
        else:
            from validate_github_draft import validate_draft

            if not title_file.is_file():
                raise ValueError("标题文件须是已存在的普通文件")
            lines = title_file.read_text(encoding="utf-8").splitlines()
            if len(lines) != 1 or not lines[0].strip() or "\x00" in lines[0]:
                raise ValueError("标题文件须包含一行非空标题")
            validate_draft(args.kind, args.path, args.template)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(args.path.absolute())
    print(title_file.absolute())


if __name__ == "__main__":
    # 受管 Skill 快照不应因运行脚本产生 __pycache__。
    sys.dont_write_bytecode = True
    main()
