---
version: "1.0"
description: "半导体行业报告审查规则"
language: "zh-CN"
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

# 格式规则

## FMT-001: 正文字体统一
- 严重度: warning
- 说明: 正文文本必须使用指定字体之一
- 字体: [微软雅黑, Arial, Noto Sans SC, Calibri]

## FMT-002: 标题字号范围
- 严重度: warning
- 说明: 标题字号 28-40pt, 正文 12-22pt
- 标题: {min: 28, max: 40}
- 正文: {min: 12, max: 22}

## FMT-003: 每页文本量限制
- 严重度: warning
- 说明: 单页文本不应过于密集
- 检查: per_page_char_limit
- 最大字数: 200

## FMT-004: 单段不超过3行
- 严重度: warning
- 说明: 单个段落不应过长，以3行为上限（中文约150字，英文约300字符）
- 中文上限: 150
- 英文上限: 300
- 最大显式换行: 3

## FMT-005: 元素不超出页面边界
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

## TERM-003: 中英文混用规范
- 检查: regex
- 模式: "(?<![A-Za-z0-9])(?:[A-Z]{2,8}(?![A-Za-z0-9])|[A-Z][a-z]{2,}(?![A-Za-z0-9]))(?!\s*[（(][^）)]*[）)])"
- 说明: "英文术语（全大写缩写或首字母大写词）首次出现应附带中文翻译，格式: 英文 (中文)"
- 仅中文页面: true
- 大小写敏感: true
- 排除括号内: true
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

# 内置检查（非配置驱动）

以下检查由审计器/引擎内置实现，不经 rules.md 声明与 _DISPATCH 调度，不参与上方
26 条规则计数（无对应 `##` 条目）：

| rule_id | 说明 | 实现位置 |
|---------|------|----------|
| FMT-MIXED-001 | 英文与中文之间建议加空格 | `src/auditors/language.py` → `_check_mixed_formatting` |
| FMT-MIXED-002 | 中文与英文之间建议加空格 | `src/auditors/language.py` → `_check_mixed_formatting` |
| FMT-MIXED-003 | 英文后不应使用中文标点 | `src/auditors/language.py` → `_check_mixed_formatting` |
| VOCAB-REJECT | 禁用词汇检查 (reject.txt) | `src/auditors/language.py` → `_check_rejected_vocab`；引擎 `src/engines/vocabulary.py` |
| PY-SPELL | 纯 Python 拼写检查 (tier-3 降级) | `src/engines/languagetool.py` → `_check_python` |
| PY-ZH-GRAMMAR | 中文基础语法正则检查 | `src/engines/languagetool.py` → `_check_chinese_patterns` |
| SYS-ERROR | 规则/审计器执行失败的系统错误 (UI 可见) | `src/auditors/custom_rules.py` → `audit`/`_execute_check_rule`；`src/engines/pipeline.py` → `run_auditors` |

