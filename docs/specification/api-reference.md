# DocAudit API 参考

> 函数签名速查。**签名唯一信源** — 所有公开接口在此定义。
> 完整用法 → [用户手册](../user-manual/user-manual.md) &nbsp;|&nbsp; 编码规范 → [skills/python/SKILL.md](../../skills/python-SKILL.md)
> 结构导航 → [project-structure.md](../governance/project-structure.md)

**总模块**: 28 | **规则**: 26 条

---

## Converters（转换器）

`src/converters/` — 多格式 → 统一 Document 模型

### `BaseConverter` `src/converters/base.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `can_handle` | `(source_path: str \| Path)` | `bool` | 抽象方法 — 扩展名匹配 |
| `convert` | `(source_path: str \| Path)` | `Document` | 抽象方法 — 格式 → Document |

### `PptxConverter` `src/converters/pptx_converter.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `can_handle` | `(source_path: str \| Path)` | `bool` | `.pptx` / `.ppt` 扩展名匹配 |
| `convert` | `(source_path: str \| Path)` | `Document` | 完整解析 PPTX → Document。提取 Run 级字体/颜色/位置/版式/母版/备注/图片/图表、继承字体/字号、真实项目符号、Group 绝对坐标、图片 alt/像素尺寸、图表标题/图例 |

### `DocxConverter` `src/converters/docx_converter.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `can_handle` | `(source_path: str \| Path)` | `bool` | `.docx` / `.doc` 扩展名匹配 |
| `convert` | `(source_path: str \| Path)` | `Document` | DOCX → Document。段落样式→style_name，大纲级别→level |
| `_warn_unparsed_nested_content` | `(doc: DocxDocument)` | `None` | 未解析嵌套内容 (文本框/页眉页脚/脚注) 跳过时输出 logger.warning，不改变解析行为 |

### `PdfConverter` `src/converters/pdf_converter.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `__init__` | `(backend: str \| None = None)` | — | `None`/`"auto"` 自动探测（有 PyMuPDF 用 PyMuPDF）\| `"pymupdf"` \| `"docling"`；环境变量 `DOCAUDIT_PDF_BACKEND` 可覆盖 |
| `can_handle` | `(source_path: str \| Path)` | `bool` | `.pdf` 扩展名匹配 |
| `convert` | `(source_path: str \| Path)` | `Document` | PDF → Document；auto 模式选择 PyMuPDF/Docling，PyMuPDF 缺失时回退 Docling |
| `_convert_with_pymupdf` | `(source_path: Path)` | `Document` | PyMuPDF 路径：文本块 + 书签标题层级 + bbox 几何（无表格结构、无 docling 模型依赖） |
| `_convert_with_docling` | `(source_path: Path)` | `Document` | Docling 路径：版面分析 + 表格结构；保留 Markdown 导出回退 |

> 后端选择辅助函数：`_select_pdf_backend(explicit=None) -> str`、`_import_pymupdf() -> module | None`（模块级，测试可 monkeypatch）。

### `MarkdownConverter` `src/converters/md_converter.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `can_handle` | `(source_path: str \| Path)` | `bool` | `.md` / `.markdown` / `.txt` 扩展名匹配 |
| `convert` | `(source_path: str \| Path)` | `Document` | Markdown → Document。多编码回退 (UTF-8→GBK→Shift-JIS)，YAML frontmatter → metadata |

---

## Auditors（审查器）

`src/auditors/` — Document → [AuditFinding, ...]

### `StructureAuditor` `src/auditors/structure.py`

