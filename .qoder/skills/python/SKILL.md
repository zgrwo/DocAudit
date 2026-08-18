---
name: python
description: >
  DocAudit Python 开发规范。
  在编写、审查或重构 DocAudit Python 代码时使用，涵盖：
  Auditor 开发、Finding 创建、_DISPATCH 注册、_skip_checks 配置、
  rules.md 规则编写、中文文本规范、测试编写、AutoFix 实现。
trigger: "编写、审查或重构 DocAudit Python 代码时触发。"
last_updated: 2026-07-11
---
# DocAudit Python 开发规范

从 DocAudit 项目中提炼的实战模式。

## 核心规则速查表

> 🔴 = 会导致静默错误（不崩溃但结果错误）&nbsp;&nbsp;|&nbsp;&nbsp;多 § 引用时第一个 § 为主规则。

| 场景 | 规则 | § |
|------|------|---|
| 新增 check_type | 🔴 必须三处注册：Auditor 方法 + `_DISPATCH` + `_skip_checks` | §1.1 |
| 新增规则声明 | 🔴 必须在 `rules.md` 中声明，否则 CustomRulesAuditor 不执行 | §1.1 |
| per_page=True 方法 | 签名必须为 `(self, page, doc)`，CustomRulesAuditor 逐页调用 | §1.2 |
| Finding 消息 | 必须中文；`message` 说明问题，`suggestion` 给出修改建议 | §2.1 |
| Finding rule_id | 必须与 `rules.md` 中的规则 ID 一致 | §2.2 |
| Finding context | 截断到 50-150 字符，避免报告冗余 | §2.3 |
| `_skip_checks` | 只在 `pipeline.py` 的 `build_auditors()` 中设置，不在 Auditor 构造时预设 | §1.3 |
| HTML 报告 | 🔴 所有用户文本必须 `html.escape()` — 见 `src/reporters/html_reporter.py` | §2.4 |

## 1. Auditor 开发规范

### 1.1 新增 check_type 的三步注册法

每新增一个可通过 `rules.md` 配置的检查类型，必须修改 3 个位置，缺一不可：

**位置 1：在对应 Auditor 中新增方法**

```python
# src/auditors/structure.py (或 format.py / factual.py)
def _check_xxx(self, page, doc) -> list[AuditFinding]:  # per_page=True
    """检查说明"""
    ...
    return findings
```

方法签名由 `_DISPATCH` 中的 `per_page` 决定：
- `per_page=True` → `(self, page, doc)`
- `per_page=False` → `(self, doc)`

**位置 2：在 `_DISPATCH` 表中注册**

```python
# src/auditors/custom_rules.py — _DISPATCH 字典
"xxx_check_type": ("sa", "_check_xxx", True, False),
#                   ↑       ↑            ↑     ↑
#               auditor_key  method_name  per_page  pptx_only
```

auditor_key: `"sa"`=StructureAuditor, `"fa"`=FormatAuditor, `"fca"`=FactualAuditor

**位置 3：在 `_skip_checks` 中排除**

```python
# src/engines/pipeline.py — build_auditors()
"_skip_checks": [..., "xxx_check_type"],
```

这确保 Auditor 自身的 `audit()` 不直接执行该检查，而是由 CustomRulesAuditor 通过 Dispatch 统一调度，避免重复执行。

### 1.2 per_page vs 全局方法

```python
# per_page=True: 方法签名 (page, doc)，CustomRulesAuditor 逐页迭代
def _check_element_overflow(self, page, doc) -> list[AuditFinding]:
    page_label = f"第 {page.slide_number or page.index+1} 页"
    ...

# per_page=False: 方法签名 (doc)，CustomRulesAuditor 传整个文档
def _check_figure_caption_format(self, doc) -> list[AuditFinding]:
    for page in doc.pages:
        ...
```

### 1.3 在 Auditor.audit() 中添加调用

当 check 方法可通过 `_DISPATCH` 调度时，在 `audit()` 中需加 skip 守卫：

```python
# 在 audit() 方法中
if "xxx_check_type" not in skip:
    for page in doc.pages:          # per_page=True
        findings.extend(self._check_xxx(page, doc))
```

### 1.4 Auditor 配置获取

配置从 `self.config` 读取，在 `__init__` 中解析为实例属性，提供合理的默认值：

```python
def __init__(self, config: dict | None = None):
    super().__init__(config)
    cfg = config or {}
    self.max_value = cfg.get("max_value", DEFAULT_MAX)
```

## 2. Finding 创建规范

### 2.1 message 和 suggestion

```python
AuditFinding(
    message="问题描述，说明发现了什么",        # 事实陈述，不含建议
    suggestion="建议如何修改",                 # 可操作的建议
    ...
)
```

- `message`: 中文，简洁陈述，50 字以内
- `suggestion`: 中文，可操作，告诉用户怎么做
- 严重度: `ERROR`=必须修复, `WARNING`=建议修复, `INFO`=仅供参考

### 2.2 rule_id 命名

```python
rule_id="STR-006"   # 必须与 rules.md 中的 ## RULE-ID 一致
```

