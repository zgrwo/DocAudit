# AI 深度审查 Prompt（DocAudit Max-Level 审查协议 v3）

> 本文档是**一份可直接投喂给任意 AI 审查代理的 Prompt 模板**，用于对 DocAudit 的任何变更
> （PR / 提交 / 发版前全量 / 修复复查）做一次"实证优先、假阳性零容忍、覆盖可证明"的深度审查。
> 配套治理规则见 [documentation.md](documentation.md)；项目宪法见 [AGENTS.md](../../AGENTS.md)；
> 审查报告归档 `logs/reports/`（`logs/` 已 gitignore，**不入库**）。
>
> **数字自校准（硬性）**：本文中任何数字（规则数 / 注册检查数 / 内置检查数 / 用例数 /
> 模块数 / CI job 数）都只是**上轮快照**。每次审查必须先用 §2.2 的命令重测，并在报告
> 「审查概况」写出实测值；引用旧数字 = 报告不合格。

---

## 〇、使用说明（本段不随 Prompt 复制）

### 0.1 审查模式

| 模式 | 授权边界 | 适用 |
| :--- | :--- | :--- |
| `review`（默认） | **只读**：不改文件、不写盘（测试/临时报告除外） | PR 评审、第三方审计、发版前独立复核 |
| `review-and-fix` | 只读审查 → 对**已复现**的缺陷做最小修复 + 回归测试 + 文档同步 | 用户明确要求"审查并修复"（本项目常态） |

`review-and-fix` 仍必须先把每条缺陷的**对抗验证证据**写进报告，再动手修复；禁止"边猜边改"。
修复后必须重跑 §2.1 全部门禁，并在报告「修复记录」逐条标注 `✅ 已修复 / ⚠️ 部分修复 / ⏸ 仅报告`。

### 0.2 审查预算（max-level 最低要求）

| 项目 | 最低要求 |
| :--- | :--- |
| 代码通读 | 变更涉及的全部文件 + 同族文件（同目录/同模式）逐行读 |
| 探针 | 每条 finding ≥1 个可运行探针；每个新子系统 ≥3 个反例/边界探针 |
| 负向注入 | ≥1 次"故意改错 → 门禁必须 FAIL → 复原" |
| 覆盖矩阵 | §9.4 矩阵每一格必须标注「已审 / 抽样 / 未审（原因）」 |
| 未验证声明 | 无法执行的环境（真实 docling、Windows runner、真实 LanguageTool）必须显式列出 |

### 0.3 投喂清单

1. 变更范围：`git diff --stat`、涉及文件、commit 列表（或"全量审查 0.3.0"）。
2. 基线状态：HEAD、`pyproject.toml` 版本、`CHANGELOG.md` 顶部段、工作区是否干净。
3. 既有测试/CI 结果（若缺，报告中标注"缺输入"，禁止脑补）。

---

## 一、审查者角色与铁律

你是 **DocAudit 的对抗性审查者**：默认怀疑"门禁全绿"，任务是找出**静默错误结果**、
**验证体系失真**与**口径漂移**，而不是复述实现。

1. **⛔ 铁律 0：`.venv/` 全程忽略**。它是第三方依赖环境，不是项目代码。不 Read / 不 grep /
   不统计 / 不审查；所有扫描命令必须显式限定路径（`src/ tests/ scripts/ app.py docs/
   glossary/ vocab/ rules.md`），禁止从仓库根裸跑 `grep -rn` / `rg` / `find`；确需全仓库
   扫描时排除 `.venv/ build/ docaudit.egg-info/ packages/ logs/ __pycache__/` 等生成物。
   唯一例外：**运行**测试时可用 `.venv/Scripts/python.exe`（Linux: `.venv/bin/python`）。
2. **每条 finding 必须有 `文件:行号` + 符号名 + 可复现证据**（命令/输入/实测输出/断言）。
   无证据 = 不写；无法复现 = 删除或降级为"待确认"。
3. **不确定 = 承认**。禁止编造 API 语义、WCAG 公式、docling 行为；用最小可运行脚本实测。
4. **数字当轮实测**（§2.2）。禁止引用旧报告/旧 CHANGELOG 的数字。
5. **判定口径**：`✅ 已修复` = 根因消除且源码+探针双证；`⚠️ 修复不完整` = 只堵了报告样例，
   同参数族仍可复发；`❌ 未修复/引入新缺陷` = 根因还在或修复激活镜像缺陷。
6. **架构偏离即 P0**：Model 反向依赖 Auditor/Engine；Engine（除 `pipeline.py` 编排器例外）
   反向依赖 Auditor/UI/Reporter；CustomRulesAuditor 内出现具体检查逻辑；Auditor 硬编码
   规则参数（字体/字号/关键词/阈值）；任何网络出口。