| 方法 | 签名 | 规则 ID | 说明 |
|------|------|---------|------|
| `__init__` | `(config: dict \| None)` | — | `required_sections`, `required_sections_severity`, `conclusion_keywords`, `exempt_layouts`, `max_english_words`, `max_chinese_chars_title`, `min_title_font_size`, `_skip_checks` |
| `audit` | `(doc: Document)` | — | → `list[AuditFinding]` |
| `_check_title_slide` | `(doc: Document)` | STR-001 | 首张幻灯片必须为标题版式 |
| `_check_heading_levels` | `(doc: Document)` | STR-003 | 标题层级不跳级 (H1→H2→H3；仅非 PPTX，PPTX para.level 为缩进级别由方法内守卫跳过) |
| `_check_figure_numbering` | `(doc: Document)` | STR-002 | 图表编号连续性 + 重复 + 倒退检测 |
| `_check_required_sections` | `(doc: Document)` | CON-002 | 必须包含指定章节 |
| `_check_slide_structure_consistency` | `(doc: Document)` | STR-008 | 幻灯片版式多样性检查 |
| `_check_master_consistency` | `(doc: Document)` | STR-MASTER | 多母版检测 |
| `_check_every_slide_has_conclusion` | `(doc: Document)` | CON-004 | 每页须有关键要点 (仅 PPTX 适用) |
| `_check_title_length` | `(doc: Document)` | STR-004 | 标题长度限制 (英文词数/中文字数) |
| `_check_title_trailing_punctuation` | `(page: Page, doc: Document)` | STR-006 | 标题末尾标点检测 |
| `_check_duplicate_title` | `(doc: Document)` | STR-005 | 跨幻灯片重复标题 |
| `_check_figure_caption_format` | `(doc: Document)` | STR-007 | 图表标题格式一致性 |

### `FormatAuditor` `src/auditors/format.py`

| 方法 | 签名 | 规则 ID | 说明 |
|------|------|---------|------|
| `__init__` | `(config: dict \| None)` | — | `allowed_fonts`, `title_size_range`(28,44), `body_size_range`(12,32), `alignment_tolerance`(5.0), `max_chinese_chars`(150), `max_english_chars`(300), `max_chars_per_page`(200), `min_contrast`(4.5), `large_text_min_contrast`(3.0), `large_text_threshold`(18), `rule_severities`(rule_id→严重度覆盖, 2026-09-06 C-1), `enabled_rule_ids`(rules.md 声明驱动, 2026-10-28), `_skip_checks` |
| `audit` | `(doc: Document)` | — | → `list[AuditFinding]` |
| `_check_font_consistency` | `(page: Page)` | FMT-001 | 字体是否在允许列表中 (西文 latin 与中文 eastAsia 分别判定，按页+字体+作用域聚合) |
| `_check_global_font_consistency` | `(doc: Document)` | FMT-001 | 全文字体种类统计 |
| `_check_font_size` | `(page: Page)` | FMT-002 | 标题/正文字号范围检查 |
| `_check_alignment` | `(page: Page)` | FMT-ALIGN | 同页文本框行/列对齐 (标题与正文不互比) |
| `_check_element_overlap` | `(page: Page, doc: Document)` | FMT-OVERLAP | 元素重叠 (25% 阈值；排除嵌套/空占位/全屏背景) |
| `_check_safe_margin` | `(page: Page, doc: Document)` | FMT-SAFE-MARGIN | 元素贴边检查 (默认 1% 安全边距) |
| `_check_text_overflow` | `(page: Page, doc: Document)` | FMT-TEXT-OVERFLOW | 文本框内容溢出估算 (非像素级) |
| `_check_footer_consistency` | `(doc: Document)` | FMT-FOOTER | 页脚/页码/日期占位符部分缺失 |
| `_check_image_quality` | `(page: Page, doc: Document)` | FMT-IMAGE | 图片宽高比/DPI/alt text |
| `_check_chart_labeling` | `(page: Page, doc: Document)` | FMT-CHART | 图表标题缺失 |
| `_check_layout_consistency` | `(doc: Document)` | — | PPTX 版式使用合理性 |
| `_check_paragraph_length` | `(page: Page)` | FMT-004 | 单段不超过3行 (中文/英文/显式换行) |
| `_check_element_overflow` | `(page: Page, doc: Document)` | FMT-005 | 元素不超出幻灯片边界 (容差 5pt) |
| `_check_per_page_char_limit` | `(page: Page, doc: Document)` | FMT-003 | 单页文本量上限 |
| `_check_empty_placeholders` | `(page: Page, doc: Document)` | FMT-006 | 空白占位符检测 (PPTX only) |
| `_check_bullet_consistency` | `(page: Page, doc: Document)` | FMT-007 | 项目符号样式一致性 |
| `_check_table_contrast` | `(page: Page, doc: Document)` | FMT-008 | 表格底色 vs 字体色 WCAG 对比度 (PPTX/DOCX) |
| `_hex_to_rgb` / `_relative_luminance` / `_contrast_ratio` | 模块级纯函数 | — | WCAG 对比度计算 (FMT-008) |

