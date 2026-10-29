---
name: rules
description: >
  DocAudit 审查规则声明格式（rules.md 编写规范）。
  新增 / 修改 rules.md 中的审查规则时使用。
last_updated: 2026-10-29
---

# rules.md 规则声明格式（rules）

`rules.md` 是规则配置的**唯一入口**（红线：不在代码中硬编码规则参数）。
本文件是入口指针，**格式规范的 SSOT** 在 `skills/python-SKILL.md` §3
（规则块格式 / regex 类型规则 / 新增 check_type 两步注册 §1.1）。

## 速查

规则块格式：

```markdown
## RULE-ID: 规则描述
- 严重度: error | warning | info
- 说明: 规则详细说明
- 检查: check_type        ← CHECK_REGISTRY 中的 key（_DISPATCH 自动派生）
```

regex 类型规则（`检查: regex`，无需注册注册表）：

```markdown
- 模式: "正则表达式"       ← 双引号包裹
- 建议: "修改建议"
```

## 改动前必检

1. 新增 check_type → 两步注册（Auditor 方法 + `CHECK_REGISTRY` 一行），
   见 `skills/python-SKILL.md` §1.1；验证：
   `CustomRulesAuditor.validate_dispatch()` 必须 `[]`
   （`_DISPATCH` / `_skip_checks` 由注册表派生，勿手改）
2. rules.md 格式变更 → 同步 `src/engines/rule_parser.py`（解析键名）
3. 规则数变更（当前 26 条）→ 同步 api-reference.md、tests/test_rules.py、
   ci.yml 断言与 test_gates 文档数字白名单
4. 严重度：无 `检查:` 键的 format 规则（FMT-001/002/004）经 `rule_severities`
   通道生效（2026-09-06 C-1）；有 `检查:` 键的规则由 dispatch 路径统一覆盖
5. 改完必须跑 `python src/cli.py rules validate`（配置错误显式失败）