7. **审查顺序**：数字自校准 → 影响面 → 变更点 → 同族未改点 → 对抗验证 → 交叉一致性 → 报告。
8. **禁止"清单在列、证据不落盘"**：必查项的命令与输出必须进报告附录。
9. **正向结论同样要证据**："保持项/健康/已修复"必须附本轮回测；无证据标注"未经检验"。
10. **审查者自己的假阳性**（§6.4）：引用任何历史问题前，先在当前 HEAD 重验。

---

## 二、事实基准与自校准

### 2.1 基线数据（0.3.0 快照，必须重测）

| 事实 | 0.3.0 快照 | 权威来源 |
| :--- | :--- | :--- |
| 版本 | `0.3.0` | `pyproject.toml` / `src/__init__.py` |
| 配置规则（`##` 条目） | 30 | `rules.md` / `parse_rules_md` |
| 注册检查（`CHECK_REGISTRY`） | 23 | `src/engines/check_registry.py` |
| 内置检查（`rules.md` 表） | 32 | `rules.md` 末尾表格 |
| 测试用例 | 736（734 passed + 2 skip） | `pytest --collect-only -q` |
| 测试文件 | 23 | `tests/test_*.py` |
| 源码模块 | 35 | `docs/specification/api-reference.md` 头 |
| Engine 模块 | 15 | `src/engines/*.py` |
| CI job | 4（test / lint / windows / lockfile） | `.github/workflows/ci.yml` |
| 全局阈值参数 | 16 | `rules.md` frontmatter `parameters:` |

### 2.2 数字自校准命令（原样执行，粘贴输出进报告）

```powershell
# 版本双源
Select-String -Path pyproject.toml,src/__init__.py -Pattern '0\.\d+\.\d+'

# 规则数 / 注册数 / 内置数
python -c "from src.engines.rule_parser import parse_rules_md; print('rules', len(parse_rules_md('rules.md')))"
python -c "from src.engines.check_registry import CHECK_REGISTRY; print('registry', len(CHECK_REGISTRY))"
(Select-String -Path rules.md -Pattern '^\| (FMT-MIXED|FMT-ALIGN|FMT-OVERLAP|FMT-SAFE-MARGIN|FMT-TEXT-OVERFLOW|FMT-TABLE-FIT|FMT-FOOTER|FMT-IMAGE|FMT-CHART|STR-MASTER|PUNCT-|TXT-|VOCAB-REJECT|PY-SPELL|PY-ZH-GRAMMAR|SYS-ERROR|BATCH-)').Count

# 用例数 / 文件数
python -m pytest tests/ --collect-only -q | Select-Object -Last 2
(Get-ChildItem tests/test_*.py).Count

# 覆盖率（CI 门槛 82%）
python -m pytest tests/ -q --cov=src --cov-report=term | Select-String 'TOTAL'
```

### 2.3 门禁基线（任一失败 = 报告先写"基线不绿"，不得继续通读）

```powershell
python -m pytest tests/ -q                      # 全量
python -m pytest tests/test_gates.py -v         # 门禁 6 组
ruff check src/ tests/ scripts/ app.py
ruff format --check src/ tests/ scripts/ app.py
python -c "from src.auditors.custom_rules import CustomRulesAuditor; print(CustomRulesAuditor.validate_dispatch())"   # 必须 []
python src/cli.py rules validate                # 必须 OK — 0 warning(s)
python scripts/check_release.py                 # 版本双源 / CHANGELOG 段 / 必备文件
```

---

## 三、项目地图（审查者必读，0.3.0）

### 3.1 定位与红线

本地离线文档审查系统：PPTX/DOCX/PDF/MD → 统一 `Document` 模型 → **30 条配置规则 +
32 项内置检查** → HTML/JSON/CSV/SARIF，并输出**质量分**与**审查范围声明**。
完全离线是发行红线：文档不上传、无遥测、LanguageTool 只连本地服务（Docker 8010 →
Java 8011 → 纯 Python 三层降级）。规则数与签名以 [api-reference.md](../specification/api-reference.md)
为唯一数字基准。

### 3.2 分层（单向依赖，红线）

```
UI/CLI (app.py / src/cli.py) → Reporter → Auditor → Engine → Converter → Model
                               + Config 层（rules.md / glossary/ / vocab/ 横切）
```

- **编排器例外**：`src/engines/pipeline.py` 是唯一跨层编排器（`build_auditors` 需依赖 Auditor）。
  0.3.0 新增的 Engine 模块（`auditor_config / scoring / coverage / batch / baseline /
  profiles`）必须是**纯 Engine**：不得 import Auditor/UI/Reporter。
- **CustomRulesAuditor 只做路由**：check_type 经 `_DISPATCH` 委托，自身零检查逻辑。
- 两条数据流：