### `LanguageAuditor` `src/auditors/language.py`

| 方法 | 签名 | 规则 ID | 说明 |
|------|------|---------|------|
| `__init__` | `(config: dict \| None)` | — | `languagetool_url`, `glossary_dir`, `vocab_dir` |
| `audit` | `(doc: Document)` | — | → `list[AuditFinding]` |
| `_check_text` | `(text, page_index, page_label)` | PY-SPELL | LanguageTool 拼写/语法 (三层降级) |
| `_check_builtin_chinese_patterns` | `(text, page_index, page_label)` | PY-ZH-GRAMMAR | 中文基础语法/标点模式，始终执行 |
| `_check_punctuation` | `(text, page_index, page_label)` | PUNCT-001~007 | 重复/冲突标点、全半角、配对、省略号/破折号 |
| `_check_redundancy` | `(text, page_index, page_label)` | TXT-REDUNDANT | 高精度中文冗余表达 |
| `_check_mixed_formatting` | `(text, page_index, page_label)` | FMT-MIXED-001~003 | CJK-Latin 间距 + 标点 |
| `_check_rejected_vocab` | `(text, page_index, page_label)` | — | reject.txt 禁用词匹配 |
| `_segment_by_language` | `(text)` | — | → `list[(text, "zh"\|"en")]` 语言分段 |

### `FactualAuditor` `src/auditors/factual.py`

| 方法 | 签名 | 规则 ID | 说明 |
|------|------|---------|------|
| `__init__` | `(config: dict \| None)` | — | `vocab_dir`(领域缩写白名单), `_skip_checks` |
| `audit` | `(doc: Document)` | — | → `list[AuditFinding]` |
| `_check_numeric_consistency` | `(doc: Document)` | CON-001 | 数值跨页一致性 (上下文聚类；年份/季度/节点为限定词) |
| `_check_abbreviation_first_defined` | `(doc: Document)` | CON-003 | 缩写首次出现未定义 |
| `_check_abbreviation_defined_never_used` | `(doc: Document)` | CON-003-A | 定义后未再次使用 |
| `_check_abbreviation_multiply_defined` | `(doc: Document)` | CON-003-B | 同一缩写重复定义 |
| `_check_abbreviation_used_before_defined` | `(doc: Document)` | CON-003-C | 缩写在定义前使用 |
| `_scan_abbreviations` | `(doc: Document)` | — | → `dict` 全量缩写扫描 (缓存) |

