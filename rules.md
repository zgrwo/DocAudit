---
version: "1.0"
description: "半导体行业报告审查规则"
language: "zh-CN"
# 全局阈值：此前硬编码在 Auditor 里，现于此声明（未声明时使用代码默认值 = 历史值）。
# 非法值/未知键由 `docaudit rules validate` 显式报错；运行时降级为默认值并告警。
parameters:
  alignment_tolerance: 5.0            # FMT-ALIGN 对齐容差 (pt)
  max_font_types: 3                   # FMT-001 全局字体种类上限
  near_duplicate_similarity: 0.90     # TXT-NEAR-DUP 近似页相似度阈值 (0.5-1.0)
  near_duplicate_min_chars: 40        # TXT-NEAR-DUP 最小字符数
  conclusion_min_paragraphs: 3        # CON-004 判断 2 的内容段落门槛
  table_fit_height_ratio: 1.15        # FMT-TABLE-FIT 行高不足倍率
  table_fit_min_excess_pt: 6.0        # FMT-TABLE-FIT 行高不足最小超出 (pt)
  table_fit_col_ratio: 1.05           # FMT-TABLE-FIT 列宽不足倍率
  table_fit_col_min_excess_pt: 2.0    # FMT-TABLE-FIT 列宽不足最小超出 (pt)
  table_margin_pt_pptx: 7.2           # PPTX 单元格默认内边距 (pt)
  table_margin_pt_docx: 5.4           # DOCX 单元格默认内边距 (pt)
  text_overflow_height_ratio: 1.15    # FMT-TEXT-OVERFLOW 溢出倍率
  text_overflow_min_excess_pt: 8.0    # FMT-TEXT-OVERFLOW 最小超出 (pt)
  image_min_dpi: 150                  # FMT-IMAGE 最低 DPI
  numeric_length_units: [nm, μm, um, mm, cm, m]  # CON-001 视为工艺节点的长度单位
  common_uppercase_extra: []          # 缩写扫描额外豁免词（大写，如公司内部代号）
---

# 结构规则

## STR-001: 必须有标题页
- 严重度: error
- 说明: 第一页必须使用标题版式
- 检查: first_slide_has_title_layout
- 最小标题字号: 28

## STR-002: 图表编号连续性
- 严重度: error
- 说明: 所有图/表的编号必须连续 (Fig.1 → Fig.2 → Fig.3 ...)，不允许跳号
- 检查: figure_numbering_sequential

## STR-003: 标题层级不跳级
- 严重度: warning
- 说明: 标题层级应逐步递进，不跳级 (H1 → H2 → H3，不应 H1 → H3)
- 检查: heading_level_sequential

## STR-004: 标题长度限制
- 严重度: warning
- 说明: 幻灯片标题不应过长，以 10 个英文词或 40 个中文字为上限
- 检查: title_length
- 最大英文词数: 10
- 最大中文字数: 40

## STR-005: 禁止重复标题
- 严重度: error
- 说明: 不同幻灯片不应使用完全相同的标题
- 检查: duplicate_title

## STR-006: 标题末尾禁止标点
- 严重度: info
- 说明: 幻灯片标题末尾不应使用句号、逗号等标点符号
- 检查: title_trailing_punctuation

## STR-007: 图表标题格式一致性
- 严重度: warning
- 说明: 图表标题的编号格式应全文统一（如统一使用"图N："或"Fig. N: "）
- 检查: figure_caption_format

## STR-008: 幻灯片版式多样性
- 严重度: info
- 说明: 所有幻灯片不应使用完全相同的版式，建议根据内容类型使用不同版式
- 检查: slide_structure_consistency

## STR-009: 图表须被正文引用
- 严重度: info
- 说明: 图/表标题存在但正文从未出现「见图N / 如图N所示 / 表N中」等引用，读者无从定位；图表是"摆设"或引用缺失
- 检查: figure_referenced

# 格式规则

## FMT-001: 正文字体统一（仅 PPTX）
- 严重度: warning
- 说明: 幻灯片正文文本必须使用指定字体之一（DOCX/PDF/MD 不套用 PPT 品牌字体表）
- 字体: [微软雅黑, Arial, Noto Sans SC, Calibri]

