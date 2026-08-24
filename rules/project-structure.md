# DocAudit 项目结构

> 完整文件树 + 架构图 + 文件职责速查。代码位置导航的唯一信源。
> 设计理念 → [context.md](context.md) &nbsp;|&nbsp; 编码规范 → [skills/python-SKILL.md](../skills/python-SKILL.md)

---

## 架构层级

```
┌──────────────────────────────────────────────────────────┐
│                    UI / CLI 层                            │
│  app.py (Streamlit Web)     src/cli.py (命令行)           │
│  用户入口 — 触发审查 + 展示结果 + 下载报告                 │
└───────────────────────┬──────────────────────────────────┘
                        │ 调用 build_auditors() + run_auditors()
                        ▼
┌──────────────────────────────────────────────────────────┐
│                    Reporter 层                            │
│  src/reporters/html_reporter.py   json_reporter.py       │
│  输出层 — Findings → HTML/JSON 报告                       │
└───────────────────────┬──────────────────────────────────┘
                        ▲ 消费 list[AuditFinding]
┌──────────────────────────────────────────────────────────┐
│                    Auditor 层                             │
│  structure.py  format.py  language.py                    │
│  factual.py    custom_rules.py (中枢路由器)               │
│  审查层 — Document → [AuditFinding, ...]                  │
└──┬─────────┬────────┬────────┬──────────┬────────────────┘
   │         │        │        │          │
   ▼         ▼        ▼        ▼          ▼
┌──────────────────────────────────────────────────────────┐
│                    Engine 层                              │
│  rule_parser.py  terminology.py  vocabulary.py           │
│  languagetool.py autofix.py      pipeline.py (编排器)     │
│  引擎层 — 可复用后端服务                                   │
└───────────────────────┬──────────────────────────────────┘
                        │ 消费统一的 Document 模型
                        ▼
┌──────────────────────────────────────────────────────────┐
│                    Converter 层                           │
│  pptx_converter.py  docx_converter.py                    │
│  pdf_converter.py   md_converter.py                      │
│  转换层 — 多格式 → 统一 Document 模型                      │
└───────────────────────┬──────────────────────────────────┘
                        │ 输出统一的 Document 模型
                        ▼
┌──────────────────────────────────────────────────────────┐
│                    Model 层 (独立，零外部依赖)             │
│  src/models/document.py   src/models/finding.py          │
│  数据层 — Document → Page → PageElement → Paragraph → Run │
│          AuditFinding (type, severity, rule_id, ...)      │
└──────────────────────────────────────────────────────────┘

  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
  │                Config 层 (横切)                          │
  │  rules.md     glossary/     vocab/                      │
  │  配置层 — 驱动所有 Auditor 行为                           │
  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
```

**层级依赖规则**：上层依赖下层，下层不感知上层。Model 层零外部依赖。

| 层级 | 可依赖 | 不可依赖 |
|------|--------|---------|
| UI/CLI | Reporter, Auditor, Engine, Converter, Model | — |
| Reporter | Model (AuditFinding) | Auditor, Engine |
| Auditor | Engine, Model | UI, Reporter, Converter |
| Engine | Model, Converter (仅 pipeline), Auditor (仅 pipeline 编排器) | UI, Reporter |
| Converter | Model | 以上所有 |
| Model | —（独立层） | 以上所有 |
| Config | —（被 Engine 读取） | — |

> **编排器例外**：`pipeline.py` 位于 Engine 层，但它是唯一跨层编排器——
> 其职责是构建并运行全部 5 个 Auditor，故需依赖 Auditor 层（`build_auditors`/
> `run_auditors`）。除 pipeline 外，其余 Engine 模块不得反向依赖 Auditor/UI/Reporter。

---

## 完整目录树