### `CustomRulesAuditor` `src/auditors/custom_rules.py`

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(config: dict \| None)` | `rules_path`, `vocab_dir`(TERM-* 白名单) |
| `load_rules` | `(rules_path: str \| Path)` | 加载 rules.md |
| `set_delegate_auditors` | `(sa, fa, fca)` | 注入主流水线审计器实例 |
| `audit` | `(doc: Document)` | → `list[AuditFinding]` 执行所有 check 规则 |
| `validate_dispatch` | `()` (classmethod) | → `list[str]` 验证所有注册条目有效（方法存在性） |
| `skip_checks_for` | `(auditor_key: str)` (classmethod) | → `list[str]` 该 Auditor 应跳过的内部守卫键（pipeline 用，替代手写 `_skip_checks`） |

**注册表** (`CHECK_REGISTRY: dict[str, CheckSpec]`) 是唯一真相来源；`_DISPATCH` 与
pipeline 的 `_skip_checks` 由它派生（2026-10-29 起不再手改）。`CheckSpec` 字段：
`auditor` / `method` / `per_page` / `pptx_only` / `skip_key`（空串表示与 check_type 同名）。

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
| `every_slide_has_conclusion` | sa | `_check_every_slide_has_conclusion` | ✗ | ✓ |
| `duplicate_title` | sa | `_check_duplicate_title` | ✗ | ✗ |
| `title_trailing_punctuation` | sa | `_check_title_trailing_punctuation` | ✓ | ✗ |
| `figure_caption_format` | sa | `_check_figure_caption_format` | ✗ | ✗ |
| `element_overflow` | fa | `_check_element_overflow` | ✓ | ✓ |
| `per_page_char_limit` | fa | `_check_per_page_char_limit` | ✓ | ✓ |
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

数据类（同文件）:

| 类 | 字段 | 说明 |
|------|------|------|
| `AuditRule` | `rule_id` / `category` / `severity` / `description` / `check_type` / `params` / `raw_text` | 单条审查规则 (`parse_rules_md` 返回) |

### `TerminologyChecker` `src/engines/terminology.py`

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

### `LanguageToolClient` `src/engines/languagetool.py`

> 本地探活：`localhost` 在构造时归一为 `127.0.0.1`（Windows IPv6 白等 ~2s）；
> Tier-1 探活结果进程级缓存 30s（`_PROBE_TTL`），同一进程重复审查不再重复探测；
> `reset()` 清除该 URL 的缓存并立即重探。

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `__init__` | `(base_url: str = DEFAULT_URL, timeout: int = 30, auto_start: bool = True)` | — | 初始化三层降级 |
| `is_available` | (属性) | `bool` | 是否有可用后端 |
| `check` | `(text: str, language: str = "auto", mother_tongue: str \| None = None)` | `list[dict]` | 语法拼写检查 (Docker→Java→Python) |
| `reset` | `()` | — | 清除缓存并重新探测后端 (有测试覆盖; 供外部手动重启探测) |

模块级函数（同文件）:

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `check_chinese_patterns` | `(text: str)` | `list[dict]` | 中文基础语法/标点模式；始终执行，不依赖 LanguageTool 后端 |

### `AutoFixer` `src/engines/autofix.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `__init__` | `(allowed_fonts=None)` | — | 默认字体: [微软雅黑, Arial, Noto Sans SC, Calibri] (对齐 rules.md FMT-001) |
| `fix_pptx` | `(source, target)` | `Path` | 字体标准化 (latin + a:ea) + 字号修正 (PPTX) |
| `fix_docx` | `(source, target)` | `Path` | 字体标准化 (latin + w:eastAsia) + 字号修正 (DOCX) |
| `fix_spacing` | `(source, target)` | `Path` | CJK-Latin 间距修复 (PPTX/DOCX) |
| `fix_element_overflow` | `(source, target)` | `Path` | 溢出元素移回边界内 (PPTX only) |
| `fix_title_punctuation` | `(source, target)` | `Path` | 去除标题末尾标点 (PPTX only) |
| `fix_bullet_style` | `(source, target, preferred="•")` | `Path` | 统一项目符号样式 (PPTX only) |
| `fix_count` | (属性) | `int` | 最后一次修复的变更数 |

### `Vocabulary` `src/engines/vocabulary.py`

| 方法 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `__init__` | `(vocab_dir: str \| Path \| None = None)` | — | 加载白名单/黑名单目录 |
| `load` | `(vocab_dir: str \| Path)` | — | 加载/重载词汇表 (accept.txt + reject.txt) |
| `is_accepted` | `(word: str)` | `bool` | 是否在白名单中 (大小写不敏感) |
| `should_reject` | `(text: str)` | `list[(word, reason)]` | 匹配黑名单 |
| `filter_accepted` | `(words: set)` | `set` | 过滤出白名单中的词 |

### CheckRegistry `src/engines/check_registry.py`

dispatch 检查的单一真相来源（Engine 层纯声明，避免 Engine → Auditor 反向依赖）。
`_DISPATCH`（`custom_rules`）与 `_skip_checks`（`pipeline`）均由它派生。

| 符号 | 签名/字段 | 说明 |
|------|-----------|------|
| `CheckSpec` | `(auditor: str, method: str, per_page: bool = False, pptx_only: bool = False, skip_key: str = "")` | 单条检查声明；`skip_key` 为空表示与 check_type 同名 |
| `CHECK_REGISTRY` | `dict[str, CheckSpec]` | check_type → 声明（当前 19 条） |

### Exemptions `src/engines/exemptions.py`

