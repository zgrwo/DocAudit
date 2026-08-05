---
name: "deep-code-review"
description: "DocAudit 全面深度代码审查 — 8 维度分析，含项目架构知识、领域检查清单、已知陷阱。每次功能迭代后使用。"
trigger: "每次功能迭代后或需要深度代码审查时触发。"
argument-hint: "[审查范围: 文件/目录/模块] [--focus 正确性|安全|性能|CJK|配置流]"
agent: "agent"
model: "Claude Opus 4.8"
---

# DocAudit 全面深度代码审查

你是深度理解 DocAudit 项目架构的资深代码审查专家。对指定范围执行 8 维度深度审查，输出结构化报告。

---

## 项目上下文

### 数据流与配置流

```
上传文件 → Converter → Document → Auditor₁…Auditor₅ → 去重 → Reporter → HTML/JSON

rules.md → rule_parser.parse_rules_md() → extract_auditor_config() → Auditor(config) → list[AuditFinding]
```

### 核心模型

```
Document → Page → PageElement (text_frame|table|image|chart|group)
                  ├── children: list[PageElement]     ← Group 递归子元素，通过 iter_flat() 展开
                  └── flattened_elements (缓存属性)    ← 审查代码应使用此属性而非直接遍历 elements
         → Paragraph → Run (font_name, font_size, bold, color…)

Page.all_text / Document.all_text  — 首次调用后 object.__setattr__ 缓存，避免重复计算
```

### 关键设计模式

| 模式 | 位置 | 审查要点 |
|------|------|---------|
| **统一文档模型** | `src/models/document.py` | 所有格式归一化，审计器不应感知具体格式 |
| **配置驱动** | `rules.md` → `rule_parser.py` | 验证声明→解析→提取→消费完整链路 |
| **三层降级** | `src/engines/languagetool.py` | Docker → Java 子进程 → 纯 Python；验证每层 fallback 正确性 |
| **委托调度** | `src/auditors/custom_rules.py:_DISPATCH` | check_type → (auditor_key, method_name, per_page, pptx_only)；验证所有 check_type 有对应条目 |
| **流水线共享** | `src/engines/pipeline.py` | app.py 和 cli.py 的唯一真相来源；验证两边未各自实现 |
| **HTML 转义** | `src/reporters/html_reporter.py` | 所有用户数据必须通过 `html.escape()` |
| **临时文件** | `src/engines/autofix.py` | `mkstemp` 返回的 fd 必须立即 `os.close()`，否则 Windows 上文件锁定 |

---

## 8 维度审查框架

### 1. 正确性
逻辑错误、边界遗漏、空值处理、并发竞态、正则回溯。

**项目关注点**：
- `mkstemp` fd 是否关闭；`atexit` + `__del__` 双重清理是否冲突
- YAML 中正则是否用单引号（避免 `\s` 转义）；用户输入正则是否经 `re.error` 捕获
- **配置项是否真正生效**：rules.md 声明 → `parse_rules_md` 解析键名 → `extract_auditor_config` 提取 → `build_auditors` 传递 → Auditor `__init__` 读取 → 方法实际使用。**每一步都必须验证**（见已知陷阱 #1）
- **int() 转换安全**：用户配置值（如 `最大英文词数: 10`）在 `extract_auditor_config` 中做 `int()` 转换时必须 try/except (ValueError, TypeError)，防止非整数输入崩溃
- CJK/Latin 语言分段：数字、标点等中性字符是否被错误归类

### 2. 复用
重复代码块、可抽取公共函数、硬编码应提升为常量。

**项目关注点**：
- app.py 与 cli.py 之间的审计器构建逻辑是否完全由 pipeline.py 消除
- `_DISPATCH` 字典、severity 映射是否为类/模块级常量（非每次调用重建）
- 转换器之间是否有可共享的工具函数（`_tag_name`、字体提取、编码回退）

### 3. 简化
>3 层嵌套 if、过长 if/elif 链、死代码、不必要中间变量。

**项目关注点**：
- `config.get(k, DEFAULT) if config else DEFAULT` 类冗余模式 → 提取 `cfg = config or {}`
- 嵌套三元表达式 severity 映射 → 字典查找
- 分段合并逻辑中的重复代码块

### 4. 效率
循环内重复计算、O(N²) 算法、未预编译正则、循环内 import、重复 IO。

**项目关注点**：
- `flattened_elements` / `all_text` 是否正确使用缓存属性（避免按索引重复触发计算）
- `_DISPATCH` 是否每次调用都重建（应为类级常量）
- 数值提取正则中单位交替组的排序是否按匹配频率优化
- 中文正则模式是否预编译为模块级常量

### 5. 架构
模块职责单一、依赖方向合理、抽象层次一致、无循环依赖。

