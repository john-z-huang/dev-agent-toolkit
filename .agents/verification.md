# 本地验证

## Python 代码格式化与静态检查

Code Agent 必须用 `ruff format` 处理 Python 代码格式，禁止通过 Edit、补丁或其他编辑工具手工修正格式。

从仓库根目录运行下列命令。前三条用 MCP 项目的 Ruff 配置覆盖 `mcp-server/`、`scripts/`、`skills/` 和 `tests/` 中的 Python 文件。最后一条用 ty 检查 `mcp-server/` 中的 Python 文件。

```bash
/bin/bash -c 'cd mcp-server && uv run --locked -- ruff format --config pyproject.toml . ../scripts ../skills ../tests'
/bin/bash -c 'cd mcp-server && uv run --locked -- ruff format --check --config pyproject.toml . ../scripts ../skills ../tests'
/bin/bash -c 'cd mcp-server && uv run --locked -- ruff check --no-fix --config pyproject.toml . ../scripts ../skills ../tests'
/bin/bash -c 'cd mcp-server && uv run --locked -- ty check'
```

`ruff format` 写入源码。其余命令用于检查。只格式化本次改动时，把目录参数换成目标文件。`codex-hooks/` 使用独立环境和配置，见 [Hooks 验证命令](../codex-hooks/README.md#验证)。

## 离线测试

在 `mcp-server/` 使用项目环境运行离线测试：

```bash
/bin/bash -c 'uv sync --managed-python && uv run --managed-python -- python -m unittest discover -s ../tests -v'
```

构建测试会在临时目录生成并解包 sdist、重建 wheel、安装到隔离环境后运行 CLI，不会写入现有用户 Skill 目录。

## OpenAI 官方 API 冒烟测试

`tests/openai_official_smoke.py` 使用统一客户端发起最小 Responses 请求，固定 `gpt-6.2-sol`、`medium` 推理强度和 512 token 输出上限，出站审核用 `gpt-6-luna`。只有显式传入 `--live` 才联网并产生实际 API 用量。不传参数输出 `skipped`，退出码为 2。常规离线测试验证该入口的行为。

先在终端中配置并导出所需的 API 和代理环境变量，再从 `mcp-server/` 目录通过 Bash 运行；Bash 子进程继承当前终端已导出的配置：

```bash
/bin/bash -c 'uv run --frozen -- python ../tests/openai_official_smoke.py --live'
```

测试按原拼写读取 `OPENAI_API_KEY_OFFICAL` 和 `OPENAI_BASE_URL_OFFICAL`，任一缺失或为空就停止，不能回退到其他配置。入口只在调用期间将它们映射为统一客户端要求的 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`，之后恢复原环境；生产客户端的配置规则保持不变。代理继续读取当前进程的标准代理变量，遵循 `NO_PROXY`。

输出仅含安全 JSON 状态、固定请求模型、成功时的 token 计数或失败分类，不输出真实配置、响应正文或原始异常。请求仅在超时时按统一配置重试，不切换模型；只有完整、未拒绝、模型匹配且结构正确的响应才返回 `success` 和退出码 0，失败退出码为 1。

## Codex App Server 测试已移除

本项目已移除 Codex App Server 专用测试用例、JSON-RPC 客户端和冒烟驱动。`tests/test_mcp_registration.py` 等仍验证标准 MCP stdio 初始化及工具发现；这些结果不代表 Codex App Server 集成测试已运行或通过。恢复条件与限制见 [MCP Server 开发原则](mcp-server-guidelines.md#codex-app-server-测试)。