## FMT-002: 标题字号范围（仅 PPTX）
- 严重度: warning
- 说明: 幻灯片标题字号 28-44pt, 正文 12-32pt（DOCX/PDF/MD 不套用幻灯片字号）
- 标题: {min: 28, max: 44}
- 正文: {min: 12, max: 32}

## FMT-003: 每页文本量限制（仅 PPTX）
- 严重度: warning
- 说明: 单张幻灯片文本不应过于密集（DOCX/PDF/MD 的页/章节不适用）
- 检查: per_page_char_limit
- 最大字数: 200

## FMT-004: 单段不超过3行
- 严重度: warning
- 说明: 单个段落不应过长，以3行为上限（中文约150字，英文约300字符）
- 中文上限: 150
- 英文上限: 300
- 最大显式换行: 3

## FMT-005: 元素不超出页面边界（仅 PPTX）
- 严重度: error
- 说明: 文本框/图片/表格等元素不得超出幻灯片边界
- 检查: element_overflow

## FMT-006: 空占位符检测
- 严重度: warning
- 说明: 幻灯片中不应有未填充内容的空白占位符文本框
- 检查: empty_placeholder

## FMT-007: 项目符号样式一致性
- 严重度: info
- 说明: 同一页内不应混用多种项目符号样式（如实心圆点+数字编号+字母编号）
- 检查: bullet_consistency

## FMT-008: 表格文字与底色对比度
- 严重度: warning
- 说明: 表格单元格的底色与文字颜色对比度不足会影响可读性；深色底色应配浅色文字，浅色底色应配深色文字
- 检查: table_contrast
- 最小对比度: 4.5
- 大字最小对比度: 3.0
- 大字字号阈值: 18

# 术语规则

## TERM-001: 先进封装术语
- 检查: regex
- 模式: "fan-out(?!\s*(wafer|panel|WLP|FOWLP|FO-WLP))"
- 建议: "建议使用完整术语: Fan-Out Wafer-Level Packaging (FOWLP) 或扇出型晶圆级封装"
- 严重度: error

## TERM-002: 硅通孔术语
- 检查: regex
- 模式: "through.silicon.via(?!.*TSV)"
- 建议: "首次出现应标注缩写: TSV (Through Silicon Via)"
- 严重度: warning

## TERM-003: 技术缩写首次出现应附中文翻译
- 检查: regex
- 模式: "(?<![A-Za-z0-9])[A-Z]{2,8}(?![A-Za-z0-9])"
- 说明: "技术缩写（全大写，如 TSV/FOWLP）首次出现应附带中文翻译，格式: 英文 (中文)"
- 仅中文页面: true
- 大小写敏感: true
- 排除括号内: true
- 排除白名单: true
- 仅首次出现: true
- 严重度: info

# 内容规则

## CON-001: 数值一致性
- 严重度: error
- 说明: 同一指标在前文出现过的数值应保持一致
- 检查: numeric_cross_reference

## CON-002: 必须包含的章节
- 严重度: error
- 说明: 技术报告/演示必须包含以下章节
- 章节: [概述, 工艺流程, 关键参数, 结论]

## CON-003: 缩写首次定义
- 严重度: error
- 说明: 技术缩写首次出现时必须给出全称
- 检查: abbreviation_first_defined

## CON-003-A: 缩写定义后未再使用
- 严重度: info
- 说明: 缩写首次定义后在文档中未再次出现，定义可能是多余的
- 检查: abbreviation_defined_never_used

## CON-003-B: 缩写重复定义
- 严重度: warning
- 说明: 同一技术缩写在文档中被多次定义，只需保留首次定义
- 检查: abbreviation_multiply_defined

## CON-003-C: 缩写在定义前使用
- 严重度: warning
- 说明: 缩写出现在其全称定义之前，读者可能不理解
- 检查: abbreviation_used_before_defined

## CON-004: 每页须有结论
- 严重度: error
- 说明: 每一页幻灯片必须有明确的结论或关键要点，不能只有标题而无内容总结
- 检查: every_slide_has_conclusion
- 关键词: [结论, 小结, 总结, 要点, 关键, 建议, 展望, Summary, Conclusion, Key, Takeaway, Recommend]
- 豁免版式: [标题幻灯片, Title Slide, Title, Titelfolie, 封面, タイトル, Cover]

