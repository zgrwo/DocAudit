# 文档职责规范

> 核心原则：**信息只在一处定义，其余各处链接引用（SSOT）**。

## 文档分工矩阵

| 文档 | 受众 | 核心问题 | 维护触发 |
|------|------|----------|----------|
| `AGENTS.md` | AI 助手 | "项目怎么组织？红线在哪？" | 架构/红线/流程变更 |
| `rules/context.md` | AI + 新人 | "术语什么意思？" | 新概念引入 |
| `rules/api-reference.md` | 开发者/AI | "函数签名是什么？"（**签名唯一信源**） | 任何 Public 接口变更 |
| `rules/user-manual.md` | 最终用户 | "我要做 X，怎么操作？" | 用户可见功能变更 |
| `rules/project-structure.md` | 开发者/AI | "代码在哪？"（**结构唯一信源**） | 文件新增/删除/移动 |
| `rules/code-review-prompt.md` | AI 审查 | "如何系统性审查？" | 审查维度演进 |
| `skills/*.md` | AI 编码 | "Python 有什么陷阱？" | 发现新陷阱 |

## 禁止事项

| ❌ 禁止 | 原因 |
|---------|------|
| 在多处重复定义同一信息 | 更新时必然遗漏 |
| 在代码注释中写使用教程 | 教程属于 user-manual.md |
| 在 api-reference 中写实现细节 | 只写签名和行为契约 |

## 同步更新链（DocAudit 特定：3 步注册）

```
新增 check_type
  → ① Auditor 方法实现
  → ② _DISPATCH 表注册
  → ③ _skip_checks 添加
  缺一不可！

新增 Public 接口
  → rules/api-reference.md
  → rules/user-manual.md（如为用户可见功能）

修改 rules.md 格式
  → 同步 rule_parser.py
```

## 审查检查项

- [ ] 变更内容属于该文档的职责范围
- [ ] 未在其他文档中重复定义同一信息
- [ ] 3 步注册已完成（如为新增 check_type）
- [ ] 数字/计数与 api-reference.md 一致
