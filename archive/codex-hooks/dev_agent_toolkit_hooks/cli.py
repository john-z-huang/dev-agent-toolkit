"""无参数处理标准输入事件；configure 子命令显式管理 Hooks 注册。"""

from __future__ import annotations

import sys
from importlib.metadata import version
from pathlib import Path

from . import registration, runtime


def main() -> int:
    arguments = sys.argv[1:]
    if arguments and arguments[0] == "configure":
        # 保留 uv tool 的稳定 bin 入口，不解析为虚拟环境中的版本路径。
        return registration.main(Path(sys.argv[0]).absolute(), arguments[1:])
    if arguments == ["--version"]:
        print(version("dev-agent-toolkit-hooks"))
        return 0
    if arguments in (["--help"], ["-h"]):
        print("用法：dev-agent-toolkit-hooks < event.json")
        print("      dev-agent-toolkit-hooks configure --help")
        return 0
    if arguments:
        print("不支持的参数；请用 --help 查看用法。", file=sys.stderr)
        return 2
    return runtime.main()