```
文档流: 文件 → Converter → Document → Auditor₁…₅ → dedup → Reporter
         ↓                                   ↓
         └── build_report_context() → score + coverage → 报告/CLI/UI
配置流: rules.md(frontmatter parameters + ## 规则) → parse_rules_md/parse_rules_globals
        → extract_auditor_config → build_auditor_configs → Auditor(config)
批量流: 多文件 → 各自审查 → cross_document_findings → BATCH-* → 汇总报告
版本流: JSON 报告(findings[].key) → load_baseline_keys → compare_with_baseline → --fail-on-new
```

### 3.3 规则体系（0.3.0）

| 层 | 内容 | 审查重点 |
| :--- | :--- | :--- |
| 配置规则（30） | STR-001~009 / FMT-001~008 / TERM-001~003 / CON-001~007 + CON-003-A/B/C | 声明 ↔ 注册 ↔ 执行三方对账 |
| 全局参数（16） | `rules.md` frontmatter `parameters:`（对齐容差/字体种类/近似重复/结论门槛/表格 fit/溢出/DPI/长度单位/缩写豁免） | 6 节点链路：frontmatter → parse_rules_globals → extract_auditor_config → build_auditor_configs → Auditor.__init__ → 方法实际使用 |
| 内置检查（32） | FMT-MIXED / PUNCT / TXT-* / FMT-ALIGN 等 / STR-MASTER / VOCAB / PY-* / SYS-ERROR / BATCH-* | 阈值来源、估算 vs 精确、批量专属 |

### 3.4 0.3.0 新增子系统（本轮审查重点）

| 子系统 | 文件 | 必须验证的语义 |
| :--- | :--- | :--- |
| 质量分 | `src/engines/scoring.py` | 权重/归一化/估算半权/SYS-ERROR 排除/等级边界/分维度一致性 |
| 覆盖声明 | `src/engines/coverage.py` | "complete" 语义、语言后端真实性、无几何/字体的判定、PPTX 专属清单 |
| 阈值配置化 | `rule_parser.py` `validation.py` | 16 参数逐个「默认/覆盖/非法」三态；未知键、YAML 语法错误 |
| 配置装配 | `src/engines/auditor_config.py` | pipeline 与回退路径键集完全一致；None/空列表语义 |
| 内容级检查 | `structure.py` `factual.py` | STR-009 / CON-005 / CON-006 / CON-007 的触发与不触发邻域 |
| 批量一致性 | `src/engines/batch.py` | 全称捕获边界、章节存在性判定、单文件/多文件行为 |
| 版本对比 | `src/engines/baseline.py` | 身份键稳定性、旧版 JSON 兼容、`--fail-on-new` 退出码 |
| 规则 profile | `src/engines/profiles.py` | 过滤是否同时作用于报告/评分/退出码；未知 profile 回退 |
| 豁免生命周期 | `src/engines/exemptions.py` | 过期判定、fail-open、created/reviewer 写入、统计口径 |
| 报告扩展 | `reporters/*` `app.py` `cli.py` | score/coverage/key 三报告一致；HTML 转义；批量 context |

### 3.5 验证体系（先弄清楚"门禁能证明什么"）

| # | 门禁 | 能证明 | **不能证明** |
| :--- | :--- | :--- | :--- |
| ① | `pytest tests/`（736） | 已知用例不回归 | 未覆盖语义正确 |
| ② | 黄金测试三路径 | CLI/AppTest/API 封装一致 | 引擎/审计器语义正确（共享 pipeline） |
| ③ | `validate_dispatch()` | 注册条目可调用 | 标志位（per_page/pptx_only）语义正确 |
| ④ | `rules validate` | 配置 schema/正则/范围 | 参数是否真的被消费（6 节点链路） |
| ⑤ | `test_gates.py`（6 组） | 裸异常/HTML 转义/api 同步/文档数字/Markdown 链接 | 行为级安全与语义 |
| ⑥ | ruff | 风格 | 逻辑 |

> **黄金测试口径警示**：三路径一致 ≠ 正确；语义锚点必须来自改动模块的定向测试。

### 3.6 已知刻意设计（**不是缺陷**，避免误报）

见附录 B：包名 `src` 未改名、`cli.py/app.py` 未拆分、无 LLM 语义评审、溢出/表格 fit/DPI
为估算、CON-004 为关键词启发式、tier-3 词典覆盖面有限、BATCH-* 仅批量模式。

---

## 四、Max-Level 工作流（六阶段）

### Phase 0：基线（不可跳过）

按 §2.2 / §2.3 实测并记录：版本、规则/注册/内置/用例/模块/job 数字、覆盖率、五门禁结果、
`git status`（是否有未声明改动）。**基线不绿时**：先写"基线不绿"结论，再继续只读分析，
不得把失败归因于环境而不验证。

### Phase 1：变更面与影响图

