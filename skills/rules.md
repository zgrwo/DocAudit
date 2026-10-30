---
name: rules
description: >
  DocAudit 审查规则声明格式（rules.md 编写规范）。
  新增 / 修改 rules.md 中的审查规则时使用。
last_updated: 2026-11-05
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

阈值参数（规则块内，键名见 `rule_parser.py`）：

```markdown
- 关键词: [结论, 小结]        ← CON-004/005：结论关键词
- 最小数字个数: 1             ← CON-005：结论量化门槛
- 最小内容段落: 1             ← CON-006：章节实体内容门槛
- 最小字数: 20                ← CON-006
- 量词关键词: [厚度, 宽度]    ← CON-007：数值单位检查的量词前缀
- 豁免版式: [封面, Cover]     ← CON-004 / FMT-005 豁免版式
```

全局阈值（不在规则块内，写在文件头 frontmatter；未声明用代码默认值）：

```yaml
parameters:
  alignment_tolerance: 5.0     # FMT-ALIGN 对齐容差
  max_font_types: 3            # FMT-001 字体种类上限
  near_duplicate_similarity: 0.90
  conclusion_min_paragraphs: 3 # CON-004 判断 2
  table_fit_height_ratio: 1.15
  text_overflow_height_ratio: 1.15
  image_min_dpi: 150
  numeric_length_units: [nm, μm, um, mm, cm, m]
```

完整键表见 `src/engines/rule_parser.py::GLOBAL_PARAM_SPECS`（16 项）与
`rules.md` frontmatter；改阈值优先用 global parameters，不要写进代码。

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
3. 规则数变更（当前 30 条）→ 同步 api-reference.md、tests/test_rules.py、
   ci.yml 断言与 test_gates 文档数字白名单
4. 严重度：无 `检查:` 键的 format 规则（FMT-001/002/004）经 `rule_severities`
   通道生效（2026-09-06 C-1）；有 `检查:` 键的规则由 dispatch 路径统一覆盖
5. 改完必须跑 `python src/cli.py rules validate`（配置错误显式失败）
