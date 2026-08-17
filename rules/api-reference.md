# DocAudit API 参考

> 函数签名速查。**签名唯一信源** — 所有公开接口在此定义。
> 完整用法 → [用户手册](user-manual.md) &nbsp;|&nbsp; 编码规范 → [skills/python/SKILL.md](../skills/python/SKILL.md)
> 结构导航 → [project-structure.md](project-structure.md)

**总模块**: 15 | **总公开函数**: 30+ | **规则**: 26 条

---

## Converters（转换器）

`src/converters/` — 多格式 → 统一 Document 模型

### BaseConverter `src/converters/base.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `can_handle` | `(source_path: str \| Path)` | `bool` | 抽象方法 — 扩展名匹配 |
| `convert` | `(source_path: str \| Path)` | `Document` | 抽象方法 — 格式 → Document |

### PptxConverter `src/converters/pptx_converter.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `can_handle` | `(source_path: str \| Path)` | `bool` | `.pptx` / `.ppt` 扩展名匹配 |
| `convert` | `(source_path: str \| Path)` | `Document` | 完整解析 PPTX → Document。提取 Run 级字体/颜色/位置/版式/备注/图片/图表 |

### DocxConverter `src/converters/docx_converter.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `can_handle` | `(source_path: str \| Path)` | `bool` | `.docx` / `.doc` 扩展名匹配 |
| `convert` | `(source_path: str \| Path)` | `Document` | DOCX → Document。段落样式→shape_name，大纲级别→level |

### PdfConverter `src/converters/pdf_converter.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `can_handle` | `(source_path: str \| Path)` | `bool` | `.pdf` 扩展名匹配 |
| `convert` | `(source_path: str \| Path)` | `Document` | PDF → Document (Docling)。回退 Markdown 导出 |

### MarkdownConverter `src/converters/md_converter.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `can_handle` | `(source_path: str \| Path)` | `bool` | `.md` / `.markdown` / `.txt` 扩展名匹配 |
| `convert` | `(source_path: str \| Path)` | `Document` | Markdown → Document。多编码回退 (UTF-8→GBK→Shift-JIS)，YAML frontmatter → metadata |

---

## Auditors（审查器）

`src/auditors/` — Document → [AuditFinding, ...]

### StructureAuditor `src/auditors/structure.py`

| 方法 | 签名 | 规则 ID | 说明 |
|------|------|---------|------|
| `__init__` | `(config: dict \| None)` | — | `required_sections`, `conclusion_keywords`, `exempt_layouts`, `max_english_words`, `max_chinese_chars_title`, `_skip_checks` |
| `audit` | `(doc: Document)` | — | → `list[AuditFinding]` |
| `_check_title_slide` | `(doc: Document)` | STR-001 | 首张幻灯片必须为标题版式 |
| `_check_heading_levels` | `(doc: Document)` | STR-003 | 标题层级不跳级 (H1→H2→H3) |
| `_check_figure_numbering` | `(doc: Document)` | STR-002 | 图表编号连续性 + 重复 + 倒退检测 |
| `_check_required_sections` | `(doc: Document)` | CON-002 | 必须包含指定章节 |
| `_check_slide_structure_consistency` | `(doc: Document)` | STR-008 | 幻灯片版式多样性检查 |
| `_check_every_slide_has_conclusion` | `(doc: Document)` | CON-004 | 每页须有关键要点 |
| `_check_title_length` | `(doc: Document)` | STR-004 | 标题长度限制 (英文词数/中文字数) |
| `_check_title_trailing_punctuation` | `(page: Page, doc: Document)` | STR-006 | 标题末尾标点检测 |
| `_check_duplicate_title` | `(doc: Document)` | STR-005 | 跨幻灯片重复标题 |
| `_check_figure_caption_format` | `(doc: Document)` | STR-007 | 图表标题格式一致性 |

### FormatAuditor `src/auditors/format.py`

