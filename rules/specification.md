# DocAudit — 项目规格文档

> 版本：0.1.0 | 最后更新：2026-08-18 | 状态：Alpha 迭代中
> 事实唯一入口：**规则以 [rules.md](../rules.md) 为唯一入口**，测试清单/数字以 [AGENTS.md](../AGENTS.md) 为准。
> 接口签名 → [api-reference.md](api-reference.md) · 用户操作 → [user-manual.md](user-manual.md)

## 1. 项目概述

**DocAudit** 是一个本地离线文档审查系统，支持 PPTX/DOCX/PDF/Markdown 格式，提供结构审查、格式审查、事实审查、语言审查、自定义规则审查等 5 大审查维度，26 条配置驱动规则。

### 核心价值

- 完全离线：文档不上传任何服务器，所有处理在本地完成
- 配置驱动：rules.md 声明规则（规则唯一入口），无需修改代码
- 多格式支持：PPTX/DOCX/PDF/Markdown 统一审查
- 黄金测试：CLI / Web UI / Python API 真实三路径结果一致
- 半导体术语表：45+ 条专业术语 YAML 定义

### 目标用户

- 半导体/制造业技术文档工程师
- 需要批量审查技术报告的质量管理人员
- 需要术语一致性的文档团队

## 2. 功能规格

### 2.1 审查维度

| 维度 | Auditor | 检查内容 |
|------|---------|----------|
| 结构审查 | StructureAuditor | 标题页检测、标题层级递进、图表编号连续、必含章节、重复标题、每页结论 |
| 格式审查 | FormatAuditor | 字体一致性 (Run 级)、字号范围、单页文本密度、段落长度、元素溢出、空占位符、项目符号、表格对比度 |
| 事实审查 | FactualAuditor | 数值跨页一致性、缩写定义管理、重复定义检测 |
| 语言审查 | LanguageAuditor | 语法拼写（LanguageTool）、中英混排、术语一致性、禁用词汇 |
| 自定义规则 | CustomRulesAuditor | rules.md 配置的 26 条规则（委托模式路由，不包含检查逻辑） |
| 内置检查 | LanguageAuditor 等 | FMT-MIXED / VOCAB-REJECT / PY-SPELL / PY-ZH-GRAMMAR（不经 rules.md 配置） |

### 2.2 规则清单（26 条，以 rules.md 为唯一入口）

> 规则声明、严重度、阈值、check_type 全部以 `rules.md` 为准，本表仅为速览；
> 新增/修改/删除规则只编辑 `rules.md`，本文件不重复维护规则定义。

| 规则 ID | 类型 | 说明（摘自 rules.md） |
|---------|------|----------------------|
| STR-001 | structure | 必须有标题页：第一页必须使用标题版式 |
| STR-002 | structure | 图表编号连续性：所有图/表编号必须连续（Fig.1 → Fig.2 → ...），不允许跳号 |
| STR-003 | structure | 标题层级不跳级：标题层级应逐步递进（H1 → H2 → H3，不应 H1 → H3） |
| STR-004 | structure | 标题长度限制：幻灯片标题不应过长（10 个英文词 / 40 个中文字上限） |
| STR-005 | structure | 禁止重复标题：不同幻灯片不应使用完全相同的标题 |
| STR-006 | structure | 标题末尾禁止标点：标题末尾不应使用句号、逗号等标点符号 |
| STR-007 | structure | 图表标题格式一致性：图表标题编号格式应全文统一 |
| STR-008 | structure | 幻灯片版式多样性：不应全部使用完全相同版式 |
| FMT-001 | format | 正文字体统一：正文必须使用指定字体之一 |
| FMT-002 | format | 标题字号范围：标题 28-40pt，正文 12-22pt |
| FMT-003 | format | 每页文本量限制：单页文本不应过于密集 |
| FMT-004 | format | 单段不超过 3 行：单个段落不应过长 |
| FMT-005 | format | 元素不超出页面边界：文本框/图片/表格不得超出幻灯片边界 |
| FMT-006 | format | 空占位符检测：不应有未填充内容的空白占位符 |
| FMT-007 | format | 项目符号样式一致性：同一页不应混用多种项目符号样式 |
| FMT-008 | format | 表格文字与底色对比度：深底配浅字/浅底配深字（WCAG AA） |
| TERM-001 | terminology | 先进封装术语：fan-out 应使用完整术语（regex） |
| TERM-002 | terminology | 硅通孔术语：through silicon via 首次出现应标注缩写（regex） |
| TERM-003 | terminology | 中英文混用规范：英文术语首次出现应附带中文翻译（regex） |
| CON-001 | factual | 数值一致性：同一指标在前文出现过的数值应保持一致 |
| CON-002 | factual | 必须包含的章节：技术报告必须包含概述/工艺流程/关键参数/结论 |
| CON-003 | factual | 缩写首次定义：技术缩写首次出现时必须给出全称 |
| CON-003-A | factual | 缩写定义后未再使用：定义可能多余 |
| CON-003-B | factual | 缩写重复定义：同一技术缩写在文档中被多次定义 |
| CON-003-C | factual | 缩写在定义前使用：读者可能不理解 |
| CON-004 | factual | 每页须有结论：每一页必须有明确的结论或关键要点 |