豁免持久化（`.docauditignore`，JSON v1）。读取只信任 `key` 字段（稳定 `exemption_key`），
其余为人工评审元数据；文件缺失/损坏返回空集合（fail-open 到"多报"）。

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `load_exemptions` | `(path: str \| Path = DEFAULT_EXEMPTION_FILE)` | `set[str]` | 读取豁免键；兼容裸列表与 `{"exemptions": [...]}` 两种形态 |
| `save_exemptions` | `(path: str \| Path, keys: Iterable[str], findings: list[AuditFinding] \| None = None)` | `None` | 写入版本化 JSON；findings 用于补齐 rule_id/page/message 元数据 |
| `apply_exemptions` | `(findings: list[AuditFinding], keys: set[str])` | `tuple[list[AuditFinding], int]` | 过滤已豁免项，返回 (保留列表, 豁免条数) |
| `DEFAULT_EXEMPTION_FILE` | `str` | `".docauditignore"` | 默认文件名 |
| `_extract_keys` | `(data)` | `set[str]` | 内部：解析两种文件形态 |

---

## Models（数据模型）

`src/models/` — 系统通用语言

### Run `src/models/document.py`

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | `str` | 文本内容 |
| `font_name` | `str \| None` | 西文字体 (DOCX w:ascii / PPTX a:latin)；未提取到为 None |
| `font_name_east_asia` | `str \| None` | 中文字体 (DOCX w:eastAsia / PPTX a:ea typeface)；中文显示字体由此决定，无则 None |
| `font_size` | `float \| None` | 字号 (pt) |
| `bold` / `italic` / `underline` | `bool \| None` | 加粗/斜体/下划线 |
| `color` | `str \| None` | 字体色 hex RGB (e.g. "FF0000") |
| `strikethrough` | `bool \| None` | 删除线 |
| `effective_font_name` | `str \| None` | 继承解析后的有效西文字体 (theme/master/layout/style) |
| `effective_font_name_east_asia` | `str \| None` | 继承解析后的有效中文字体 |
| `effective_font_size` | `float \| None` | 继承解析后的有效字号 (pt) |
| `font_size_inherited` | `bool` | 字号是否来自继承而非 run 显式设置 |

### Document `src/models/document.py`

| 字段 | 类型 | 说明 |
|------|------|------|
| `source_path` | `str` | 原始文件路径 |
| `format` | `str` | `"pptx"` \| `"docx"` \| `"pdf"` \| `"md"` |
| `metadata` | `DocumentMetadata` | title, author, created, modified, slide_count, page_count, word_count, custom_properties |
| `pages` | `list[Page]` | 页/幻灯片列表 |
| `auxiliary_elements` | `list[PageElement]` | 正文之外的文本 (DOCX 页眉/页脚/脚注)；`placeholder_type` 为 header/footer/footnote，仅参与语言/术语类检查（无版面几何） |
| `all_text` (属性) | `str` | 全文拼接 (缓存) |
| `all_paragraphs` (属性) | `list[Paragraph]` | 全文档段落 |

内部数据类（同文件）:

| 类 | 字段 | 说明 |
|------|------|------|
| `Run` | `text` / `font_name` / `font_name_east_asia` / `font_size` / `bold` / `italic` / `underline` / `color` / `strikethrough` | 最小文本单元 — 一段连续格式属性的文本 |
| `Paragraph` | `text` / `runs` / `level` / `alignment` / `space_before` / `space_after` / `line_spacing` / `bullet_type` / `bullet_char` | 段落 — 一组 Run 组成一个逻辑段落；`bullet_type`: `char`/`number`/`none`/None |

### `Page` `src/models/document.py`

| 字段/属性 | 类型 | 说明 |
|----------|------|------|
| `index` | `int` | 页索引 (0-based) |
| `elements` | `list[PageElement]` | 页内元素列表 |
| `layout_name` | `str \| None` | PPTX 版式名称 |
| `master_name` | `str \| None` | PPTX 母版名称/partname (多母版检测) |
| `slide_number` | `int \| None` | 幻灯片编号 (1-indexed) |
| `notes` | `str \| None` | 演讲者备注 |
| `flattened_elements` (属性) | `list[PageElement]` | 递归展开 Group 子元素 (缓存) |
| `all_text` (属性) | `str` | 该页所有文本 (缓存) |
| `all_paragraphs` (属性) | `list[Paragraph]` | 该页所有段落 |
| `text_frames` (属性) | `list[PageElement]` | 仅文本框类型 |
| `tables` (属性) | `list[PageElement]` | 仅表格类型 |