| 方法 | 签名 | 规则 ID | 说明 |
|------|------|---------|------|
| `__init__` | `(config: dict \| None)` | — | `allowed_fonts`, `title_size_range`(28,40), `body_size_range`(12,22), `alignment_tolerance`(5.0), `max_chinese_chars`(150), `max_english_chars`(300), `max_chars_per_page`(200), `min_contrast`(4.5), `large_text_min_contrast`(3.0), `large_text_threshold`(18), `_skip_checks` |
| `audit` | `(doc: Document)` | — | → `list[AuditFinding]` |
| `_check_font_consistency` | `(page: Page)` | FMT-001 | 字体是否在允许列表中 (按页+字体聚合) |
| `_check_global_font_consistency` | `(doc: Document)` | FMT-001 | 全文字体种类统计 |
| `_check_font_size` | `(page: Page)` | FMT-002 | 标题/正文字号范围检查 |
| `_check_alignment` | `(page: Page)` | — | 同列文本框垂直对齐 |
| `_check_layout_consistency` | `(doc: Document)` | — | PPTX 版式使用合理性 |
| `_check_paragraph_length` | `(page: Page)` | FMT-004 | 单段不超过3行 (中文/英文/显式换行) |
| `_check_element_overflow` | `(page: Page, doc: Document)` | FMT-005 | 元素不超出幻灯片边界 (容差 5pt) |
| `_check_per_page_char_limit` | `(page: Page, doc: Document)` | FMT-003 | 单页文本量上限 |
| `_check_empty_placeholders` | `(page: Page, doc: Document)` | FMT-006 | 空白占位符检测 (PPTX only) |
| `_check_bullet_consistency` | `(page: Page, doc: Document)` | FMT-007 | 项目符号样式一致性 |
| `_check_table_contrast` | `(page: Page, doc: Document)` | FMT-008 | 表格底色 vs 字体色 WCAG 对比度 (PPTX/DOCX) |
| `_hex_to_rgb` / `_relative_luminance` / `_contrast_ratio` | 模块级纯函数 | — | WCAG 对比度计算 (FMT-008) |

### LanguageAuditor `src/auditors/language.py`

| 方法 | 签名 | 规则 ID | 说明 |
|------|------|---------|------|
| `__init__` | `(config: dict \| None)` | — | `languagetool_url`, `glossary_dir`, `vocab_dir` |
| `audit` | `(doc: Document)` | — | → `list[AuditFinding]` |
| `_check_text` | `(text, page_index, page_label)` | PY-SPELL, PY-ZH-GRAMMAR | LanguageTool 拼写/语法 (三层降级) |
| `_check_mixed_formatting` | `(text, page_index, page_label)` | FMT-MIXED-001~003 | CJK-Latin 间距 + 标点 |
| `_check_rejected_vocab` | `(text, page_index, page_label)` | — | reject.txt 禁用词匹配 |
| `_segment_by_language` | `(text)` | — | → `list[(text, "zh"\|"en")]` 语言分段 |

### FactualAuditor `src/auditors/factual.py`

| 方法 | 签名 | 规则 ID | 说明 |
|------|------|---------|------|
| `__init__` | `(config: dict \| None)` | — | `_skip_checks` |
| `audit` | `(doc: Document)` | — | → `list[AuditFinding]` |
| `_check_numeric_consistency` | `(doc: Document)` | CON-001 | 数值跨页一致性 (上下文聚类) |
| `_check_abbreviation_first_defined` | `(doc: Document)` | CON-003 | 缩写首次出现未定义 |
| `_check_abbreviation_defined_never_used` | `(doc: Document)` | CON-003-A | 定义后未再次使用 |
| `_check_abbreviation_multiply_defined` | `(doc: Document)` | CON-003-B | 同一缩写重复定义 |
| `_check_abbreviation_used_before_defined` | `(doc: Document)` | CON-003-C | 缩写在定义前使用 |
| `_scan_abbreviations` | `(doc: Document)` | — | → `dict` 全量缩写扫描 (缓存) |