## CON-005: 结论须有量化支撑
- 严重度: info
- 说明: 含「结论/建议/展望」等关键词的句子没有任何数字/百分比/单位（如"性能显著提升"），属于空泛表述；本检查只判断"有没有给数据"，不判断数据是否正确；默认 info（启发式，团队可按口径升为 warning）
- 检查: conclusion_has_evidence
- 关键词: [结论, 小结, 总结, 建议, 展望, Summary, Conclusion, Recommendation]
- 最小数字个数: 1

## CON-006: 必含章节须有实体内容
- 严重度: warning
- 说明: CON-002 声明的必含章节只有标题（PPTX 为仅标题页 / DOCX 为标题后无正文），属于"只有壳的章节"；缺失章节由 CON-002 报，本规则只查已有章节的内容
- 检查: section_has_substance
- 最小内容段落: 1
- 最小字数: 20

## CON-007: 数值须带单位
- 严重度: info
- 说明: 「厚度 5」「电压 3.3」这类量词语境下的数值缺少单位；只检查配置量词（厚度/宽度/电压…）后 8 字符内的数值，避免把计数/序号误报
- 检查: numeric_unit_presence
- 量词关键词: [厚度, 宽度, 深度, 直径, 间距, 线宽, 高度, 长度, 温度, 电压, 电流, 功率, 速度, 尺寸, 距离, 容量, 重量, 压力, 频率, 密度, 角度]

# 内置检查（非配置驱动）

以下检查由审计器/引擎内置实现，不经 rules.md 声明与 _DISPATCH 调度，不参与上方
30 条规则计数（无对应 `##` 条目）：