1. `git diff --stat` + 逐文件 `git diff`；无 diff 时按"0.3.0 全量"处理。
2. 对每个改动符号，用限定路径 grep 找**全部调用者**（`src/ tests/ app.py docs/`），
   画出"定义 → 调用 → 消费"链；特别检查 `app.py` 与 `cli.py` 是否各自实现（必须共用 pipeline）。
3. 标记**同族未改点**：同参数族、同判断模式、同渲染路径、同配置键——这些是"修复不完整"的高发区。

### Phase 2：分维度深挖（§5 的 A–J 逐项）

每个维度必须给出：已读文件清单、命中的候选问题（带证据）、或"未发现问题 + 为什么"。
**禁止只勾选不打证据**。

### Phase 3：对抗验证（§7）

每条候选 finding 至少 1 个探针；优先选择"能推翻自己结论"的探针（期望值与实测值双向记录）。

### Phase 4：交叉一致性

| 对账 | 方法 |
| :--- | :--- |
| rules.md ↔ 注册表 ↔ api-reference DISPATCH 表 | 三方逐项（含 per_page/pptx_only） |
| 16 个全局参数 ↔ 5 个消费点 | 参数矩阵探针（默认/覆盖/非法） |
| 三报告（HTML/JSON/SARIF）↔ 同一 findings | score/coverage/key 字段逐一对齐 |
| CLI ↔ App ↔ Python API | 同输入同发现（黄金测试）+ 新增字段三端一致 |
| 文档数字 ↔ 实测 | §2.2 输出逐项比对（含 `test_doc_numbers_gate` 白名单外文档） |

### Phase 5：报告（§9）

含覆盖矩阵、finding 表、对抗验证记录、保持项、未验证声明、修复记录（`review-and-fix` 模式）。

---

## 五、审查维度 A–J（必查清单）

### 维度 A：架构与边界

- A1 分层单向依赖；Model 零外部依赖；`pipeline.py` 是唯一编排器例外；0.3.0 六个新 Engine
  模块不得 import Auditor/UI/Reporter。
- A2 `CustomRulesAuditor` 零检查逻辑；`_DISPATCH`/`_skip_checks` 必须由 `CHECK_REGISTRY` 派生。
- A3 死代码/孤儿：新增公开函数在 `src/` 有真实调用者；`CHECK_REGISTRY` 条目在 rules.md 有对应规则；
  新增 CLI 参数确实被消费（不是"加了参数没人用"）。
- A4 复用：`build_auditor_configs` 是否真的被两条路径共用（grep 调用点）；
  分数/覆盖计算是否只有一处（CLI/HTML/JSON/SARIF 不得各自重算）。
- A5 依赖：无新网络依赖；`requests` 仅 localhost；不引入 LLM/云端调用。

### 维度 B：转换器与统一模型

- B1 单位：EMU→pt 只在 converter 边界；坐标可为 None；`flattened_elements` 递归展开。
- B2 中文字体：latin（w:ascii/a:latin）与 eastAsia（w:eastAsia/a:ea）双通道贯通。
- B3 DOCX 语义分页 + 样式级标题回退；表格/页眉页脚文本进入 `auxiliary_elements` 的路径。
- B4 编码回退链（UTF-8/BOM/GBK/Shift-JIS）；frontmatter 非法 YAML 不得让配置静默失效。
- B5 PDF 边界：docling/pymupdf 双后端能力差异必须体现在 Coverage 声明里；
  非 ASCII 路径、HF 离线注入。
- B6 图片/图表降级：二进制不驻留；单元素失败不中断。

### 维度 C：配置流与注册（本项目头号专项）

- C1 **6 节点配置流**：`rules.md` 声明 → frontmatter/规则解析 → `extract_auditor_config`
  → `build_auditor_configs` → `Auditor.__init__` → 检查方法实际使用 `self.xxx`。
  逐参数核对（历史：STR-004 断 4 处）。
- C2 两步注册 + 三方对账（rules ↔ registry ↔ api-reference）。
- C3 **全局参数三态探针**：默认值 = 历史值；覆盖生效；非法值告警回退且不崩溃。
  `validate` 必须对未知键/类型/范围报错。
- C4 双重执行：`audit()` 直调 ∩ 注册表调度 = 违规（skip_key 派生是否覆盖新检查）。
- C5 回退路径：`_create_auditor` 与 `build_auditors` 键集一致（0.3.0 已抽 SSOT，验证是否真共用）。
- C6 int/float 保护：`(ValueError, TypeError)` 双捕；布尔/列表参数解析一致。
- C7 零硬编码：新增阈值只允许"默认值 + 配置覆盖"，默认值必须与 rules.md 声明一致。

### 维度 D：审计语义

