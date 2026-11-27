# 安装与更新 Codex 全局 AGENTS.md

## 进入条件

需要从受管模板创建、接管或更新 Codex 全局指令。目标固定为当前用户的 `~/.codex/AGENTS.md`。项目指令及 Pi 指令继续由各自入口维护。

## 执行条件

从源码执行时核对当前 checkout 的 `instructions/codex-global.md`，需要其他模板时显式传入 `--source PATH`。两种入口均调用 `agents update`，正式操作会刷新共享 uv tool。已安装的完整包也可独立操作，省略 `--source` 时读取包内模板。

预览使用已安装的管理 CLI，核对差异、冲突和预计备份路径后执行同一资源的正式操作。预览不创建目录、备份、锁或受管记录。

```bash
/bin/bash ./dev-agent-toolkit --agents-update --dry-run
/bin/bash ./dev-agent-toolkit --agents-install
/bin/bash ./dev-agent-toolkit --agents-update
```

完整 wheel 安装后的独立入口可将预览命令中的 `--dry-run` 去掉执行写入。

```bash
/bin/bash -c 'tool_bin=$(uv tool dir --bin) && "$tool_bin/dev-agent-toolkit" agents update --dry-run'
/bin/bash -c 'tool_bin=$(uv tool dir --bin) && "$tool_bin/dev-agent-toolkit" agents show'
```

已有未知文件须明确获准接管并传入 `--adopt`。受管文件含本地修改时，审阅差异并明确获准替换后才传 `--replace-local`。模板可用 `{{HOME}}` 引用当前用户主目录，CLI 校验模板实际引用的绝对本地链接。内容相同的接管只建立受管记录。

实际改变既有文件前，先把原字节备份到 `~/.codex/AGENTS_BAK_<Unix秒时间戳>.md`。备份失败或同秒名称已占用时停止。更新原子替换目标文件，另写 `~/.codex/.AGENTS.md.dev-agent-toolkit.json` 受管记录，并使用持久合作锁。与外部编辑器并发或中断时，先核对实际目标、记录和备份，再决定如何恢复。保留已有备份和锁。

## 离开条件

用 `agents show` 核对目标状态和内容指纹。实际更改已有内容时，也核对本次备份。新会话读取更新后的全局指令。

## 重新进入条件

模板、目标内容、备份路径、受管记录或替换授权变化时，重新预览并核对变化。
