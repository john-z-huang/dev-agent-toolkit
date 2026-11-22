"""使用已安装的 Markdown 模板创建和检查本地草稿。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "check"))
    parser.add_argument("kind", choices=("issue", "pr"))
    parser.add_argument("path", type=Path, help="草稿路径，父目录须已存在")
    parser.add_argument("--template", type=Path, help="使用指定模板覆盖默认结构")
    args = parser.parse_args()
    try:
        if args.action == "create":
            default_template = Path(__file__).resolve().parents[1] / "assets" / f"{args.kind}.md"
            source = (args.template or default_template).read_text(encoding="utf-8")
            with open(args.path, "x", encoding="utf-8",
                      opener=lambda name, flags: os.open(name, flags, 0o600)) as output:
                output.write(source)
        else:
            from validate_github_draft import validate_draft

            validate_draft(args.kind, args.path, args.template)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(args.path.absolute())


if __name__ == "__main__":
    # 受管 Skill 快照不应因运行脚本产生 __pycache__。
    sys.dont_write_bytecode = True
    main()