### CustomRulesAuditor `src/auditors/custom_rules.py`

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(config: dict \| None)` | `rules_path` |
| `load_rules` | `(rules_path: str \| Path)` | 加载 rules.md |
| `set_delegate_auditors` | `(sa, fa, fca)` | 注入主流水线审计器实例 |
| `audit` | `(doc: Document)` | → `list[AuditFinding]` 执行所有 check 规则 |
| `validate_dispatch` | `()` (classmethod) | → `list[str]` 验证所有 DISPATCH 条目有效 |

**DISPATCH 表** (check_type → auditor_key, method, per_page, pptx_only):

| check_type | 审计器 | 方法 | 逐页 | PPTX only |
|-----------|--------|------|------|-----------|
| `first_slide_has_title_layout` | sa | `_check_title_slide` | ✗ | ✓ |
| `figure_numbering_sequential` | sa | `_check_figure_numbering` | ✗ | ✗ |
| `heading_level_sequential` | sa | `_check_heading_levels` | ✗ | ✗ |
| `numeric_cross_reference` | fca | `_check_numeric_consistency` | ✗ | ✗ |
| `abbreviation_first_defined` | fca | `_check_abbreviation_first_defined` | ✗ | ✗ |
| `abbreviation_defined_never_used` | fca | `_check_abbreviation_defined_never_used` | ✗ | ✗ |
| `abbreviation_multiply_defined` | fca | `_check_abbreviation_multiply_defined` | ✗ | ✗ |
| `abbreviation_used_before_defined` | fca | `_check_abbreviation_used_before_defined` | ✗ | ✗ |
| `every_slide_has_conclusion` | sa | `_check_every_slide_has_conclusion` | ✗ | ✗ |
| `duplicate_title` | sa | `_check_duplicate_title` | ✗ | ✗ |
| `title_trailing_punctuation` | sa | `_check_title_trailing_punctuation` | ✓ | ✗ |
| `figure_caption_format` | sa | `_check_figure_caption_format` | ✗ | ✗ |
| `element_overflow` | fa | `_check_element_overflow` | ✓ | ✗ |
| `per_page_char_limit` | fa | `_check_per_page_char_limit` | ✓ | ✗ |
| `empty_placeholder` | fa | `_check_empty_placeholders` | ✓ | ✓ |
| `bullet_consistency` | fa | `_check_bullet_consistency` | ✓ | ✗ |
| `table_contrast` | fa | `_check_table_contrast` | ✓ | ✗ |
| `slide_structure_consistency` | sa | `_check_slide_structure_consistency` | ✗ | ✓ |
| `title_length` | sa | `_check_title_length` | ✗ | ✗ |

> sa=StructureAuditor, fa=FormatAuditor, fca=FactualAuditor

---

## Engines（引擎）

`src/engines/` — 可复用后端服务

### Pipeline `src/engines/pipeline.py`

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `find_converter` | `(file_path: str)` | `Converter \| None` | 自动匹配转换器 |
| `build_auditors` | `(rules_path, glossary_dir, vocab_dir)` | `list[(name, auditor)]` | 构建配置好的审计器列表 |
| `run_auditors` | `(doc: Document, auditors: list, on_progress=None)` | `list[AuditFinding]` | 顺序执行审计器 → 去重 |

### RuleParser `src/engines/rule_parser.py`

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `parse_rules_md` | `(file_path: str \| Path)` | `list[AuditRule]` | 解析 rules.md → 规则对象列表 |
| `extract_auditor_config` | `(rules: list)` | `dict` | 从规则中提取 Auditor 配置参数 |

### TerminologyChecker `src/engines/terminology.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `__init__` | `(glossary_dir: str \| Path \| None = None)` | — | 加载目录中所有 .yaml 术语表 |
| `load_glossaries` | `(glossary_dir: str \| Path)` | `None` | 加载/重载术语规则 (就地修改 self.glossaries) |
| `check` | `(text, page_index, page_label)` | `list[AuditFinding]` | 对文本执行术语检查 (含跳过去重) |

数据类（同文件）:

| 类 | 字段 | 说明 |
|------|------|------|
| `TermRule` | `pattern` / `preferred` / `context` / `severity` | 单条术语规则 (regex 编译) |
| `TermGlossary` | `category` / `terms` | 术语表 (对应一个 YAML 文件) |

