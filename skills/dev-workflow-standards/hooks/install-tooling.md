# 构建与安装项目工具

## 进入条件

需要构建发行包，或只刷新 dev-workflow-standards 的 uv tool。若目标是更新已安装 Skill、全局指令、MCP 注册或原生 Hooks，直接使用 [对应合同](index.md)。

## 执行条件

核对源码 checkout、`mcp-server/pyproject.toml` 的版本及 `uv tool dir --bin` 对应的安装环境。构建写入仓库的 `dist/`，安装写入 uv tool 环境。构建或解析依赖可能联网。在源码根目录选择所需动作。

```bash
/bin/bash ./dws --uv-build
/bin/bash ./dws --uv-tool-install
```

安装命令默认使用 `dist/` 中与当前项目版本匹配的 wheel，缺少时先构建。更新或重装同版本 wheel 用 `/bin/bash ./dws --uv-tool-install --force`。指定其他 wheel 时，在操作参数后传 uv 选项及 wheel 路径。显式相对路径以调用目录为准。

每次将一个操作参数放在首位。`/bin/bash ./dws` 无参数只打印帮助。可在所选操作后加 `--help`。从其他目录调用时用 `dws` 的绝对路径，保持入口和源码组件的相对布局。Skill 和全局指令预览依赖已安装的管理 CLI。选择安装前核对它的来源。

## 离开条件

构建后核对 wheel 和 sdist 路径及版本。安装后用 `uv tool list --show-paths` 确认实际版本和入口，按目标验证入口。安装完成只证明 uv tool 环境已更新。发生部分成功时按 [恢复](recovery.md) 核对已生成产物及已安装版本。

## 重新进入条件

源码 checkout、版本、wheel、uv tool 环境或安装范围变化时，复核受影响部分。
