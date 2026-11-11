# Git 写操作与宿主审批

操作优先使用覆盖需求的 MCP 工具或已授权 Connector；没有对应工具、工具未暴露或功能未覆盖时，按 [`cli-fallback.md`](cli-fallback.md) 自行用 CLI 补足查询或已授权写入，无须仅因换入口再次请求授权。只读细节见 [`read-only-queries.md`](read-only-queries.md)。Codex MCP 配置使用 `default_tools_approval_mode="writes"`，让写工具在执行前进入 Codex 审批流程；CLI 遵守宿主命令审批和沙箱规则。执行层审批与用户意图授权独立；适用的宿主审批及用户授权均须满足。Pi 不提供 Codex 专属审批时按 [宿主兼容](../SKILL.md#宿主审批兼容) 执行，不安装或模拟 Codex 审批；实际权限门禁、扩展和校验仍须遵守。

CLI 补足须保留必要检查的目的与通过条件，不在工具拒绝后更换路径或执行器绕过审批。实际执行失败、必要检查无法完成或效果不明时保留现场，说明已完成步骤、失败原因及缺少条件。`fetch`、index/refs/配置修改均为本地写入；只读也可以联网，仍受宿主审批和沙箱限制。

本服务提供固定路径暂存和提交工具 `stage_repository_paths`、`commit_repository_changes`，但不提供任意命令或项目自定义测试工具。调用只读工具 `check_staged_changes` 时传入 `repo_path`，检查暂存区空白问题；是否运行项目测试按项目要求和用户指示处理。

仓库规则不能覆盖用户全局 AGENTS 或已安装 Skill 中的更高层限制。交付时核对并报告仍存在的冲突；不自动编辑全局配置或声称运行中服务已加载新说明。验证本仓库源码的初始化和工具发现，与验证已安装服务完成重载是两件事。