### LanguageToolClient `src/engines/languagetool.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `__init__` | `(base_url: str = DEFAULT_URL, timeout: int = 30, auto_start: bool = True)` | — | 初始化三层降级 |
| `is_available` | (属性) | `bool` | 是否有可用后端 |
| `check` | `(text: str, language: str = "auto", mother_tongue: str \| None = None)` | `list[dict]` | 语法拼写检查 (Docker→Java→Python) |
| `check_chinese_only` | `(text: str)` | `list[dict]` | 仅中文检查 |
| `check_english_only` | `(text: str)` | `list[dict]` | 仅英文检查 |
| `reset` | `()` | — | 清除缓存并重新探测后端 |
| `shutdown` | `()` | — | 关闭 Java 子进程，清理资源 |

### AutoFixer `src/engines/autofix.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `__init__` | `(allowed_fonts=None)` | — | 默认字体: [微软雅黑, Arial, Noto Sans SC, Calibri] (对齐 rules.md FMT-001) |
| `fix_pptx` | `(source, target)` | `Path` | 字体标准化 + 字号修正 (PPTX) |
| `fix_docx` | `(source, target)` | `Path` | 字体标准化 + 字号修正 (DOCX) |
| `fix_spacing` | `(source, target)` | `Path` | CJK-Latin 间距修复 (PPTX/DOCX) |
| `fix_element_overflow` | `(source, target)` | `Path` | 溢出元素移回边界内 (PPTX only) |
| `fix_title_punctuation` | `(source, target)` | `Path` | 去除标题末尾标点 (PPTX only) |
| `fix_bullet_style` | `(source, target, preferred="•")` | `Path` | 统一项目符号样式 (PPTX only) |
| `fix_count` | (属性) | `int` | 最后一次修复的变更数 |

### Vocabulary `src/engines/vocabulary.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `__init__` | `(vocab_dir: str \| Path \| None = None)` | — | 加载白名单/黑名单目录 |
| `load` | `(vocab_dir: str \| Path)` | — | 加载/重载词汇表 (accept.txt + reject.txt) |
| `is_accepted` | `(word: str)` | `bool` | 是否在白名单中 (大小写不敏感) |
| `should_reject` | `(text: str)` | `list[(word, reason)]` | 匹配黑名单 |
| `filter_accepted` | `(words: set)` | `set` | 过滤出白名单中的词 |

---

## Models（数据模型）

`src/models/` — 系统通用语言

### Document `src/models/document.py`

| 字段 | 类型 | 说明 |
|------|------|------|
| `source_path` | `str` | 原始文件路径 |
| `format` | `str` | `"pptx"` \| `"docx"` \| `"pdf"` \| `"md"` |
| `metadata` | `DocumentMetadata` | title, author, created, modified, slide_count, page_count, word_count, custom_properties |
| `pages` | `list[Page]` | 页/幻灯片列表 |
| `all_text` (属性) | `str` | 全文拼接 (缓存) |
| `all_paragraphs` (属性) | `list[Paragraph]` | 全文档段落 |

### Page `src/models/document.py`

| 字段/属性 | 类型 | 说明 |
|----------|------|------|
| `index` | `int` | 页索引 (0-based) |
| `elements` | `list[PageElement]` | 页内元素列表 |
| `layout_name` | `str \| None` | PPTX 版式名称 |
| `slide_number` | `int \| None` | 幻灯片编号 (1-indexed) |
| `notes` | `str \| None` | 演讲者备注 |
| `flattened_elements` (属性) | `list[PageElement]` | 递归展开 Group 子元素 (缓存) |
| `all_text` (属性) | `str` | 该页所有文本 (缓存) |
| `all_paragraphs` (属性) | `list[Paragraph]` | 该页所有段落 |
| `text_frames` (属性) | `list[PageElement]` | 仅文本框类型 |
| `tables` (属性) | `list[PageElement]` | 仅表格类型 |

