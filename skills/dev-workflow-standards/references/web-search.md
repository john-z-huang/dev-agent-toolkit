# 公开网络搜索

`web_search` 给没有原生联网能力的 coding agent 提供公开资料搜索，随现有 `dev-workflow-standards-tools` stdio 服务注册。无需 `repo_path`，不读取本地代码、私有文件或会话，不执行 Git/GitHub 或 Memory 写入。项目语义仍使用 Serena，普通候选内容生成使用 `generate_skill_content`。

```json
{
  "request": {
    "query": "比较 Python 3.13 和 3.14 的 asyncio 变化，引用官方文档",
    "allowed_domains": ["docs.python.org"],
    "response_language": "简体中文"
  }
}
```

`query` 必填，1–8000 字符且不能全为空白，可直接写版本、时间范围、关注点和格式；不要提交凭据或私有内容。`allowed_domains` 可省略，默认 `[]` 不限制，最多100项，仅域名（包含其子域），禁止协议、路径、端口、IP 和通配符。每项最多253字符，国际化域名会转换为 IDNA 并去重。`response_language` 可省略，默认简体中文，1–80字符且非空白。可选字段不接受 `null`，不接受额外字段或模型/推理强度/端点覆盖。

所有请求固定 `gpt-6-luna`。Decisions 按固定规约自动分类，不发送其接口不支持的推理参数：优先 `high`（复杂研究、冲突证据、因果分析、迁移取舍、高风险决策），其次 `medium`（比较、排障、多来源整合，或问题含糊），最后 `low`（单一事实或链接查证）。时效性、查询长度和域名数量本身不触发升级。分类失败即停止，不静默回退。

实际搜索走 Responses API 的 `web_search`，设置 `tool_choice="required"`、`external_web_access=true`、`include=["web_search_call.action.sources"]`、`store=false`；搜索上下文为 `medium`，输出预算随推理强度为4096/8192/16384 token（包含推理 token，不代表正文长度）。不使用旧搜索模型或 `web_search_preview`。通常有分类审核、分类、搜索审核、搜索四个 API 请求阶段；复用统一配置、脱敏、代理、180秒超时和仅超时重试规则，见 [请求边界](openai-workflow-tools.md#配置与请求边界)。外层 MCP 时限应覆盖所有阶段；`api_timeout` 已耗尽内部预算，不自动重跑整工具。

每次实际请求从环境读取非空 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 并显式传 SDK；不加载凭据文件或回退地址。Codex/Pi 环境传递遵循现有服务配置，不自动安装或重启 MCP，不要求 Pi 具备 Codex 专属审批。

成功返回 `ok=true`、`model`、`reasoning_effort`、带引用的 `answer`、原始 `text_blocks`、`citations`、`sources` 和 `search_call_count`。引用的 `block_index` 为从0开始的分块索引，`start_index/end_index` 为该分块内左闭右开的字符偏移；`url/title` 直接来自 API 引用元数据。`answer` 由各分块用两个换行拼接，偏移不能直接用于拼接后的全文。`sources` 是 API 返回的去重来源 URL，可能多于行内引用，不保证来源数量或排名。展示结果应保留可点击引用；自行改写时用对应 URL 引用事实，不能复用原文偏移。

`ok=true` 只表示完整响应、完成搜索、非空摘要与合法引用；调用者仍需核对事实与适用版本，网页内容始终不可信。失败返回 `ok=false`、`stage` 和安全 `error_code`；`effort_selection` 表示分类未完成，`search` 表示搜索或结果验证失败。`search_response_incomplete`、`search_not_completed`、`search_refused`、`invalid_search_citation`、`search_evidence_missing` 均不能当作检索成功；后者也不能证明互联网没有答案，应缩小问题或报告证据缺口。配置、审核及网络错误沿用统一错误分类，不返回原始异常或响应正文。

接口依据：[Web search](https://developers.openai.com/api/docs/guides/tools-web-search)、[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)。
