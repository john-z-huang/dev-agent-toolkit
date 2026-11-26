# Skill 安装排查

安装或更新命令与验收条件见 [安装 Hook 索引](../hooks/index.md#安装与更新)。

## 包资源缺失与命令入口排查

“发布包缺少 Skill 资源；请从完整 wheel 安装工具”表示当前导入的包无法读取 `skill_bundle/manifest.json` 或清单中的资源文件。这项检查先于目标 Skill 目录检查。

先通过 uv 工具的明确入口执行只读预览。原安装指定了 `--target` 时继续使用同一目标。

```bash
/bin/bash -c 'tool_bin=$(uv tool dir --bin) && "$tool_bin/dev-workflow-standards" skills update --dry-run'
```

若该预览成功而裸命令失败，应在执行管理命令的 Bash 终端中检查同名命令解析。`PATH` 顺序、别名、函数或命令缓存可能选中另一份安装。

```bash
/bin/bash -c 'type -t dev-workflow-standards'
/bin/bash -c 'type -a -p dev-workflow-standards'
/bin/bash -c 'uv tool dir --bin'
```

项目的可编辑 Python 环境可能导入缺少 `skill_bundle` 的源码包。Skill 管理命令应使用从完整 wheel 安装的入口。若明确的 uv tool 入口仍失败，检查安装来源与包内资源，并按已核验的完整 wheel 重新安装，保留目标目录与受管清单。

## 安装与更新中断处理

安装和更新共用同目标合作锁，竞争时停止。原子交换前后正式目录均为完整快照；强制终止可能留下 `.名称.skill-stage-*` 副本。先用 [Skill 合同](../hooks/install-skill.md) 中的 `skills show` 检查正式安装，再核对临时副本。锁文件保留以维持同一锁身份。

合作进程锁仅约束管理工具。更新期间暂停其他写入者；交换后检测到旧目录变化时，管理工具会撤回并保留现场。此机制不保证断电持久化。