```
DocAudit/
├── AGENTS.md                        # AI 上下文中枢 — 路由表 + 红线 + 约束（跨工具标准大写）
├── CLAUDE.md                        # Claude Code 兼容副本（AGENTS.md 静态副本，修改后需重新复制）
├── README.md                        # 人类项目首页 — 场景入口 + 快速上手
├── rules.md                         # 审查规则声明 (26 条，配置驱动)
├── app.py                           # Streamlit Web UI 入口
├── docker-compose.yml               # LanguageTool Docker 服务
├── pyproject.toml                   # 项目配置 + 依赖声明
├── requirements-core.txt            # 离线依赖锁定文件 (生成物，勿手改)
├── requirements-pdf.txt             # 离线依赖锁定文件 (生成物，勿手改)
├── requirements-full.txt            # 离线依赖锁定文件 (生成物，勿手改)
├── .vale.ini                        # Vale 配置 (可选，未接入 CI)
├── LICENSE                          # MIT 许可证
├── CHANGELOG.md                     # 变更日志 (keepachangelog)
├── CONTRIBUTING.md                  # 贡献指南 (含三步注册法)
├── .gitignore                       # Git 忽略规则
│
├── rules/                           # 📚 规范文档中心 (SSOT)
│   ├── specification.md             #   项目规格文档
│   ├── context.md                   #   领域背景 + 设计哲学 + 技术选型
│   ├── project-structure.md         #   项目结构 (本文件)
│   ├── api-reference.md             #   函数签名速查 — 唯一信源
│   ├── user-manual.md               #   用户手册 — 场景驱动配方
│   ├── refactoring-plan.md          #   重构计划
│   ├── documentation.md             #   文档职责规范
│   ├── tooling-pitfalls.md          #   工具/脚本坑位清单 (cmd/bat/pip/git)
│   └── falsy-pitfalls.md            #   Python falsy 值误判检查清单
│
├── skills/                          # 🛠️ AI 编码规范
│   ├── python-SKILL.md              #   Python 开发规范
│   ├── refactoring-guardian.md      #   重构守卫专家
│   ├── architecture-reviewer.md     #   架构审查专家
│   └── project-plan-review.md       #   规划评审专家
│
├── .qoder/                          # 🤖 Qoder 平台目录 (skills/ 入库, 其余不入库)
│   ├── skills/                      #   平台注册 Skill (入库, 与 skills/ 源同步)
│   ├── prompts/                     #   Prompt 源文件 (不入库: code-review/deep-code-review)
│   └── better-harness/              #   审查报告生成物 (不入库)
│
├── tools/                           # 🔧 CI 门禁工具
│   ├── check_bare_handlers.py       #   裸异常处理器检查 (AST 感知)
│   ├── check_doc_numbers.py         #   文档数字一致性检查 (防数字漂移)
│   ├── check_html_escape.py         #   html.escape 合规性检查 (报告器 + app.py)
│   ├── check_api_sync.py            #   api-reference.md 同步检查 (含签名一致性)
│   └── check_skill_sync.py          #   技能双份同步检查 (skills/ ↔ .qoder/skills/)
│
├── .github/
│   ├── dependabot.yml               # 依赖自动更新 (每周)
│   ├── workflows/
│   │   └── ci.yml                   # CI: pytest 矩阵 + DISPATCH + ruff + 三门禁检查
│   ├── ISSUE_TEMPLATE/              # bug / feature / docs / refactor 四类模板
│   └── PULL_REQUEST_TEMPLATE.md     # PR 模板
│
├── scripts/                         # 🔧 启动/安装脚本 (批处理仅为 ASCII 启动器，逻辑在 .py)
│   ├── common.py                    #   共享工具 (UTF-8/路径/解释器探测/run 封装)
│   ├── run.bat / run.sh / run.py    #   一键启动 Web UI
│   ├── install.bat / install.sh / install.py   # 安装依赖
│   ├── setup_offline.bat / .sh / .py           # 离线安装 (下载三步: 锁文件+构建依赖+自检)
│   ├── gen_requirements_lock.py     #   从 packages/ 离线解析生成 requirements-*.txt
│   └── packages/                    #   离线依赖缓存 (生成物，gitignore 排除)
│
├── glossary/                        # 📖 半导体术语表 (YAML)
│   ├── semiconductor_core.yaml      #   半导体制造核心 (17 条)
│   ├── advanced_packaging.yaml      #   先进封装 (19 条)
│   └── general_tech.yaml            #   通用技术写作 (9 条)
│
├── vocab/                           # 📝 词汇白名单/黑名单
│   ├── accept.txt                   #   术语白名单 (80+ 词)
│   └── reject.txt                   #   禁用词黑名单 (11 条)
│
├── styles/                          # 🎨 Vale 风格配置 (可选，未接入 CI)
│
├── .streamlit/
│   └── config.toml                  # Streamlit 配置
│
├── src/                             # 📦 源代码
│   ├── __init__.py
│   ├── cli.py                       #   CLI 命令行入口
│   ├── text_utils.py                #   CJK 字符检测 + 混排正则
│   │
│   ├── models/                      #   数据模型层 (独立，零外部依赖)
│   │   ├── __init__.py
│   │   ├── document.py              #     Document → Page → PageElement → Paragraph → Run
│   │   └── finding.py               #     AuditFinding → FindingSeverity/Type → dedup
│   │
│   ├── converters/                  #   转换层 — 多格式 → 统一 Document
│   │   ├── __init__.py
│   │   ├── base.py                  #     Converter 抽象基类
│   │   ├── pptx_converter.py        #     PPTX → Document (保真度最高)
│   │   ├── docx_converter.py        #     DOCX → Document
│   │   ├── pdf_converter.py         #     PDF → Document (Docling + 回退)
│   │   └── md_converter.py          #     Markdown → Document
│   │
│   ├── auditors/                    #   审查层 — Document → [AuditFinding]
│   │   ├── __init__.py
│   │   ├── base.py                  #     BaseAuditor 抽象基类
│   │   ├── structure.py             #     StructureAuditor (STR-001~008)
│   │   ├── format.py                #     FormatAuditor (FMT-001~008)
│   │   ├── language.py              #     LanguageAuditor (语法+术语+词汇)
│   │   ├── factual.py               #     FactualAuditor (CON-001~003-C)
│   │   └── custom_rules.py          #     CustomRulesAuditor (中枢路由器)
│   │
│   ├── engines/                     #   引擎层 — 可复用后端服务
│   │   ├── __init__.py
│   │   ├── pipeline.py              #     流水线编排: build_auditors() + run_auditors()
│   │   ├── rule_parser.py           #     rules.md 解析器 + extract_auditor_config()
│   │   ├── terminology.py           #     术语检查器 (YAML glossary 匹配)
│   │   ├── vocabulary.py            #     词汇表管理器 (accept.txt + reject.txt)
│   │   ├── languagetool.py          #     LanguageTool 客户端 (三层降级)
│   │   └── autofix.py               #     AutoFixer (字体/间距/溢出/标点/符号)
│   │
│   └── reporters/                   #   输出层 — Findings → 报告
│       ├── __init__.py
│       ├── html_reporter.py         #     HTML 报告生成
│       └── json_reporter.py         #     JSON 报告生成
│
└── tests/                           # 🧪 测试 (419 用例)
    ├── __init__.py
    ├── fixtures/
    │   ├── sample.pptx              #     测试用 PPTX
    │   ├── sample.docx              #     测试用 DOCX (存根)
    │   ├── sample_round2_test.pptx  #     第二轮测试 PPTX
    │   ├── sample.pdf               #     最小合法 PDF (docling 集成测试)
    │   └── gen_sample_pdf.py        #     sample.pdf 生成器 (xref 偏移程序化计算)
    ├── test_models.py               #     Document + Finding 模型测试
    ├── test_auditors.py             #     Structure + Format + Factual 审计器测试
    ├── test_engines.py              #     Terminology + Vocabulary + 语言分段 + LT 客户端测试
    ├── test_rules.py                #     规则解析 + DISPATCH 验证
    ├── test_integration.py          #     全流水线集成测试 (流水线确定性回归)
    ├── test_golden_paths.py         #     真实三路径黄金测试 (API=CLI=AppTest) + run_auditors 行为
    ├── test_rule_coverage.py        #     零断言规则定向覆盖测试
    ├── test_html_report_security.py #     HTML 转义红线 (XSS 载荷)
    ├── test_app_ui.py               #     app.py 过滤器/扫描器 + AppTest 冒烟
    ├── test_cli_exit_codes.py       #     CLI 退出码契约
    ├── test_cli_direct.py           #     CLI 直接单测 (audit_file/--fix 链路)
    ├── test_autofix.py              #     AutoFixer 修复链路
    ├── test_converters.py           #     四格式转换器
    ├── test_edge_cases.py           #     边界输入
    ├── test_language_auditor.py     #     语言审计器细节
    ├── test_scripts.py              #     scripts/ 工具 (common + setup_offline + 锁文件)
    ├── test_contrast.py             #     FMT-008 WCAG 对比度算法 + 表格检查
    ├── test_check_doc_numbers.py    #     文档数字一致性检查器门禁
    ├── test_check_bare_handlers.py  #     裸异常检查器门禁
    ├── test_check_api_sync.py       #     API 同步检查器门禁
    ├── test_check_html_escape.py    #     HTML 转义检查器门禁
    └── test_check_skill_sync.py     #     技能双份同步检查器门禁
```