规则 ID 前缀:
- `STR-xxx` → StructureAuditor（结构）
- `FMT-xxx` → FormatAuditor（格式）
- `CON-xxx` → FactualAuditor（事实/内容）
- `TERM-xxx` → TerminologyChecker（术语，regex 类型）
- `PY-xxx` → LanguageAuditor 内置 Python 检查

### 2.3 context 截断

```python
context=text[:100]           # 中文/英文通用截断到 100-150 字符
context=text[:80] + "..."    # 超长文本加省略号
```

### 2.4 HTML 转义（报告生成时）

```python
# src/reporters/html_reporter.py — 必须转义所有用户文本
import html
html.escape(f.message)
html.escape(f.context)
html.escape(f.suggestion)
html.escape(f.location)
html.escape(doc.source_path)
```

## 3. 自定义规则 (rules.md) 声明规范

### 3.1 规则块格式

```markdown
## RULE-ID: 规则描述
- 严重度: error | warning | info
- 说明: 规则详细说明
- 检查: check_type        ← 对应 _DISPATCH 中的 key
```

### 3.2 regex 类型规则

```markdown
## TERM-XXX: 术语规则描述
- 检查: regex
- 模式: "正则表达式"       ← 使用双引号包裹
- 建议: "修改建议"
- 严重度: error
```

regex 规则的 `检查: regex` 不需要在 `_DISPATCH` 中注册 — 由 `_execute_regex_rule()` 直接处理。

## 4. 测试编写规范

### 4.1 创建测试用 PPTX

```python
from pptx import Presentation
from pptx.util import Inches, Pt

prs = Presentation()
slide_layout = prs.slide_layouts[0]  # title slide
slide = prs.slides.add_slide(slide_layout)
slide.shapes.title.text = "测试标题"

tmp_path = Path(tmpdir) / "test.pptx"
prs.save(str(tmp_path))
```

### 4.2 Auditor 方法测试

```python
from src.converters import PptxConverter
converter = PptxConverter()
doc = converter.convert(str(tmp_path))

auditor = FormatAuditor()
findings = auditor.audit(doc)
assert any("预期消息" in f.message for f in findings)
```

### 4.3 术语/词汇表测试

```python
# 使用 tmp_path fixture 写入临时 YAML/TXT
glossary_file = tmp_path / "test.yaml"
glossary_file.write_text("""
category: 测试
terms:
  - pattern: '(?i)test.pattern'
    preferred: 'Test Pattern (TP)'
""", encoding="utf-8")
```

## 5. AutoFix 实现规范

### 5.1 原子写入模式

所有 fix 方法必须使用原子写入（临时文件 → 成功 → 替换）：

```python
import tempfile, os, shutil

tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pptx", prefix="autofix_", dir=target.parent)
os.close(tmp_fd)
try:
    shutil.copy2(source, tmp_path)
    # ... 修改 tmp_path ...
    prs.save(str(tmp_path))
    shutil.move(tmp_path, str(target))
except Exception:
    Path(tmp_path).unlink(missing_ok=True)
    raise
```

### 5.2 链式修复

CLI 中的 `--fix` 支持链式修复：前一个 fix 的输出作为后一个 fix 的输入：

```python
out = file_path.parent / f"{file_path.stem}_fixed{file_path.suffix}"
fixer.fix_pptx(file_path, out)       # Step 1: 字体
fixer.fix_spacing(out, out)          # Step 2: 间距（在 Step 1 输出上继续）
```

## 6. 中文文本规范

### 6.1 用户可见文本

- 所有 `message`, `suggestion`, `location` 使用中文
- 技术缩写保留英文大写（如 TSV, FOWLP）
- 页码格式: `第 {n} 页`
- 位置格式: `第 {n} 页 [{layout_name}]`

### 6.2 日志/调试文本

- 日志可用英文或中文
- 错误/警告信息使用中文以便用户理解
- 开发者调试信息可用英文

## 7. 常见陷阱

| 陷阱 | 后果 | 解决方案 |
|------|------|---------|
| 新增 check 只写 Auditor 方法，忘注册 `_DISPATCH` | CustomRulesAuditor 不执行 | 三步注册法 (§1.1) |
| 忘加 `_skip_checks` | 同一检查执行两次 | `pipeline.py` 中加排除 |
| `per_page=True` 但方法签名为 `(self, doc)` | CustomRulesAuditor 调用时报错 | 改为 `(self, page, doc)` |
| Finding 的 `rule_id` 与 `rules.md` 不一致 | 用户无法追溯规则来源 | 严格对齐 |
| `context` 字段不截断 | HTML 报告中显示异常 | 截断到 100-150 字符 |
| 修改 rules.md 格式但不更新 `rule_parser.py` | 新字段无法解析 | 同步更新 `parse_rules_md()` |
| falsy 值误判（`0`/`""`/`[]`/`None` 混用布尔判断） | 静默跳过检查或漏报 | Python falsy 陷阱清单 → [falsy-pitfalls.md](falsy-pitfalls.md)（SSOT：本文件只链接引用） |