### `PageElement` `src/models/document.py`

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `str` | `"text_frame"` \| `"table"` \| `"image"` \| `"chart"` \| `"group"` |
| `paragraphs` | `list[Paragraph]` | 段落列表 |
| `tables` | `list[list[TableCell]]` | 表格数据 (按行) |
| `table_row_heights` | `list[float]` | 表格行高 (pt)；与行索引对齐，0.0 表示自动/未设置 |
| `table_col_widths` | `list[float]` | 表格列宽 (pt)；与列索引对齐，0.0 表示自动/未设置 |
| `children` | `list[PageElement]` | Group 子元素 |
| `left` / `top` / `width` / `height` | `float \| None` | 位置尺寸 (pt) |
| `shape_name` | `str \| None` | PPTX shape 名称 (DOCX 为 None) |
| `style_name` | `str \| None` | DOCX 段落样式名 (如 "Heading 1")；PPTX 为 None |
| `is_title` | `bool` | 是否为标题占位符 |
| `is_body` | `bool` | 是否为正文占位符 |
| `is_placeholder` | `bool` | 是否为占位符 |
| `placeholder_type` | `str \| None` | `title`/`body`/`subtitle`/`slide_number`/`footer`/`date`/`header`/`other` |
| `auto_size` | `str \| None` | 文本框自动缩放模式 |
| `word_wrap` | `bool \| None` | 是否自动换行 |
| `margin_left/top/right/bottom` | `float \| None` | 文本框内边距 (pt) |
| `vertical_anchor` | `str \| None` | 垂直锚点 |
| `image_alt_text` | `str \| None` | 图片替代文本 |
| `image_px_width/height` | `int \| None` | 图片原始像素尺寸 |
| `chart_has_title/title/has_legend` | `bool/str/bool \| None` | 图表标题/图例元数据 (不加载内嵌数据) |
| `image_ext` | `str \| None` | 图片扩展名 ("png" \| "jpg" \| "emf"；图片二进制不载入模型，见 P1-5) |
| `chart_type` | `str \| None` | 图表类型 python-pptx 枚举名 (如 "COLUMN_CLUSTERED (51)")；内嵌 Excel 数据不装载 |
| `iter_flat()` | 生成器 | 递归展开自身 + 所有子孙 |

### `TableCell` `src/models/document.py`

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | `str` | 单元格文本 |
| `row` / `col` | `int` | 行/列索引 (0-based) |
| `rowspan` / `colspan` | `int` | 合并单元格跨度 (默认 1) |
| `font_name` / `font_size` | `str \| None` / `float \| None` | 首 run 字体信息 (FMT-008 大字判定依据) |
| `fill_color` | `str \| None` | 单元格底色 hex RGB (e.g. "1E3A5F")；无填充/渐变/主题色为 None |
| `font_color` | `str \| None` | 首 run 字体色 hex RGB (e.g. "FFFFFF")；未提取到为 None |
| `margin_left/top/right/bottom` | `float \| None` | 单元格内边距 (pt)；PPTX 默认 7.2，DOCX 未提取为 None |

### AuditFinding `src/models/finding.py`

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `FindingType` | `structure` \| `format` \| `language` \| `terminology` \| `factual` \| `custom` \| `system` |
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
| `exemption_key` (属性) | `str` | 稳定豁免键: dedup_key + message + location 的 md5；跨多次审查可复用 |
| `to_dict()` | `dict` | 序列化（含 `exemption_key`，便于从 JSON 报告构造 `.docauditignore`） |
| `from_dict(data)` (classmethod) | `AuditFinding` | 反序列化 |
| `deduplicate(findings)` (static) | `list[AuditFinding]` | 去重 (保留最高严重度) |

---

## Reporters（报告生成）

`src/reporters/` — AuditFinding → HTML / JSON / CSV / SARIF

### HtmlReporter `src/reporters/html_reporter.py`

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `generate_html_report` | `(doc: Document, findings: list[AuditFinding], title: str, output_path: str \| Path \| None, file_label: str \| None = None, page_count: int \| None = None, show_thumbnails: bool = True)` | `str` | 生成独立 HTML 报告，所有用户文本已 `html.escape()`；`file_label` 用于批量模式覆盖头部"文件:"行；`page_count` 覆盖总页数（批量模式传聚合页数，None 保持现状）；`show_thumbnails` 控制内联 SVG 线框缩略图（批量聚合报告传 False，单页 200/总计 3000 元素上限）；批量 finding 带 `metadata["source_file"]` 时按文件分组；含严重度统计与按类型分布 |