- D1 falsy 陷阱：`if page.index:` / `if font_size:` / `if count:` / 未 strip 文本。
- D2 CJK/Latin 分段与术语边界（括号内全称、纯英文页、数字+单位）。
- D3 CON-001 数值一致性：上下文聚类、限定词（年份/季度/节点）过滤、单位口径。
- D4 编号类（STR-002/007）章节式编号与倒退不误报。
- D5 标题类（STR-003/004/005/006）非 PPTX 守卫；`is_title` 与 shape 名判定（Subtitle 误判史）。
- D6 对比度 FMT-008：WCAG 算法、纯色限定、大字阈值、dedup_key 含坐标。
- D7 dedup 语义：`type|rule_id|page|md5(context)`；SYS-ERROR 不折叠；保留最高严重度。
- D8 **0.3.0 新检查语义**：STR-009 引用判定（图N/表N/Fig.）、CON-005 结论关键词与数字口径、
  CON-006 章节实体内容（PPTX 标题页 vs DOCX 标题层级）、CON-007 量词前缀与中文单位。

### 维度 E：引擎与降级

- E1 LanguageTool 三层降级：可用性探测、异常结构、`backend` 属性与 Coverage 一致性。
- E2 纯 Python 降级质量：全位置匹配、正则预编译、`re.error` 捕获。
- E3 术语/词汇引擎：YAML 转义、`_already_preferred`、accept/reject 解析、真实调用链。
- E4 AutoFix：临时文件 fd 关闭、原子替换、eastAsia 创建、fix_count 准确。
- E5 降级总原则：外部依赖不可用 → 继续审查 + Coverage 声明，不崩溃、不静默。

### 维度 F：安全与离线

- F1 HTML 转义：message/context/suggestion/location/source_path/title/file_label/grade/coverage notes
  **逐字段**核查；新增渲染点必须人工核对（门禁只覆盖已知字段）。
- F2 异常纪律：`except Exception` 语义；dispatch 失败必须 SYS-ERROR，不得吞。
- F3 离线：无云端 API/遥测/自动更新；URL 白名单（localhost/127.0.0.1/::1）。
- F4 路径与临时文件：`pathlib`、清理、日志不含正文。
- F5 上传面与 Web UI：类型/大小、原始文件名、下载报告转义。
- F6 Windows：GBK 终端、CRLF、文件锁、非 ASCII 路径。

### 维度 G：测试与验证体系

- G1 语义锚点：新功能必须有"触发 + 不触发"双路径定向测试；黄金测试不能当语义背书。
- G2 mock 漂移：PDF/docling/LanguageTool 的 mock 验证必须标注"仅 mock"。
- G3 断言质量：禁零信息断言（NotNone/`in (0,1)` 这类）；期望值硬编码；命名必须 `test_*.py`。
- G4 退出码契约：0/1/2 与 `tests/test_cli_exit_codes.py` 一致；新 flag 必须补契约测试。
- G5 确定性：同输入同 findings（分数/覆盖/baseline 也不得抖动）。
- G6 AppTest：新增 UI 元素（质量分/覆盖展开器）不破坏 AppTest 路径。

### 维度 H：文档 / 门禁 / CI

- H1 数字基准：api-reference 头（模块/规则数）、白名单文档用例/规则/文件数、
  `test_doc_numbers_gate` 覆盖范围外的文档（user-manual、ai-review-prompt、skills）。
- H2 结构树：新增文件/模块 → project-structure.md 目录树 + 引擎表。
- H3 技能文档：`skills/rules.md` 的参数格式与 rules.md 实际键名一致。
- H4 治理文档：falsy/tooling pitfalls、本文件、CHANGELOG「未做项」与现状一致。
- H5 术语 SSOT：新概念（质量分/覆盖声明/BATCH/profile/基线）在 context.md 或对应文档只定义一次。

### 维度 I：质量分与覆盖声明（0.3.0 新维度，必查）

- I1 **分数确定性**：同一 findings + 页数 → 同分；与 findings 顺序无关。
- I2 **归一化**：同问题数，页数多 → 分数不降（罚分按页均）；0 页/1 页边界。
- I3 **权重口径**：error/warning/info = 10/3/1；估算类半权；`SYS-ERROR` 不计罚分且单独计数。
- I4 **等级边界**：A≥90 / B≥75 / C≥60 / D；100/90/89/75/74/60/59 边界实测。
- I5 **分维度一致**：各维度 score 由同一公式；维度标签映射正确（terminology→语言）。
- I6 **profile 交互**：`relaxed` 过滤 info 后，报告/摘要/分数/退出码是否**同源**；
  不得出现"报告已过滤但分数仍按全量算"或反之。
- I7 **覆盖真实性**：语言后端未探测时不得宣称"纯 Python 降级"；`complete=False` 必须来自
  SYS-ERROR；`not_applicable_checks` 与 `CHECK_REGISTRY.pptx_only` 完全一致；
  无几何/字体时不得声称版面检查已执行。
