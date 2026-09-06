# DocAudit 文档索引

> 文档分区参照 Harmonization 治理体系（`governance` / `specification` / `user-manual`）。
> 文档职责分工见 [governance/documentation.md](governance/documentation.md)；SSOT 原则：信息只在一处定义，其余链接引用。

## governance/ — 治理

| 文档 | 角色 |
|------|------|
| [ai-review-prompt.md](governance/ai-review-prompt.md) | AI 深度审查 Prompt 模板（报告归档 `logs/reports/`，不入库） |
| [context.md](governance/context.md) | 领域背景、设计哲学、术语约定 |
| [project-structure.md](governance/project-structure.md) | 项目结构唯一信源（完整目录树 + 文件职责） |
| [documentation.md](governance/documentation.md) | 文档职责规范与同步链 |
| [tooling-pitfalls.md](governance/tooling-pitfalls.md) | 工具/脚本坑位清单（cmd/bat/pip/git） |
| [falsy-pitfalls.md](governance/falsy-pitfalls.md) | Python falsy 值误判检查清单 |
| [refactoring-plan.md](governance/refactoring-plan.md) | 重构计划（历史） |
| [remediation-plan-2026-08.md](governance/remediation-plan-2026-08.md) | 2026-08 整改计划（历史） |

## specification/ — 规格

| 文档 | 角色 |
|------|------|
| [specification.md](specification/specification.md) | 项目规格（功能/架构/质量） |
| [api-reference.md](specification/api-reference.md) | **函数签名唯一信源**（数字基准） |

## user-manual/ — 用户手册

| 文档 | 角色 |
|------|------|
| [user-manual.md](user-manual/user-manual.md) | 场景驱动的操作指南 |

## 相关入口

- 项目宪法：[AGENTS.md](../AGENTS.md)
- 规则配置（运行时，非文档）：[rules.md](../rules.md)
- 审查报告归档：`logs/reports/`（gitignore，不入库）