### PageElement `src/models/document.py`

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `str` | `"text_frame"` \| `"table"` \| `"image"` \| `"chart"` \| `"group"` |
| `paragraphs` | `list[Paragraph]` | 段落列表 |
| `tables` | `list[list[TableCell]]` | 表格数据 (按行) |
| `children` | `list[PageElement]` | Group 子元素 |
| `left` / `top` / `width` / `height` | `float \| None` | 位置尺寸 (pt) |
| `shape_name` | `str \| None` | PPTX shape 名称 / DOCX 样式名 |
| `is_title` | `bool` | 是否为标题占位符 |
| `is_body` | `bool` | 是否为正文占位符 |
| `is_placeholder` | `bool` | 是否为占位符 |
| `image_blob` / `image_ext` | `bytes \| None` / `str \| None` | 图片数据 |
| `chart_type` / `chart_data` | `str \| None` / `dict \| None` | 图表数据 |
| `iter_flat()` | 生成器 | 递归展开自身 + 所有子孙 |

### TableCell `src/models/document.py`

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | `str` | 单元格文本 |
| `row` / `col` | `int` | 行/列索引 (0-based) |
| `rowspan` / `colspan` | `int` | 合并单元格跨度 (默认 1) |
| `font_name` / `font_size` | `str \| None` / `float \| None` | 首 run 字体信息 (FMT-008 大字判定依据) |
| `fill_color` | `str \| None` | 单元格底色 hex RGB (e.g. "1E3A5F")；无填充/渐变/主题色为 None |
| `font_color` | `str \| None` | 首 run 字体色 hex RGB (e.g. "FFFFFF")；未提取到为 None |

### AuditFinding `src/models/finding.py`

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `FindingType` | `structure` \| `format` \| `language` \| `terminology` \| `factual` \| `custom` |
| `severity` | `FindingSeverity` | `error` \| `warning` \| `info` |
| `message` | `str` | 问题描述 |
| `rule_id` | `str \| None` | 触发的规则 ID |
| `page_index` | `int \| None` | 所在页 (0-indexed) |
| `element_index` | `int \| None` | 页内元素索引 |
| `context` | `str \| None` | 原文摘录 |
| `suggestion` | `str \| None` | 修改建议 |
| `location` | `str \| None` | 人类可读位置 (如 "第 3 页") |
| `metadata` | `dict` | 额外元数据 |
| `id` | `str` | 自动生成 12 位 hex UUID |
| `dedup_key` (属性) | `str` | 去重键: `"{type}\|{rule_id}\|{page}\|{context 前 120 字符的 md5 哈希}"` |
| `to_dict()` | `dict` | 序列化 |
| `from_dict(data)` (classmethod) | `AuditFinding` | 反序列化 |
| `deduplicate(findings)` (static) | `list[AuditFinding]` | 去重 (保留最高严重度) |

---

## Reporters（报告生成）

`src/reporters/` — AuditFinding → HTML / JSON

### HtmlReporter `src/reporters/html_reporter.py`

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `generate_html_report` | `(doc: Document, findings: list[AuditFinding], title: str, output_path: str \| Path \| None, file_label: str \| None = None)` | `str` | 生成独立 HTML 报告，所有用户文本已 `html.escape()`；`file_label` 用于批量模式覆盖头部"文件:"行 |

### JsonReporter `src/reporters/json_reporter.py`

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `generate_json_report` | `(doc: Document, findings: list[AuditFinding], output_path: str \| Path \| None)` | `dict` | 生成 JSON 报告，可选写入文件 |

---

## CLI（命令行入口）

`src/cli.py` — 命令行审查入口

| 函数 | 签名 | 说明 |
|------|------|------|
| `audit_file` | `(file_path, rules_path="rules.md", glossary_dir="glossary", vocab_dir=None, verbose=False)` → `(Document, list[AuditFinding])` | 执行单文件审查并返回结果 |
| `print_summary` | `(findings)` | 打印审查结果摘要 |
| `doctor_check` | `()` → `int` | 环境诊断：检查运行环境健康状态，失败项 > 0 时返回 1 |

---

<!-- last_updated: 2026-08-05 -->