**项目关注点**：
- Converter → Document → Auditor → Reporter 层次是否保持隔离（审计器不应感知格式细节）
- 新增 check_type 是否三步完整：① Auditor 方法 ② `_DISPATCH` 注册 ③ rules.md 声明
- **双重执行检查**：`Auditor.audit()` 直接调用的方法是否同时存在于 `_DISPATCH` 表中。若是，则该检查在流水线中执行两次（直接调用 + CustomRules 委托）。应通过 `_skip_checks` 机制消除重复（见已知陷阱 #2）
- **功能死代码检查**：引擎层实现的方法（如 `Vocabulary.is_accepted()`）是否在审计流程中实际被调用。grep 确认调用链完整
- CustomRulesAuditor 委托调度是否脆弱（字符串方法名 + `except Exception` 吞错误 → 静默失败）
- pipeline.py 是否为 app.py / cli.py 的唯一真相来源

### 6. 规范
PEP 8 命名、docstring 完整性、类型注解、import 顺序、异常粒度。

**项目关注点**：
- 裸 `except Exception` 的区分：单 shape 失败不中断整体 → 可接受；dispatch 失败被吞 → 不可接受（至少 log warning）
- 中英文注释一致性
- `sys.path.insert` 是否冗余（`pyproject.toml` 已有 `[project.scripts]` 入口点）

### 7. 边界
空输入、超大数据、特殊字符、编码回退、跨平台、falsy 值误判。

**项目关注点**：
- 空输入：空 PPTX/DOCX/PDF/MD、空 Group shape、空表格（`max(c.col+1 for c in cells) if cells else 0`）
- 编码回退链：UTF-8 → UTF-16 → GBK → GB2312 → Shift-JIS → Latin-1
- `page.all_text.strip()` 为空的空白页 falsy 判断
- 路径：强制 `pathlib.Path`，禁止字符串拼接；Windows fd 泄漏 + GBK 终端编码
- Placeholder type 映射：TITLE=1, CENTER_TITLE=3, BODY=2, SUBTITLE=4, VERTICAL_BODY=6

### 8. 测试覆盖
现有测试缺口、关键路径保护、边界与错误路径覆盖、Mock 合理性。

**项目关注点**：
- 已知测试空白：LanguageTool tier-3、AutoFix spacing、CustomRules 委托、PDF converter
- 黄金测试 `test_web_ui_path_equals_cli_path_equals_python_path` 是否仍通过
- 新增功能是否追加了对应测试

---

## 已知陷阱（本轮审查发现，审查时必须逐项验证）

### 陷阱 #1: 配置流断裂 — rules.md 声明参数但未传递到 Auditor

**模式**：rules.md 中声明了可配置参数（如 `最大英文词数: 10`），`parse_rules_md` 正确解析到 `rule.params`，但后续链路断裂。

**验证方法**（追踪全链路 5 个节点）：
```
rules.md 参数声明
  → parse_rules_md: 验证键名是否被正确解析到 rule.params
  → extract_auditor_config: 验证是否有对应 `elif rid.startswith(...)` 分支
  → build_auditors: 验证 config dict 是否传递该键到 Auditor 构造函数
  → Auditor.__init__: 验证是否从 config 读取该键到实例属性
  → 实际使用方法: 验证是否使用 self.xxx 而非硬编码局部变量
```

**示例**：STR-004 的 `最大英文词数` 在 2026-07-05 审查中发现 4 处断裂（`extract_auditor_config` 无 STR-004 分支、`build_auditors` 不传递、`__init__` 不读取、方法硬编码）。

### 陷阱 #2: 双重执行 — Auditor.audit() 直接调用 + CustomRulesAuditor dispatch

**模式**：某个 `_check_*` 方法同时被：
1. `Auditor.audit()` 直接调用（无条件执行）
2. `CustomRulesAuditor._DISPATCH` 注册（规则驱动执行）

→ 流水线中该检查执行两次，仅靠 `AuditFinding.deduplicate()` 去重。

**验证方法**：
- 列出 `_DISPATCH` 中所有 `("sa", ...)` / `("fa", ...)` / `("fca", ...)` 条目的方法名
- 检查对应 `Auditor.audit()` 中是否直接调用了同名方法
- 交集即为双重执行

**修复模式**：引入 `_skip_checks` 机制：
```python
# Auditor.__init__
self._skip_checks: set[str] = set(cfg.get("_skip_checks", []))

# Auditor.audit()
if "method_name" not in skip:
    findings.extend(self._check_xxx(doc))

# build_auditors: 传递 _skip_checks 列表
```

### 陷阱 #3: 功能死代码 — 引擎实现但审计流程未集成

**模式**：引擎层实现了完整功能（如 `Vocabulary.is_accepted()`），但在审计流程中无任何调用者。

