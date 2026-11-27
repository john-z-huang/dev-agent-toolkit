# Skill 安装排查

安装或更新命令与验收条件见 [安装 Hook 索引](../hooks/index.md#安装与更新)。

## 包资源缺失与命令入口排查

出现“发布包缺少 Skill 资源”时，先核对是否调用了从发行包读取资源的管理入口。使用 checkout 时，从源码启动器预览，Python 将读取当前 checkout 中的 Skill。

原安装指定了 `--target` 时继续使用同一目标。

```bash
/bin/bash ./dev-agent-toolkit --skills-update --dry-run
```

若启动器找不到满足版本要求的 Python，可用相同条件查找本地解释器。

```bash
/bin/bash -c 'exec uv python find --system --no-python-downloads ">=3.11"'
```

若预览报告 Skill 源不完整，核对 checkout 中的 `skills/dev-agent-toolkit/SKILL.md`、引用资源和 `mcp-server/pyproject.toml`。若错误来自目标快照，保留目录和受管清单后按下节回读。

## 安装与更新中断处理

安装和更新共用同目标合作锁，竞争时停止。原子交换前后正式目录均为完整快照；强制终止可能留下 `.名称.skill-stage-*` 副本。先用 [Skill 合同](../hooks/install-skill.md) 中的 `--skills-show` 检查正式安装，再核对临时副本。锁文件保留以维持同一锁身份。

合作进程锁仅约束管理工具。更新期间暂停其他写入者；交换后检测到旧目录变化时，管理工具会撤回并保留现场。此机制不保证断电持久化。
