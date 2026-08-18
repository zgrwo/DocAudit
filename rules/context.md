# DocAudit 项目上下文

> 领域知识、设计理念、技术选型。回答"为什么"而非"怎么做"。
> 怎么做 → [用户手册](user-manual.md) · [API 参考](api-reference.md) · [项目结构](project-structure.md)

---

## 领域背景：半导体文档审查的独特需求

半导体先进封装团队日常产生大量技术文档：工艺整合报告 (PIR)、DOE 实验报告、技术评审 PPT、良率分析报告、FMEA 文档。这些文档有几个共同特征：

1. **术语密度极高** — 一页幻灯片可能出现 5-8 个技术缩写 (TSV, FOWLP, CoWoS, EMIB, UBM, RDL, C4...)，且必须在首次出现时定义
2. **中英混排是常态** — 中文论述 + 英文术语 + 数值+单位，混排格式问题频发
3. **图表编号和数值引用严格** — Fig.1 → Fig.2 → Fig.3 不能跳号，良率数值跨页必须一致
4. **格式规范因地而异** — 不同客户 (Intel/TSMC/ASE) 有不同字体、版式、字号要求
5. **数据安全红线** — 工艺参数、良率数据是核心机密，不能上传任何云端服务

通用文档审查工具 (Grammarly, PerfectIt, Vale) 不理解半导体领域，无法处理：
- `FinFET` 不是拼写错误
- `TSV (Through Silicon Via, 硅通孔)` 的中英对照格式
- `µm` vs `um` 的单位规范
- 工艺报告中"图1"和"Fig.1"的格式混用

DocAudit 专门为此场景构建。

---

## 为什么是四维审查

| 维度 | 审查内容 | 回答什么问题 |
|------|----------|-------------|
| 📐 **内容结构** | 标题页、标题层级、图表编号、必含章节、结论 | "文档逻辑完整吗？" |
| 🎨 **格式规范** | 字体、字号、对齐、元素溢出、文本密度 | "文档看起来专业吗？" |
| 📝 **语言文字** | 语法拼写、中英混排、术语规范、禁用词 | "文档表达准确吗？" |
| 🔬 **事实精准** | 数值跨页一致性、缩写定义 | "文档内容可信吗？" |

四个维度覆盖了从"形式"到"内容"的递进层次——不做语义理解（那是 LLM 的事），而是做确定性、可配置、可追溯的审查。

---

## 为什么是 PPTX-first

1. 半导体团队的核心交付物是 PPT（技术评审、设计评审、项目汇报）
2. PPTX (OOXML) 提供的元数据最丰富：字体/字号/颜色精确到 Run、位置精确到 EMU、版式名称、占位符类型
3. 可以做到 Run 级的格式精确定位，而不是"这页有问题"的模糊告警
4. DOCX / PDF / MD 作为补充格式，填充同一 Document 模型的子集字段

---

## 为什么完全离线

- 工艺参数是核心机密 — 良率、CPK、缺陷密度、工艺窗口
- 客户合同中通常有数据本地化条款
- LanguageTool 三层降级设计 (Docker → Java 子进程 → Python 内置) 确保零网络环境也能跑
- 没有任何数据上报逻辑、没有遥测、没有云端 API 调用

---

## 设计哲学

### 配置驱动 (Configuration over Code)

```
rules.md → rule_parser → extract_auditor_config() → Auditor(config={...})
```

非程序员编辑 `rules.md` 即可调整审查行为（字体白名单、字号范围、必含章节），无需改 Python 代码。规则声明和规则执行解耦。

### 统一模型 (Unified Document Model)

所有格式转换到同一个 `Document → Page → PageElement → Paragraph → Run` 体系。审查器只认统一模型，不关心原始格式。新增格式只需新增 Converter，审查器零改动。

### 优雅降级 (Graceful Degradation)

- LanguageTool: Docker → Java 子进程 → Python 内置，零外部依赖也能跑基础检查
- PDF Converter: Docling → 回退 Markdown 导出
- PPTX 元数据丰富的检查（字体/溢出/版式）在 MD/PDF 上自动跳过

### 委托模式 (Delegation Pattern)

CustomRulesAuditor 不包含任何检查逻辑 — 所有 check 类型通过 `_DISPATCH` 表委托给对应 Auditor 的内部方法。CustomRulesAuditor 是"路由器"，不是"执行者"。

---

## 技术选型理由

| 技术 | 选型理由 |
|------|---------|
| **python-pptx** | OOXML 解析，Run 级字体/位置提取，兼写修复 |
| **python-docx** | OOXML 解析，DOCX 读写 |
| **Streamlit** | 纯 Python Web UI，零前端代码，适合内部工具 |
| **YAML** | 术语表人类可读可编辑，比 JSON 更适合非程序员维护 |
| **pyspellchecker** | 纯 Python 英文拼写检查（三层降级的最后防线） |

> **中英混排分段实现**：不依赖分词器 — `LanguageAuditor._segment_by_language()` 逐字符扫描
> （CJK 字符判定 + ASCII 字母判定）将混合文本切分为语言段；数字/标点/空格等中性字符
> 保持当前语言不切换，过短的连续同语言段自动合并。确定性、零外部依赖，
> LanguageTool 分语言检查与术语检查均基于该分段结果（见 `src/auditors/language.py`）。

---

## 已知限制

| 限制 | 影响 | 缓解措施 |
|------|------|---------|
| PDF 仅有文本层 | PDF 的字体/位置/版式无法检查 | 提示用户优先使用 PPTX/DOCX |
| 英文语法需 LanguageTool | 仅拼写检查在纯 Python 模式可用 | Docker 一键部署 LanguageTool |
| 项目符号字符未从 PPTX XML 提取 | 项目符号一致性检查使用文本启发式 | 未来可扩展 PPTX Converter 提取 `a:buChar` |
| 不支持图片内文字 (OCR) | 截图中的文字无法审查 | 架构预留 `image_blob` 字段 |
| 不替代人工审查 | 只做确定性检查，不做语义/逻辑判断 | 定位为"第一道防线"，辅助而非替代 |

---

## 术语约定

| 本项目中术语 | 含义 |
|-------------|------|
| **规则 (Rule)** | `rules.md` 中的一条审查声明，如 STR-001 |
| **发现 (Finding)** | 审查过程中产生的一个问题报告 (`AuditFinding`) |
| **审计器 (Auditor)** | 执行一类审查的组件 (StructureAuditor, FormatAuditor...) |
| **检查类型 (check_type)** | `_DISPATCH` 表中的 key，如 `"title_trailing_punctuation"` |
| **转换器 (Converter)** | 将原始格式转为统一 Document 模型的组件 |
| **引擎 (Engine)** | 可复用的后端服务 (RuleParser, AutoFixer, LanguageTool) |
| **流水线 (Pipeline)** | `build_auditors()` + `run_auditors()` — 审查编排 |
| **豁免 (Exempt)** | 在 Web UI 中忽略特定 Finding，不删除，可恢复 |

---

<!-- last_updated: 2026-08-18 -->