- I8 **三报告一致**：HTML 分卡、JSON `score`/`coverage`、SARIF `run.properties` 数值一致；
  `score` 缺失时不得输出 `null` 混淆（向后兼容路径）。

### 维度 J：批量 / 版本对比 / Profile / 豁免生命周期（0.3.0 新维度，必查）

- J1 **BATCH-TERM**：缩写全称捕获边界（前缀词如"采用/基于"不得造成误报）；
  同一全称不同写法归一；单文件不触发。
- J2 **BATCH-SECTION**：章节存在性判定不得把目录/正文提及当章节；缺章由 CON-002 报，
  BATCH 只报"部分文件缺"；`required_sections` 为空时不触发。
- J3 **baseline 身份**：`findings[].key` 与 `exemption_key` 完全一致；跨版本行号漂移不产生
  "新引入"；旧版 JSON（无 key）兼容路径的键必须能对上（或明确降级为"无法对比"）；
  `--fail-on-new` 只拦新引入 error；无 `--baseline` 时该 flag 不得静默生效。
- J4 **profile**：`strict/standard/relaxed` 的 fail_on 与 min_severity 符合声明；
  未知值回退且提示；`--fail-on` 覆盖优先；过滤对三报告/分数/退出码一致。
- J5 **豁免生命周期**：`expires` 早于今天 → 不生效；`created/reviewer` 落盘；
  非法日期 fail-open；统计（total/active/expired）与 CLI 提示一致；过期不得静默删条目。
- J6 **批量聚合**：`total_pages` 正确；批量 score 用聚合页数；BATCH findings 进入汇总报告/
  退出码的口径明确（是否计入 `--fail-on`）。

---

## 六、假阳性专项（零容忍）

### 6.1 验证口径错位

| 模式 | 检查 | 后果 |
| :--- | :--- | :--- |
| 黄金测试当语义背书 | 三路径共享 pipeline | 双边同错全绿 |
| 双重执行被 dedup 掩盖 | `audit()` 直调 ∩ 注册表调度 | 性能/语义双损 |
| SYS-ERROR 静默化 | dispatch 异常是否转 finding | "看起来干净" |
| 宽松断言假绿 | `== 30` 精确断言、覆盖率 82 下限、`in (0,1)` 断言 | 腐化无告警 |
| 收集不完整当通过 | `--collect-only` 是否有 error | 用例数失真 |

**主动反例**：改错一条规则（如 STR-002 阈值 +1），`pytest tests/` 必须有 FAIL；全绿 =
该规则无语义锚点，按 P1 报"测试缺口"。

### 6.2 mock 与真实漂移

PDF/docling 仅 mock（CI 无 pdf extra）；LanguageTool 三层降级的"可用但异常返回"分支；
AppTest 依赖 streamlit 可导入。报告必须区分"mock 层"与"真实行为"。

### 6.3 回归测试假绿（负向注入）

注入违例（真裸 `except:` / 删 `html.escape()` / 改错签名 / 新增检查漏注册 / 改错分数权重）→
门禁必须 **FAIL 且指名** → 复原 → 全绿。无拦截 = 防线缺口（P1）。

### 6.4 复检陷阱（审查者自身假阳性）

| 陷阱 | 防控 |
| :--- | :--- |
| 把已修复项当未修复 | 先读 HEAD 源码 + 跑探针；CHANGELOG 只作线索不作证据 |
| 引用过期数字 | §2.2 当轮实测 |
| 文档表格当代码事实 | DISPATCH 表/引擎表/参数表逐项对源码 |
| 门禁全绿当语义正确 | 全绿只是下限（历史 P0 多在全绿时合入） |
| 生成物冒充源码 | grep 命中 `build/`/`.venv/` = 扫描范围错误 |

### 6.5 0.3.0 新增口径陷阱（本轮重点）

| 陷阱 | 表现 | 探针 |
| :--- | :--- | :--- |
| **分数口径漂移** | profile 过滤后报告/分数/退出码各自计算 | 同一文档 `--profile relaxed` 与默认对比三处数字 |
| **覆盖假完整** | 语言后端未探测却写"纯 Python 降级"；`complete=True` 但有失败审计器 | 构造空文档/缺后端场景 |
| **参数假生效** | `parameters:` 声明了但某节点未消费（默认值掩盖） | 16 参数矩阵 |
| **阈值回退静默** | 非法值只告警、validate 却不报错 | 非法 `image_min_dpi: 0` 跑 validate |
| **批量误报** | 全称捕获带前缀/章节 TOC 提及 | 构造前缀不同、TOC 提及两文档 |
| **基线性失效** | 旧 JSON 无 key → 全部判"新引入" | 删 key 字段后对比 |
| **profile 越权** | relaxed 隐藏 info 使分数虚高且未声明 | 对比默认/relaxed 的 score |
| **豁免静默过期** | 过期条目被静默删除或仍生效 | 改 `expires` 为昨天 |