### JsonReporter `src/reporters/json_reporter.py`

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `generate_json_report` | `(doc: Document, findings: list[AuditFinding], output_path: str \| Path \| None)` | `dict` | 生成 JSON 报告，可选写入文件 |

### CsvReporter `src/reporters/csv_reporter.py`

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `generate_csv_report` | `(findings: list[AuditFinding], output_path: str \| Path \| None = None)` | `str` | 生成 CSV 报告（UTF-8 BOM，Excel 友好）；以 `= + - @` 开头的单元格加单引号防公式注入；列：rule_id/severity/type/page/location/message/context/suggestion/source_file/exemption_key（末列可直接用于 `.docauditignore`） |

### SarifReporter `src/reporters/sarif_reporter.py`

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `generate_sarif_report` | `(doc: Document, findings: list[AuditFinding], output_path: str \| Path \| None = None, uri_base: str \| Path \| None = None)` | `str` | 生成 SARIF v2.1.0 文本（可对接 GitHub Code Scanning / VS Code SARIF Viewer）；severity → level: error/warning/note；`partialFingerprints` 用稳定 `exemption_key`；artifact 优先 `metadata["source_file"]`；`uri_base` 提供时输出仓库相对 URI（Code Scanning 关联文件所需），不在基准目录下回退 `file://` URI |

> 排序 SSOT：`src/reporters/ordering.py` 的 `_sort_findings`（error → warning → info → 页码 → rule_id → message）被 HTML/CSV/SARIF 共用；`_group_by_source` 供 HTML 按文件分组。

---

### ConfigValidation `src/engines/validation.py`

配置静态校验（`docaudit rules validate`）。运行时加载器告警降级，本模块让配置错误显式失败。

| 函数 | 签名 | 返回 | 说明 |
|------|------|------|------|
| `validate_rules` | `(rules_path: str \| Path = "rules.md")` | `ValidationResult` | ID/严重度/check_type/正则/数值范围/重复项校验 |
| `validate_glossary` | `(glossary_dir: str \| Path = "glossary")` | `ValidationResult` | YAML 结构、term 必填字段、正则、未知字段 |
| `validate_vocab` | `(vocab_dir: str \| Path = "vocab")` | `ValidationResult` | accept/reject 编码、重复项、reject 正则 |
| `validate_configuration` | `(rules_path="rules.md", glossary_dir="glossary", vocab_dir="vocab")` | `ValidationResult` | 聚合三部分（None 跳过） |

`ValidationResult` 字段：`errors: list[str]`、`warnings: list[str]`；属性 `ok`（errors 为空）；
方法 `merge(other)` / `to_lines()`。

---

## CLI（命令行入口）

`src/cli.py` — 命令行审查入口

| 函数 | 签名 | 说明 |
|------|------|------|
| `audit_file` | `(file_path, rules_path="rules.md", glossary_dir="glossary", vocab_dir=None, verbose=False)` → `(Document, list[AuditFinding])` | 执行单文件审查并返回结果 |
| `print_summary` | `(findings)` | 打印审查结果摘要 |
| `doctor_check` | `()` → `int` | 环境诊断：检查运行环境健康状态，失败项 > 0 时返回 1 |

子命令：`audit`（默认）、`doctor`、`rules validate`（配置校验，错误时 exit 1）、
`rules list`（打印解析到的规则表：ID/严重度/检查/说明）。

审计参数（`audit`）：`--fail-on {error,warning,info,none}` 控制退出码阈值（默认 `error`，
与历史行为一致）；`--exempt-file PATH` 应用 `.docauditignore` 豁免基线；
`-o` 支持 `.html` / `.json` / `.csv` / `.sarif`（批量时 SARIF 聚合为单文件）；
`--sarif-base PATH` 让 SARIF artifact 输出相对路径（Code Scanning 关联文件所需）。

---

<!-- last_updated: 2026-10-29 -->