| rule_id | 说明 | 实现位置 |
|---------|------|----------|
| FMT-MIXED-001 | 英文与中文之间建议加空格 | `src/auditors/language.py` → `_check_mixed_formatting` |
| FMT-MIXED-002 | 中文与英文之间建议加空格 | `src/auditors/language.py` → `_check_mixed_formatting` |
| FMT-MIXED-003 | 英文后不应使用中文标点 | `src/auditors/language.py` → `_check_mixed_formatting` |
| FMT-ALIGN | 同页文本框行/列对齐提示 (标题与正文不互比) | `src/auditors/format.py` → `_check_alignment` |
| FMT-OVERLAP | 元素重叠提示 (保守阈值 25%，排除嵌套/全屏背景) | `src/auditors/format.py` → `_check_element_overlap` |
| FMT-SAFE-MARGIN | 元素贴边提示 (默认页面 1% 安全边距) | `src/auditors/format.py` → `_check_safe_margin` |
| FMT-TEXT-OVERFLOW | 文本框内容溢出估算 (CJK=2 半角单位，行高≈1.2em) | `src/auditors/format.py` → `_check_text_overflow` |
| FMT-TABLE-FIT | 表格行高/列宽/页面越界估算 (行高不足/长词断行/表格顶出页面) | `src/auditors/format.py` → `_check_table_fit` |
| FMT-FOOTER | 页脚/页码/日期占位符部分页面缺失 | `src/auditors/format.py` → `_check_footer_consistency` |
| FMT-IMAGE | 图片宽高比失真/低 DPI/缺 alt text | `src/auditors/format.py` → `_check_image_quality` |
| FMT-CHART | 图表缺少标题 | `src/auditors/format.py` → `_check_chart_labeling` |
| STR-MASTER | 检测到多个幻灯片母版 | `src/auditors/structure.py` → `_check_master_consistency` |
| PUNCT-001 | 重复标点 (`；；`/`：：`/`！！`/`？？`) | `src/auditors/language.py` → `_check_punctuation` |
| PUNCT-002 | 相邻冲突标点 (`，。`/`。，`/`、，` 等) | `src/auditors/language.py` → `_check_punctuation` |
| PUNCT-003 | 中文后使用英文标点 | `src/auditors/language.py` → `_check_punctuation` |
| PUNCT-004 | 全角字母/数字 | `src/auditors/language.py` → `_check_punctuation` |
| PUNCT-005 | 括号/引号不配对 | `src/auditors/language.py` → `_check_punctuation` |
| PUNCT-006 | 中文语境使用英文省略号 | `src/auditors/language.py` → `_check_punctuation` |
| PUNCT-007 | 中文语境使用英文双连字符破折号 | `src/auditors/language.py` → `_check_punctuation` |
| PUNCT-008 | 日期格式混用 (中文/ISO/斜杠) | `src/auditors/language.py` → `_check_date_format_consistency` |
| PUNCT-009 | 数值范围连接符混用 (`-`/`—`/`~`/`至`) | `src/auditors/language.py` → `_check_range_separator_consistency` |
| PUNCT-010 | 数值与单位空格用法不一致 (`10kg` / `10 kg`) | `src/auditors/language.py` → `_check_unit_spacing_consistency` |
| TXT-BULLET-PUNCT | 项目符号末尾标点不一致 (同页部分有句号) | `src/auditors/language.py` → `_check_bullet_trailing_punctuation` |
| TXT-DUP-SENTENCE | 跨页重复句子 (归一化后完全相同) | `src/auditors/language.py` → `_check_duplicate_sentences` |
| TXT-NEAR-DUP | 近似重复页 (字符二元组 Jaccard ≥ 0.90，≥40 字) | `src/auditors/language.py` → `_check_near_duplicate_pages` |
| TXT-REDUNDANT | 高精度中文冗余表达 | `src/auditors/language.py` → `_check_redundancy` |
| VOCAB-REJECT | 禁用词汇检查 (reject.txt) | `src/auditors/language.py` → `_check_rejected_vocab`；引擎 `src/engines/vocabulary.py` |
| PY-SPELL | 纯 Python 拼写检查 (tier-3 降级) | `src/engines/languagetool.py` → `_check_python` |
| PY-ZH-GRAMMAR | 中文基础语法/标点模式 (始终执行，不依赖 LanguageTool 后端) | `src/auditors/language.py` → `_check_builtin_chinese_patterns`；`src/engines/languagetool.py` → `check_chinese_patterns` |
| SYS-ERROR | 规则/审计器执行失败的系统错误 (UI 可见) | `src/auditors/custom_rules.py` → `audit`/`_execute_check_rule`；`src/engines/pipeline.py` → `run_auditors` |
| BATCH-TERM | 同一缩写在多份报告中全称不一致（仅批量模式） | `src/engines/batch.py` → `cross_document_findings` |
| BATCH-SECTION | 必含章节仅部分报告包含（仅批量模式） | `src/engines/batch.py` → `cross_document_findings` |

以下为代码内置的不可配阈值（2026-09-06 审查 C-2 补录；2026-11 第二轮审查后大部分已
迁入 frontmatter `parameters:`，下表仅剩结构性常量）。**同类阈值应优先声明为全局参数**，
不要在新检查里硬编码。

| 阈值 | 值 | 说明 | 实现位置 |
|------|-----|------|----------|
| 画布基准/容差 | 960×540 pt / 5.0 pt | FMT-005 版式一致性基准画布 | `src/auditors/format.py` → `_check_layout_consistency` |
| 语言分段门槛 | 英文 ≥2 词 / 中文 ≥5 字 | 过短语言段并入相邻段 | `src/auditors/language.py` → `_segment_languages` |
| 上下文窗口 | ±30 字符 | CON-001 数值上下文切片 | `src/auditors/factual.py` → `_extract_numeric_values` |
| 表格估算默认字号 | PPTX 18pt / DOCX 10.5pt | 单元格未写显式字号时按应用默认值估算 (FMT-TABLE-FIT) | `src/auditors/format.py` → `DEFAULT_TABLE_FONT_SIZE_*` |

> 已迁入全局参数（`parameters:`）的原硬编码阈值：对齐容差、全局字体种类上限、
> CON-004 判断 2 门槛、表格行高/列宽倍率与最小超出、表格单元格内边距、
> 文本溢出倍率与最小超出、图片最低 DPI、近似重复页阈值、CON-001 长度单位表、
> 缩写扫描额外豁免词。