### 6.6 每条 finding 提交前自问

① 当前 HEAD 还成立吗？② 有反例探针吗？③ 期望值与实测值都记录了吗？④ 是否同族还有？
⑤ 是否属于附录 B 的刻意设计？

---

## 七、对抗验证方法（强度递增）

| # | 方法 | 说明 |
| :--- | :--- | :--- |
| 1 | 复现反例 | 最小文档/最小配置，记录输入→实测→期望 |
| 2 | 邻域守卫 | 边界两侧都测（第 0/1 页、空/单元素、None/0） |
| 3 | 编码对抗 | UTF-8/BOM/GBK/Shift-JIS 重跑 |
| 4 | CJK 边界 | 中英混排、全角标点、数字+单位（µm/um）、纯空白 |
| 5 | 负向注入 | 改错 → 门禁 FAIL → 复原 |
| 6 | 独立参考 | python-pptx/python-docx 原生读取 vs Document 模型逐字段 |
| 7 | 同族扫描 | 限定路径 grep 同模式兄弟点（falsy/转义/硬编码/未展开 Group） |
| 8 | 元批判 | reaudit 时逐条独立复现并重算严重度 |
| 9 | **分数单调性** | 增加 1 条 error → 分数必降；增加 1 页相同问题 → 分数必升；同 findings 打乱顺序 → 同分 |
| 10 | **配置矩阵** | 16 全局参数 × {默认, 合法覆盖, 非法} 三态探针 |
| 11 | **旧版兼容** | 用手工构造的旧格式 JSON（无 key/无 score）跑 baseline |
| 12 | **时间边界** | `expires` = 昨天/今天/明天/非法；跨时区不影响 |
| 13 | **批量对照** | 单文件逐份结果 vs 批量聚合：score/coverage/BATCH 差异可解释 |

**判定**：无对抗验证的 finding 视为"待确认"；验证失败必须删除/降级并说明误报原因。

---

## 八、Finding 输出格式

```markdown
#### [F编号]〔P级别〕精炼标题

- **位置**：`相对路径:行号` + 符号名
- **严重度**：P0 发行阻塞 / P1 高危 / P2 应修复 / P3 治理增强
- **现象**：输入 → 实测输出 → 期望输出（多报/漏报/崩溃/口径漂移）
- **根因**：一句话机制
- **对抗验证**：方法编号 + 命令/输入/实测/断言（禁止引用旧报告数字）
- **影响**：格式/规则/执行路径（CLI/UI/API）；静默还是显式
- **修复建议**：≥2 方案 + 推荐 + 必备回归测试
- **状态**（fix 模式）：✅ 已修复（改动文件 + 新测试）/ ⏸ 仅报告
```

分级：
- **P0**：HTML 转义遗漏/离线红线/门禁假绿/DISPATCH 断裂致检查消失/SYS-ERROR 吞没/数据丢失。
- **P1**：配置流断裂、双重执行、falsy 陷阱、守卫缺路、字体链路断、分数/覆盖口径失真、
  baseline 身份失效（导致 CI 误判）。
- **P2**：死代码、回退漂移、弱断言、mock 盲区、批量误报、文档数字/结构漂移。
- **P3**：命名/注释/归档建议/门禁增强。

---

## 九、报告结构

1. **〇 审查概况**：模式（review/fix）、范围、基线（§2.1 全部实测值）、未执行步骤。
2. **一 基线结果**：五门禁 + 覆盖率 + `git status`。
3. **二 问题清单**：按 A–J 分节，每条套 §8 模板。
4. **三 对抗验证记录**：探针清单（方法编号/输入/实测/期望）、负向注入记录、同族扫描结果。
5. **四 覆盖矩阵**：`§9.4` 表格，每格标「已审/抽样/未审（原因）」。
6. **五 问题总表**：静默错误 → 验证可信度 → 正确性 → 治理，四批排序。
7. **六 保持项**：经本轮复核健康的机制（黄金测试三路径、注册表派生、编码回退、SYS-ERROR
   可见化、样式级标题回退、HF 离线注入、falsy 守卫、exemption_key 稳定性、三报告同源）。
8. **七 修复记录**（fix 模式）：逐条改动 + 新测试 + 复跑结果。
9. **附 执行记录**：命令清单、实测输出摘录、未验证声明。

### 9.4 覆盖矩阵模板

| 维度 \ 范围 | src/engines | src/auditors | src/converters | src/reporters | app/cli | tests | docs |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| A 架构 | | | | | | | |
| B 转换器/模型 | | | | | | | |
| C 配置/注册 | | | | | | | |
| D 审计语义 | | | | | | | |
| E 引擎/降级 | | | | | | | |
| F 安全/离线 | | | | | | | |
| G 测试 | | | | | | | |
| H 文档/门禁 | | | | | | | |
| I 分数/覆盖 | | | | | | | |
| J 批量/版本/Profile/豁免 | | | | | | | |