---

## 文件职责速查

### 模型层 (`src/models/`)

| 文件 | 关键类/函数 | 职责 |
|------|-----------|------|
| `document.py` | `Document`, `Page`, `PageElement`, `Paragraph`, `Run` | 统一文档数据模型。`Page.flattened_elements` 递归展开 Group。`all_text` 属性缓存。 |
| `finding.py` | `AuditFinding`, `FindingSeverity`, `FindingType` | 审查发现模型。`dedup_key` 去重。`to_dict()` / `from_dict()` 序列化。 |

### 转换层 (`src/converters/`)

| 文件 | 关键类 | 提取元数据 |
|------|--------|-----------|
| `pptx_converter.py` | `PptxConverter` | 字体/字号/颜色 (Run级)、位置 EMU→pt、版式名称、占位符类型、图片/图表数据、备注 |
| `docx_converter.py` | `DocxConverter` | 段落样式名→shape_name、大纲级别→level、表格、SDT |
| `pdf_converter.py` | `PdfConverter` | 文本+标题级别 (Docling)，无字体/位置 |
| `md_converter.py` | `MarkdownConverter` | 纯文本+标题级别，多编码回退 |

### 审查层 (`src/auditors/`)

| 文件 | 关键类 | 规则 ID | 检查数 |
|------|--------|---------|--------|
| `structure.py` | `StructureAuditor` | STR-001~008 | 10 |
| `format.py` | `FormatAuditor` | FMT-001~008 | 11 |
| `language.py` | `LanguageAuditor` | PY-SPELL, PY-ZH-GRAMMAR, FMT-MIXED | 语言+术语+词汇 |
| `factual.py` | `FactualAuditor` | CON-001~003-C | 5 |
| `custom_rules.py` | `CustomRulesAuditor` | 路由所有 check_type | 中枢路由器 |

