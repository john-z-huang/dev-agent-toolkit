# 仓库开发文档

本目录只服务于开发和维护本仓库，不随 wheel/sdist 交付。仓库内开发的任务导航入口仍是根 [AGENTS.md](../AGENTS.md)；这里只记录规则和文档索引，不另设第二套路由。

## 交付边界

- 本目录可以链接交付内容；交付内容（`skills/`、`instructions/codex-global.md` 及其打包结果）不得链接或引用 `.agents/`。
- 面向使用者的安装与使用说明留在根 [README.md](../README.md) 和 [INSTALL.md](../INSTALL.md)。
- 删除、缺失或未安装 `.agents/` 不得影响安装、Skill 或全局 `AGENTS.md` 的使用。
- 打包白名单和硬编码路径见 [交付边界与发行包](distribution.md)。

## 名称空间

仓库根的 `.agents/` 与用户目录下的 `~/.agents/skills/<skill>` 同名但无关。前者只存在于源码仓库；后者是 Skill 的安装目标。不要因为名称相同而修改安装默认值。

## 文档索引

文件分工见根 [AGENTS.md](../AGENTS.md) 的任务导航表；本目录不再重复维护第二份清单。
