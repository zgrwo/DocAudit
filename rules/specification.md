# DocAudit — 项目规格文档

> 版本：v1.0.0 | 最后更新：2026-07-26 | 状态：功能完备，稳定发行中

## 1. 项目概述

**DocAudit** 是一个本地离线文档审查系统，支持 PPTX/DOCX/PDF/Markdown 格式，提供结构审查、格式审查、事实审查、语言审查、自定义规则审查等 5 大审查维度，25 条配置驱动规则。

### 核心价值

- 完全离线：文档不上传任何服务器，所有处理在本地完成
- 配置驱动：rules.md 声明规则，无需修改代码
- 多格式支持：PPTX/DOCX/PDF/Markdown 统一审查
- 黄金测试：CLI=WebUI=Python 三路径结果一致
- 半导体术语表：45+ 条专业术语 YAML 定义

### 目标用户

- 半导体/制造业技术文档工程师
- 需要批量审查技术报告的质量管理人员
- 需要术语一致性的文档团队

## 2. 功能规格

### 2.1 审查维度

| 维度 | Auditor | 检查内容 |
|------|---------|----------|
| 结构审查 | StructureAuditor | 标题层级/目录完整性/章节编号 |
| 格式审查 | FormatAuditor | 字体/字号/颜色/对齐/页边距 |
| 事实审查 | FactualAuditor | 日期/数字/单位/引用一致性 |
| 语言审查 | LanguageAuditor | 术语/词汇/语法（LanguageTool） |
| 自定义规则 | CustomRulesAuditor | rules.md 配置的 25 条规则 |

### 2.2 规则清单（25 条）

| 规则 ID | 类型 | 说明 |
|---------|------|------|
| STR-001 | structure | 标题层级不跳跃 |
| STR-002 | structure | 目录与章节一致 |
| FMT-001 | format | 正文字体统一 |
| FMT-002 | format | 正文字号范围 |
| FMT-003 | format | 标题字体统一 |
| FMT-008 | format | 表格底色 vs 字体色 WCAG 对比度 (深底浅字/浅底深字) |
| CON-001 | factual | 日期格式一致 |
| CON-002 | factual | 数字单位一致 |
| LANG-001 | language | 术语白名单 (TERM-{category}) |
| LANG-002 | language | 词汇黑名单 (VOCAB-REJECT) |
| CUSTOM-001~016 | custom | 用户自定义规则 |

### 2.3 关键技术特性

- **委托模式**：CustomRulesAuditor 是"路由器"，通过 `_DISPATCH` 表委托到对应 Auditor
- **三步注册法**：新增 check_type 需同步 Auditor 方法 + `_DISPATCH` 表 + `_skip_checks`
- **配置流**：rules.md → rule_parser.py → extract_auditor_config() → Auditor
- **降级策略**：LanguageTool 不可用时跳过语法检查，不阻断流程

## 3. 架构规格

### 3.1 七层单向依赖

```
UI/CLI 层 (app.py / cli.py)
    ↓
Reporter 层 (HTML/JSON 报告)
    ↓
Auditor 层 (5 个 Auditor)
    ↓
Engine 层 (6 个引擎)
    ↓
Converter 层 (PPTX/DOCX/PDF/MD → Document)
    ↓
Model 层 (Document, AuditFinding)
    ↑
Config 层 (横切：rules.md, glossary/, vocab/)
```

### 3.2 模块依赖

| 模块 | 依赖 |
|------|------|
| custom_rules.py | 委托到 structure.py, format.py, factual.py |
| pipeline.py | 编排全部 5 个 Auditor，调用 rule_parser.py |
| language.py | 调用 languagetool.py, terminology.py, vocabulary.py |
| 其余 | 相互独立，单向向下 |

### 3.3 数据流

```
输入文件 → Converter → Document 模型
                          ↓
                    Auditor 层（5 个并行）
                          ↓
                    List[AuditFinding]
                          ↓
                    Reporter → HTML/JSON 报告
```

## 4. 质量规格

### 4.1 测试体系（158 个用例）

| 文件 | 内容 |
|------|------|
| test_models.py | Document + AuditFinding 模型 |
| test_auditors.py | Structure + Format + Factual 审计器 |
| test_engines.py | Terminology + Vocabulary + 语言分段 |
| test_rules.py | 规则解析 + DISPATCH 验证 |
| test_integration.py | 全流水线 + 黄金测试 |

### 4.2 黄金测试

`test_web_ui_path_equals_cli_path_equals_python_path` 验证 3 个执行路径为同一输入产生完全相同的发现：
- finding count 一致
- severity distribution 一致
- type distribution 一致
- dedup key sets 全维度比对

### 4.3 已知限制

- PPTX 位置单位：EMU (python-pptx) vs pt (Document 模型)，需 `/12700` 转换
- Group 子元素：必须用 `page.flattened_elements`，不直接遍历 `page.elements`
- LanguageTool：需 Docker 运行，不可用时降级跳过

## 5. 历史演化摘要

| 阶段 | commits | 关键事件 |
|------|---------|----------|
| 初始提交 | 1 | v0.1.0 完整功能一次性提交 |
| 文档重构 | 1 | 文档体系 + 6 项功能增强 |
| 规则凝练 | 1 | CLAUDE.md + rules.md 去冗余 |
| 深度审查 | 2 | 3 轮 41 项修复 + SmartExcel 对齐 |
| 健壮性修复 | 1 | 空值安全/边界情况/bug 修正 |
| 发行准备 | 1 | 11 项问题修复 + CI 发布 |

**总计**：7 commits（最少，但初始提交已包含完整功能）

## 6. 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Web UI | Streamlit | 快速原型，单用户本地使用 |
| 规则配置 | rules.md | 用户可编辑，无需代码 |
| 术语表 | YAML | 结构化，易于维护 |
| 语言检查 | LanguageTool | 开源，支持中英文 |
| 报告格式 | HTML + JSON | 可视化 + 程序化处理 |
