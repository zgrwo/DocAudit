---
name: deep-code-review
description: >
  DocAudit 深度代码审查 Prompt 模板入口。
  对本项目做 PR 审查 / 发版前全量审查 / 修复复查（reaudit）时使用。
last_updated: 2026-09-06
---

# 深度代码审查（deep-code-review）

审查 Prompt 模板的**唯一定义处**在 `docs/governance/ai-review-prompt.md`（治理文档
承载，2026-09-06 5S 整改从本目录移入）。

执行深度审查前**必须完整 Read 该文件**，并严格遵守其中的：

- 铁律 0（`.venv` 全程忽略）与全局铁律（只读审查、每条 finding 带 `文件:行号` +
  对抗验证证据）
- 必跑基线（4.2，按变更类型裁剪）与八个审查维度（A–H）
- 假阳性专项（6.1–6.4，含负向注入）与对抗验证方法论（七）
- Finding 输出格式（八）与报告结构（九，末节必含「保持项」）

按场景选择用法：单 PR / 发版前全量 / 修复复查（reaudit），见该文件「一、使用说明」。