### 引擎层 (`src/engines/`)

| 文件 | 关键函数/类 | 职责 |
|------|-----------|------|
| `pipeline.py` | `build_auditors()`, `run_auditors()` | 统一流水线编排。CLI 和 Web UI 共用。 |
| `rule_parser.py` | `parse_rules_md()`, `extract_auditor_config()` | rules.md 解析 + 配置提取 |
| `terminology.py` | `TerminologyChecker` | YAML 术语表加载 + regex 匹配 + 跳过去重 |
| `vocabulary.py` | `Vocabulary` | accept.txt 白名单 + reject.txt 黑名单 |
| `languagetool.py` | `LanguageToolClient` | Docker → Java → Python 三层降级 |
| `autofix.py` | `AutoFixer` | 字体标准化 + 字号修正 + 间距 + 溢出 + 标点 + 项目符号 |

### 报告层 (`src/reporters/`)

| 文件 | 关键函数 | 职责 |
|------|---------|------|
| `html_reporter.py` | `generate_html_report()` | 独立 HTML 报告，所有用户文本 `html.escape()` |
| `json_reporter.py` | `generate_json_report()` | 结构化 JSON，含 meta + summary + findings |

### UI / CLI

| 文件 | 关键入口 | 职责 |
|------|---------|------|
| `app.py` | `main()` | Streamlit Web UI — 单文件/批量 + 过滤 + 豁免 + 下载 |
| `src/cli.py` | `main()` | 命令行 — 单文件/批量 + `--fix` + `-o` 导出 |

---

<!-- last_updated: 2026-08-19 -->