> 共 26 条规则；TERM-001~003 为 regex 类型（由 CustomRulesAuditor 的 `_execute_regex_rule()` 直接处理），
> 其余经 `_DISPATCH` 表委托到对应 Auditor 检查方法。

### 2.3 关键技术特性

- **委托模式**：CustomRulesAuditor 是"路由器"，通过 `_DISPATCH` 表委托到对应 Auditor，不含检查逻辑
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

- 底层不感知上层（Model 不引用 Auditor，Engine 不引用 UI）
- CustomRulesAuditor 是"路由器"，不含检查逻辑
- 禁止反向依赖或跨层调用

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

### 4.1 测试体系（以 AGENTS.md 为准）

> 精确测试用例数与测试文件清单以 **AGENTS.md** 为准（数字由主代理统一同步）；
> 本表为 2026-08-18 快照，并行工作包持续新增测试文件，最新清单见 AGENTS.md 测试表。

| 文件 | 内容 |
|------|------|
| test_models.py | Document + AuditFinding 模型 |
| test_auditors.py | Structure + Format + Factual 审计器 |
| test_engines.py | Terminology + Vocabulary + 语言分段 + LanguageTool 客户端 |
| test_rules.py | 规则解析 + DISPATCH 验证 |
| test_integration.py | 全流水线 + 黄金测试 + CLI 参数解析回归 |
| test_autofix.py | AutoFixer 修复链路 |
| test_converters.py | 四格式转换器 |
| test_edge_cases.py | 边界输入 |
| test_language_auditor.py | 语言审计器细节 |
| test_scripts.py | scripts/ 工具（common + setup_offline + 锁文件解析） |
| test_contrast.py | FMT-008 WCAG 对比度算法 + 表格检查 |
| test_check_doc_numbers.py | 文档数字一致性检查器门禁 |
| test_check_bare_handlers.py | 裸异常检查器门禁 |
| test_check_api_sync.py | API 同步检查器门禁 |
| test_check_html_escape.py | HTML 转义检查器门禁 |
| test_check_skill_sync.py | Skill 双份维护检查器门禁 |
| test_cli_exit_codes.py | CLI 退出码契约（处理失败 → exit 1） |
| test_golden_paths.py | 黄金测试真实三路径（CLI/WebUI/Python API） |
| test_rule_coverage.py | 规则断言覆盖测试（STR/CON/FMT 定向补盲） |
| test_html_report_security.py | HTML 转义红线安全测试 |
| test_app_ui.py | Web UI 纯函数/冒烟测试 |

### 4.2 黄金测试（真实三路径）

黄金测试验证 **CLI / Web UI / Python API 三条真实执行路径**为同一输入产生完全相同的发现：

- 路径 1 Python API：直接调用 converter + build_auditors + run_auditors
- 路径 2 真实 CLI：subprocess 运行 `python src/cli.py <file> -o <tmp>.json`，读取 JSON 报告的 findings
- 路径 3 真实 Web UI：Streamlit AppTest 注入文件驱动 app.py，读取 session_state 中的 findings

比对维度（排除随机 id）：
- finding count 一致
- severity distribution 一致
- type distribution 一致
- rule_id 分布一致
- dedup key 集合全维度比对

### 4.3 已知限制

- PPTX 位置单位：EMU (python-pptx) vs pt (Document 模型)，需 `/12700` 转换
- Group 子元素：必须用 `page.flattened_elements` 递归展开，不直接遍历 `page.elements`
- LanguageTool：需本地服务（Docker / Java 子进程），不可用时降级跳过语法检查，不阻塞整体审查

## 5. 历史演化摘要

> 截至 2026-08-18，仓库共 **33 个 commits**（`git rev-list --count HEAD` 实测）。

| 阶段 | 关键事件 |
|------|----------|
| v0.1.0 初始交付（2026-07-26） | 完整四维审查系统一次性交付：PPTX/DOCX/PDF/MD 转换器、5 Auditor 流水线、Streamlit Web UI、CLI、HTML/JSON 报告、LanguageTool 三层降级、半导体术语表 |
| 文档体系与规则凝练 | 文档体系建立（AGENTS / README / rules/）、rules.md 规则声明收敛与去冗余 |
| 深度审查修复批次（2026-08） | 多轮 max level 审查修复：STR-003 跳级误报、TERM-003 中英混排降噪、缩写扫描缓存绑定文档、Vocabulary 编码回退、setup_offline 完全离线加固等 |
| 工程化与门禁（2026-08） | check_doc_numbers / check_bare_handlers / check_api_sync 门禁上线、锁文件可复现、CI 矩阵增强、5S 整理（Prompt/审查报告归位 .qoder） |
| 本批次整改（2026-08-18） | 幻影规格重写、CLI 处理失败退出码修复、文档事实冲突修正（详见 CHANGELOG） |

## 6. 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Web UI | Streamlit | 快速原型，单用户本地使用 |
| 规则配置 | rules.md | 用户可编辑，无需代码 |
| 术语表 | YAML | 结构化，易于维护 |
| 语言检查 | LanguageTool | 开源，支持中英文；三层降级保离线可用 |
| 报告格式 | HTML + JSON | 可视化 + 程序化处理 |

<!-- last_updated: 2026-08-18 -->