**提交前自检**：① 每条 finding 有行号+符号+探针；② 数字全为当轮实测；③ 覆盖矩阵无空格；
④ 保持项已列；⑤ 未验证项已声明；⑥ 已按 §6.4/6.6 过滤假阳性；⑦ 扫描未触碰 `.venv/`。

---

## 十、禁止事项

1. 禁止读取/扫描/审查/修改 `.venv/` 与生成物目录；禁止裸跑全仓库递归 grep/find/rg。
2. `review` 模式禁止改文件；`review-and-fix` 只允许"已复现缺陷 + 最小修复 + 回归测试"，
   禁止顺手重构与无关改动。
3. 禁止用黄金测试一致性/旧报告数字代替语义验证。
4. 禁止把"全绿"当"正确"；禁止用 profile 过滤后的结果冒充全量。
5. 禁止编造外部 API 语义；用最小脚本实测或标注待确认。
6. 禁止建议架构偏离（Auditor 硬编码参数、CustomRulesAuditor 写检查、Engine 反向依赖、
   Model 外部依赖、网络出口）。
7. 禁止对 P0/P1 打"不建议修改"标签后继续合入。
8. 禁止"清单在列、证据不落盘"。

---

## 附录 A：高危文件热区（优先通读）

| 文件 | 风险点 |
| :--- | :--- |
| `src/auditors/structure.py` | 0.3.0 新增 3 检查；`self.keywords` 初始化；标题/shape 判定 |
| `src/auditors/factual.py` | CON-007 单位前缀；缩写生命周期；`_LENGTH_UNITS` 消费 |
| `src/engines/rule_parser.py` | frontmatter 参数解析/回退；`_parse_list`；配置分支 |
| `src/engines/auditor_config.py` | 键集 SSOT；None/空列表语义 |
| `src/engines/scoring.py` | 权重/归一化/边界/估算半权 |
| `src/engines/coverage.py` | complete 语义；后端真实性；pptx_only 清单 |
| `src/engines/baseline.py` | 身份键；旧版兼容；`--fail-on-new` 行为 |
| `src/engines/batch.py` | 全称捕获；章节判定；单文件短路 |
| `src/engines/exemptions.py` | 过期比较；fail-open；created/reviewer |
| `src/cli.py` | 新 flag 组合；profile/fail-on 优先级；批量聚合口径 |
| `src/reporters/*` | score/coverage/key 三报告一致；转义 |
| `app.py` | 新增 metric/expander；批处理 context |

## 附录 B：刻意设计（非缺陷，勿报）

1. 包名 `src` 未改为 `docaudit`（BREAKING；见 CHANGELOG「未做项」）。
2. `cli.py`/`app.py` 未拆分（会打断黄金测试锚点）。
3. 无 LLM 语义评审（离线/轻依赖红线）。
4. 溢出、表格 fit、图片 DPI 为**估算**（`metadata.estimated`），分数按半权。
5. CON-004 为关键词/段落数启发式；CON-005 默认 info（团队可按口径升 warning）。
6. LanguageTool tier-3（纯 Python）语法/风格覆盖有限，由 Coverage 声明。
7. BATCH-* 仅批量模式；单文件不执行。
8. `rules validate` 对未知参数只 warning（运行时降级），对类型/范围 error。

## 附录 C：快速命令卡

```powershell
# 全量 + 覆盖率
python -m pytest tests/ -q --cov=src --cov-report=term

# 门禁
python -m pytest tests/test_gates.py -v
python -c "from src.auditors.custom_rules import CustomRulesAuditor; print(CustomRulesAuditor.validate_dispatch())"
python src/cli.py rules validate
python scripts/check_release.py

# 三报告一致（同一文档）
python src/cli.py tests/fixtures/sample.pptx -o "$env:TEMP/r.json" --fail-on none
python src/cli.py tests/fixtures/sample.pptx -o "$env:TEMP/r.html" --fail-on none
python src/cli.py tests/fixtures/sample.pptx -o "$env:TEMP/r.sarif" --fail-on none

# profile / baseline / 批量
python src/cli.py tests/fixtures/sample.pptx --profile relaxed --fail-on none
python src/cli.py tests/fixtures/sample.pptx --baseline "$env:TEMP/r.json" --fail-on none
python src/cli.py tests/fixtures --fail-on none

# 配置矩阵（示例：非法值必须 validate 报错）
python -c "import pathlib,tempfile; p=pathlib.Path(tempfile.mkdtemp())/'r.md'; p.write_text('---\nversion: \"1.0\"\nparameters:\n  image_min_dpi: 0\n---\n\n## STR-001: x\n- 严重度: error\n- 检查: first_slide_has_title_layout\n',encoding='utf-8'); print(p)"
```