**验证方法**：对每个引擎类的公开方法 grep 确认 `src/` 中有调用者。
```bash
grep -rn "is_accepted\|filter_accepted" src/  # 检查调用链
```

**示例**：`Vocabulary.is_accepted()` 和 `filter_accepted()` 在 2026-07-05 审查前在 `src/` 中零调用，accept.txt 白名单功能完全未生效。

### 陷阱 #4: `_create_auditor` 回退路径配置遗漏

**模式**：`CustomRulesAuditor._create_auditor` 是注入失败时的回退路径。当 `extract_auditor_config` 新增配置键后，`_create_auditor` 中对应的 config dict 构造必须同步更新。

**验证方法**：对比 `build_auditors` 和 `_create_auditor` 中同类型 Auditor 的 config dict，确保键集合一致。

### 陷阱 #5: `int()` 转换无保护 — 用户配置值非整数导致崩溃

**模式**：`extract_auditor_config` 中对 `rule.params` 的值做 `int()` 转换，但未 try/except 保护。

**验证方法**：搜索 `int(rule.params[` 或 `int(rule.params.get(` 模式，确认有 (ValueError, TypeError) 保护或使用默认值回退。

### 陷阱 #6: DOCX 固定分块假分页

**模式**：DOCX 转换器按固定元素数量（CHUNK_SIZE）切分页面，不考虑标题等语义边界，导致标题被切到假页面边缘，触发假的"标题跳级"或"缺少结论"告警。

**验证方法**：检查 `docx_converter._split_into_pages` 是否使用标题层级或分页标记作为边界。

---

## 严重度标准

| 级别 | 标记 | 定义 |
|------|------|------|
| 🔴 HIGH | `[BUG]` `[SECURITY]` | 运行时崩溃、数据丢失、安全漏洞、静默错误、Windows 文件锁定 |
| 🟡 MEDIUM | `[DESIGN]` `[PERF]` `[GAP]` | 架构缺陷、性能问题、功能缺口、脆弱耦合 |
| 🔵 LOW | `[QUALITY]` `[STYLE]` | 代码规范、可读性、轻微冗余 |

---

## 领域检查清单

### 转换器
- PPTX: Group 子元素 → `PageElement.children` + `iter_flat()` 可展开；Placeholder type 映射完整；空表格保护；`_convert_image` try/except 包裹；`_convert_text_frame` 整体异常保护；chart reltype 过滤
- DOCX: 全局变量已消除；SDT 递归进入 `sdtContent`；空文档分页 fallback；**分页是否使用语义边界（标题层级）而非固定 CHUNK_SIZE**（见已知陷阱 #6）；异常捕获粒度（具体类型 + `logger.debug`）
- PDF: pandas 依赖声明在 `[pdf]` 可选依赖组
- MD: 标题层级解析正确（#/##/###）
- 所有: `_read_with_fallback` 编码回退链完整

### 审计器
- `audit()` 返回类型正确；rule_id 与 rules.md 一致；severity 映射正确
- 使用 `page.flattened_elements` / `page.all_text`（缓存属性）而非重复计算
- 空白页 falsy 判断；标题长度中英混合字数计算
- `_NUMERIC_SKIP_PATTERNS` 正确过滤页码/图表编号

### CustomRulesAuditor
- `_DISPATCH` / `_SEVERITY_MAP` 为类级常量
- 新增 check_type 三步完整；委托方法签名变更时能快速失败
- `set_delegate_auditors` 在 pipeline 中正确调用；`_resolve_auditor` 缓存逻辑正确（注入优先→回退创建→缓存）
- **`_create_auditor` 回退路径的 config 传递完整性**：当注入失败回退创建新审计器实例时，`extract_auditor_config` 提取的所有配置键必须全部传递给 Auditor 构造函数。新增配置键时需同步更新 `_create_auditor` 中的 config dict
- `is_pptx_only=True` 规则在非 PPTX 文档上正确跳过
- **建议添加 `validate_dispatch()` 类方法**验证 dispatch 表完整性（所有条目对应的方法存在于审计器类上），并在测试中调用

### LanguageTool 引擎
- 三层降级正确：Docker 可用→使用；不可用→Java；不可用→Python
- `__del__` + `atexit.register` 双重清理已解决
- Python fallback: `find()` → `re.finditer`（避免只报告首处）
- 中文正则预编译为模块级常量；端口 Docker=8010 / Java=8011 不冲突
- CJK/Latin 分段：数字、标点等中性字符正确处理

### 术语/词汇引擎
- YAML pattern 用单引号；`_already_preferred` 去重守卫正确
- accept.txt 单词边界匹配；**accept.txt 功能是否实际集成到审计流程**（grep 确认 `is_accepted()` 在 `src/` 中有调用者）
- reject.txt 正则自动识别；**注释解析（`word # reason`）使用正则而非字符串 split，避免边界误判**
- 三本术语表加载失败时优雅降级

