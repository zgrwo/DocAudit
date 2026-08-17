# DocAudit 用户手册

> 场景驱动的操作指南。API 签名 → [api-reference.md](api-reference.md) &nbsp;|&nbsp; 规则编写 → [rules.md](../rules.md)

---

## 场景速查

| 我要... | 看这里 |
|---------|--------|
| 审查一份技术评审 PPTX | [§场景1](#场景1-审查一份技术评审-pptx) |
| 批量审查整个项目文件夹 | [§场景2](#场景2-批量审查项目文件夹) |
| 改字体白名单/字号范围 | [§场景3](#场景3-自定义字体要求) |
| 添加新的半导体术语规则 | [§场景4](#场景4-添加新的术语规则) |
| 自动修复格式问题（字体/间距/溢出） | [§场景5](#场景5-自动修复格式问题) |
| 导出 HTML/JSON 审查报告 | [§场景6](#场景6-导出审查报告) |
| 豁免误报/噪音问题 | [§场景7](#场景7-豁免误报问题) |
| 只用命令行不用浏览器 | [§CLI](#cli-完整参数参考) |
| 了解 rules.md 怎么写 | [§规则编写](#rulesmd-写作指南) |

---

## 场景1: 审查一份技术评审 PPTX

**场景**：你刚完成一份先进封装工艺评审 PPT（30 页），需要在提交前检查格式和术语。

### 使用 Web UI

1. 启动服务: `.venv\Scripts\streamlit run app.py` → 浏览器打开 `http://localhost:8501`
2. 侧边栏确保选中 **📄 单文件** 模式
3. 拖拽你的 `.pptx` 文件到上传区域，或点击选择文件
4. 点击 **🔍 开始审查**
5. 等待 5-10 秒（30 页约 5 秒）
6. 查看结果：
   - 顶部显示 **错误/警告/信息** 计数卡片
   - 下方按严重度 + 类型列出所有发现
7. 点击每条发现展开查看：问题描述、位置、原文摘录、修改建议

### 使用 CLI

```bash
.venv\Scripts\python src/cli.py report.pptx -v
```

---

## 场景2: 批量审查项目文件夹

**场景**：项目交付前，需要审查 `D:\Project\Docs\` 下所有 PPTX/DOCX/PDF/MD 文件。

### 使用 Web UI

1. 侧边栏切换到 **📂 批量/文件夹** 模式
2. 方式一：在文本框中输入文件夹路径 `D:\Project\Docs`
3. 方式二：拖拽多个文件到"多文件上传"区域
4. 两种方式可同时使用，文件自动去重
5. 点击 **🔍 开始批量审查**
6. 进度条显示当前处理进度
7. 完成后先展示**按文件汇总表**，再展示详细发现

### 使用 CLI

```bash
# 审查整个目录
.venv\Scripts\python src/cli.py D:\Project\Docs\ -o batch_report.html

# 只看 PPTX 文件
.venv\Scripts\python src/cli.py D:\Project\Docs\ --format pptx

# 只看 DOCX 文件
.venv\Scripts\python src/cli.py D:\Project\Docs\ --format docx
```

---

## 场景3: 自定义字体要求

**场景**：你们团队的文档标准是 `Noto Sans SC` + `Arial Narrow`，而非默认字体。

编辑 `rules.md` 中的 `FMT-001` 规则：

```markdown
## FMT-001: 正文字体统一
- 严重度: warning
- 说明: 正文文本必须使用指定字体之一
- 字体: [Noto Sans SC, Arial Narrow, Calibri]
```

修改后无需重启服务 — Web UI 点击 **🔍 开始审查** 重新审查即可生效；CLI 重新运行即可。

### 字号范围调整

编辑 `FMT-002`：

```markdown
## FMT-002: 标题字号范围
- 严重度: warning
- 说明: 标题字号 32-44pt, 正文 14-24pt
- 标题: {min: 32, max: 44}
- 正文: {min: 14, max: 24}
```

### 单页文本量上限

编辑 `FMT-003`：

```markdown
## FMT-003: 每页文本量限制
- 严重度: warning
- 说明: 单页文本不应过于密集
- 检查: per_page_char_limit
- 最大字数: 300
```

### 表格文字与底色对比度

**场景**：表格使用深色表头底色时文字看不清（如深蓝底 + 深蓝字），需要强制"深底浅字 / 浅底深字"。

编辑 `FMT-008` 规则（阈值遵循 WCAG AA：正文 4.5:1、大字 3:1，可按需调整）：

```markdown
## FMT-008: 表格文字与底色对比度
- 严重度: warning
- 说明: 表格单元格的底色与文字颜色对比度不足会影响可读性；深色底色应配浅色文字，浅色底色应配深色文字
- 检查: table_contrast
- 最小对比度: 4.5
- 大字最小对比度: 3.0
- 大字字号阈值: 18
```

> 覆盖范围：PPTX / DOCX 原生表格。仅对能提取到 solid 纯色底色的单元格判定；无填充、渐变、主题色或嵌入 Excel 对象（OLE）会跳过，不误报。

---

## 场景4: 添加新的术语规则

**场景**：你发现团队文档中常把 `interposer` 简写为 `INT`，需要强制使用标准缩写。

### 方式 A：添加到术语表（推荐）

编辑 `glossary/advanced_packaging.yaml`，在 `terms:` 下新增：

```yaml
  - pattern: '(?i)\bINT\b'
    preferred: 'Interposer (中介层)'
    context: 芯片与基板之间的互连桥接层
    severity: warning
```

**注意事项**：
- `pattern` 必须用单引号包裹，避免 YAML 转义问题
- `(?i)` 表示不区分大小写
- `\b` 是单词边界，避免匹配到 `INTERNAL` 等词

### 方式 B：添加到 rules.md（快速 regex）

编辑 `rules.md`：

```markdown
## TERM-004: Interposer 术语规范
- 检查: regex
- 模式: "(?i)\bINT\b(?!.*[Ii]nterposer)"
- 建议: "建议使用标准缩写 Interposer 或完整术语 Interposer (中介层)"
- 严重度: warning
```

### 验证

运行 CLI 检查术语表是否加载成功：

```bash
.venv\Scripts\python src/cli.py report.pptx -v
# 应看到: "已加载术语表: 先进封装 (20 条术语)"
```

---

## 场景5: 自动修复格式问题

**场景**：审查报告显示 15 个字体问题 + 8 个间距问题，不想手动逐个修改。

```bash
# 修复全部 (字体 + 间距 + 溢出 + 标题标点 + 项目符号)
.venv\Scripts\python src/cli.py report.pptx --fix

# 仅修复字体和字号
.venv\Scripts\python src/cli.py report.pptx --fix --fix-type font

# 仅修复中英文间距
.venv\Scripts\python src/cli.py report.pptx --fix --fix-type spacing

# 仅修复元素溢出
.venv\Scripts\python src/cli.py report.pptx --fix --fix-type overflow

# 仅修复标题末尾标点
.venv\Scripts\python src/cli.py report.pptx --fix --fix-type title_punct

# 仅修复项目符号
.venv\Scripts\python src/cli.py report.pptx --fix --fix-type bullet
```

输出文件：`report_fixed.pptx`（原子写入，不会损坏原文件）。

| `--fix-type` 值 | 修复内容 | 支持格式 |
|-----------------|---------|---------|
| `all` (默认) | 全部修复 | PPTX/DOCX |
| `font` | 字体标准化 + 字号 ≥12pt | PPTX/DOCX |
| `spacing` | 中英文间自动加空格 | PPTX/DOCX |
| `overflow` | 溢出元素移回边界内 | PPTX only |
| `title_punct` | 去除标题末尾标点 | PPTX only |
| `bullet` | 项目符号统一为 `•` | PPTX only |

---

## 场景6: 导出审查报告

### Web UI 导出

审查完成后，侧边栏底部：
1. 点击 **📥 下载 HTML 报告** — 独立网页，可离线查看，含完整样式
2. 点击 **📥 下载 JSON 报告** — 结构化数据，可用于二次处理（Python/pandas/Excel）

> 下载的报告会尊重当前豁免设置 — 先过滤再下载。

### CLI 导出

```bash
# HTML 报告
.venv\Scripts\python src/cli.py report.pptx -o report.html

# JSON 报告
.venv\Scripts\python src/cli.py report.pptx -o report.json

# 批量模式 — 每文件自动编号
.venv\Scripts\python src/cli.py docs/ -o batch_report.html
# 输出: batch_report_01.html, batch_report_02.html, ...
```

---

## 场景7: 豁免误报问题

**场景**：审查报告中有 20 条 Info 级别的术语建议，这些在你的文档中已知且可接受。

### Web UI 豁免

**批量豁免**（发现列表顶部按钮栏）：
- 🟢 **豁免全部 Info** — 一键清除所有提示
- 🟡 **豁免全部 Warning** — 一键清除所有警告
- 📋 **豁免全部可见** — 清除当前显示的全部问题
- 按类型豁免（下拉选择）— 一键清除某一类型的所有问题

**单条豁免**：每条发现卡片内的 **🚫 豁免** 按钮。

**恢复豁免**：侧边栏 **🔄 清除全部豁免** 恢复所有被隐藏的问题。

### 永久排除（修改规则）

如果想永久关闭某条规则，编辑 `rules.md`，注释或删除该规则块，或将其严重度改为 `info`。

---

## CLI 完整参数参考

```bash
doc-audit <path> [选项]
# 或
python src/cli.py <path> [选项]
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `path` | 位置参数 | *必填* | 文件或目录路径 |
| `--rules` | `str` | `rules.md` | 自定义规则文件路径 |
| `--glossary` | `str` | `glossary` | 术语表目录路径 |
| `--vocab` | `str` | `None` | 词汇表目录 (默认 `glossary/../vocab/`) |
| `-o`, `--output` | `str` | `None` | 输出报告 (.html 或 .json) |
| `-v`, `--verbose` | flag | `False` | 详细日志输出 |
| `--format` | choice | `all` | 按格式过滤: `pptx` / `docx` / `pdf` / `md` / `all` |
| `--fix` | flag | `False` | 自动修复格式问题 |
| `--fix-type` | choice | `all` | 修复类型: `all` / `font` / `spacing` / `overflow` / `title_punct` / `bullet` |

### 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 无 Error 级问题（可能有 Warning/Info） |
| 1 | 存在 Error 级问题 |

---

## rules.md 写作指南

### 规则块格式

```markdown
## RULE-ID: 规则描述
- 严重度: error | warning | info
- 说明: 规则的详细说明 (可选)
- 检查: check_type       ← 对应 DISPATCH 表中的 key
```

### 属性键参考

| 属性键 | 适用类型 | 值示例 |
|--------|---------|--------|
| `严重度` | 全部 | `error` / `warning` / `info` |
| `说明` | 全部 | 规则描述文本 |
| `检查` | check 类型 | `first_slide_has_title_layout` / `duplicate_title` / ... |
| `模式` | regex 类型 | `"(?i)pattern"` (双引号内的正则表达式) |
| `建议` | regex 类型 | `"修改建议文本"` |
| `字体` | FMT-001 | `[微软雅黑, Arial, Calibri]` |
| `标题/正文` | FMT-002 | `{min: 28, max: 40}` / `{min: 12, max: 22}` |
| `最大字数` | FMT-003 | `200` |
| `最小对比度` | FMT-008 | `4.5` (WCAG AA 正文) |
| `大字最小对比度` | FMT-008 | `3.0` (WCAG AA 大字) |
| `大字字号阈值` | FMT-008 | `18` (pt) |
| `最大英文词数/最大中文字数` | STR-004 | `10` / `40` |
| `最小标题字号` | STR-001 | `28` (标题页大号标题判定阈值) |
| `关键词` | CON-004 | `[结论, 总结, Summary, Conclusion]` |
| `豁免版式` | CON-004 | `[标题幻灯片, Title Slide]` |
| `章节` | CON-002 | `[概述, 工艺流程, 关键参数, 结论]` |

### 内置检查（不经 rules.md 配置）

以下检查由审计器内置实现，**不通过 rules.md 声明/关闭**，豁免请用报告中的豁免面板按 rule_id 操作：

| rule_id | 内容 | 位置 |
|---------|------|------|
| `FMT-MIXED-001~003` | 中英混排规范（CJK-Latin 间距、中文标点） | LanguageAuditor |
| `VOCAB-REJECT` | 词汇表黑名单（`vocab/reject.txt`） | LanguageAuditor |
| `PY-SPELL` / `PY-ZH-GRAMMAR` | 拼写与中文语法（LanguageTool 三层降级） | LanguageAuditor |
| `SYS-ERROR` | 系统级错误（审计器/规则执行失败时产生） | 流水线 |

### regex vs check 类型

- **regex**：模式匹配 — 无需写 Python 代码，直接声明正则即可。适用于术语/用词规则。
- **check**：检查委托 — 需在对应 Auditor 中实现方法，并注册到 `_DISPATCH` 表。适用于需要结构化逻辑的检查。

---

## 术语表维护

### 添加新术语

编辑 `glossary/` 下对应的 YAML 文件：

```yaml
- pattern: '(?i)regex_pattern'
  preferred: 'Standard Term (标准术语)'
  context: 术语说明及使用场景
  severity: error  # 可选: error | warning | info，默认 warning
```

### 修改现有术语

修改对应 YAML 中的 `preferred` 或 `severity` 字段即可。

### YAML 语法注意事项

- `pattern` 必须用单引号包裹：`'(?i)pattern'`（双引号内反斜杠会被 YAML 转义）
- 缩进必须是空格（不能用 Tab）
- `context` 字段建议中英文对照

---

## 常见问题

**Q: 为什么英文语法检查不工作？**
启动 LanguageTool 服务即可：`docker-compose up -d`（推荐，~0.5s/页）。或安装 Java 让系统自动启动（~1s/页）。Python 内置模式仅提供中文语法正则 + 智能英文拼写。

**Q: 审查结果太多怎么办？**
(1) 侧边栏 → 排除噪音规则 (2) 批量豁免 Info/Warning (3) 按类型豁免。过滤后下载报告。

**Q: 文档审查后数据安全吗？**
完全安全。所有处理在本地完成，上传的文件存临时目录，审查结束后自动删除。无任何数据上报逻辑。

**Q: 支持哪些文件格式？**
PPTX (.pptx, .ppt), DOCX (.docx, .doc), PDF (.pdf), Markdown (.md, .markdown, .txt)。

**Q: 如何在不启动 Web UI 的情况下使用？**
CLI 完全支持所有功能：`python src/cli.py report.pptx -o report.html --fix`。

**Q: 为什么 PDF 的字体/溢出检查没有结果？**
PDF 转换仅提取文本和标题级别，无字体/位置元数据。如需完整检查请使用 PPTX/DOCX 格式。

---

<!-- last_updated: 2026-07-11 -->