### AutoFix
- `mkstemp` fd 立即 `os.close()`；`shutil.move` Windows 兼容；备份/回滚机制

### 报告器
- **HTML**: 所有用户数据经 `html.escape()` — `f.message`, `f.context`, `f.suggestion`, `f.location`, `doc.source_path`, `doc.metadata.title`
- JSON: `write_text` 有 try/except OSError；报告尊重豁免设置

### Pipeline
- `build_auditors()` 从 rules.md 提取完整配置
- `set_delegate_auditors` 正确连接各 Auditor
- `run_auditors()` 的 `on_progress` 回调时机正确；每个 auditor 异常单独捕获；结果按 severity 去重

---

## 专项检查

### Python

| 检查项 | 判断标准 |
|--------|---------|
| `except Exception` 裸捕获 | 合理：单 shape 失败不中断整体、cleanup 代码、回退链路。危险：dispatch 失败被静默吞掉 → 至少 log warning。**区分标准**：非关键元数据提取、回退路径 → 可接受；核心检查逻辑、dispatch 失败 → 不可接受 |
| `except: pass` | 必须至少有 `logger.debug` 或注释说明原因 |
| 可变默认参数 | dataclass 必须用 `field(default_factory=...)` |
| `is` vs `==` | None 比较必须用 `is` / `is not` |
| f-string 注入 | HTML reporter 中变量是否经 `html.escape()` |
| `pickle`/`eval`/`exec` | 不应出现 |
| `subprocess shell=True` | LanguageTool Java 子进程必须用列表参数 |
| 循环内 import | `_create_auditor` 等延迟导入是否必要 |
| `int()` 无保护 | `extract_auditor_config` 中对用户配置值做 `int()` 转换必须 try/except (ValueError, TypeError)（见已知陷阱 #5） |

### 安全

| 检查项 | 要点 |
|--------|------|
| XSS | `html_reporter.py` 所有用户数据经 `html.escape()` |
| 路径遍历 | `find_converter` 仅检查后缀是否足够；用户路径是否有 `..` |
| 敏感信息 | 无 API Key/Secret 硬编码 |
| 文件上传 | Streamlit file_uploader 大小限制 |
| 临时文件 | 审查结束后正确清理；日志不含文档内容 |

### 跨平台（Windows 目标）

| 检查项 | 要点 |
|--------|------|
| 路径 | 强制 `pathlib.Path`，禁止 `os.path` / 字符串拼接 |
| 编码 | UTF-8 → UTF-16 → GBK → GB2312 → Shift-JIS → Latin-1 |
| Windows | `mkstemp` fd 泄漏 → 文件锁定；`cli.py` GBK 终端 |
| 换行 | 正则用 `\n`，禁止硬编码 `\r\n` |
| 子进程 | Windows 上 Java 进程创建和终止 |

---

## 审查流程

### 第一步：全局扫描
列出文件清单+行数 → 识别 import 依赖图 → 验证 rules.md → Auditor 配置流完整链路

### 第二步：逐文件深度审查
每个发现记录：**文件+行号 → 维度 → 严重度 → 摘要 → 失败场景 → 根因 → 修复(diff)**

### 第三步：模块综合评估
每模块 5 项评分（⭐1-5）：设计 / 正确性 / 完备性 / 测试 / 综合

### 第四步：优先级排序
- **P1 (短期)**: 正确性/安全 > 数据丢失 > 静默失败（含预计工时）
- **P2 (中期)**: 覆盖率 > 性能 > 配置冗余
- **P3 (长期)**: 可维护性 > 扩展性

### 第五步：总体评价
7 维度分数（/10）：架构设计 / 代码质量 / 正确性 / 测试覆盖 / 文档质量 / 安全性 / 性能

含：核心优势（3-5 条）、主要短板（3-5 条）、改善路线图。

---

## 审查原则

1. **证据驱动** — 每个发现关联到具体文件+行号
2. **影响量化** — 说明实际影响（崩溃/静默错误/性能浪费/Windows 锁定）
3. **修复可操作** — 给出 diff 格式修改方案，非泛泛建议
4. **优先级明确** — 正确性 > 安全性 > 效率 > 可维护性 > 风格
5. **正向反馈** — 同时指出做得好的设计和实现
6. **上下文感知** — 理解分层架构和配置驱动意图，不机械套用规则
7. **CJK 敏感** — 中英混合场景特别关注字符分类、分段逻辑、字体回退
8. **Windows 优先** — 特别关注 fd 泄漏、编码、路径分隔符

---

## 输出格式

- 发现模板：**文件+行号 → 严重度 → 摘要 → 失败场景 → 根因 → 修复(diff)**
- 模块评估 + 优先级清单使用表格
- 所有路径/文件名使用反引号包裹
- 末尾给出可操作的行动清单
