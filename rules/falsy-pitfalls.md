# Falsy 陷阱检查清单

> **SSOT 声明**：本文件是 falsy 值误判检查的**唯一权威信源**。
> [python-SKILL.md](../skills/python-SKILL.md) 中的 falsy 内容只链接引用本文件，不重复维护。
>
> 提炼自跨项目审计（含 VibeCodingTemplate 模板经验）。**Python 中 0 是有效值**：页码=0、计数=0、字号=0、数值=0，不能用 `if x:` 检查。

## 核心规则

Python 中 `if x:` 对以下值判假：`0`, `0.0`, `""`, `[]`, `{}`, `None`, `False`

| 变量类型 | 检查方式 | 原因 |
|----------|----------|------|
| 数值变量（页码/字号/数值/计数/百分比） | `if x is not None:` | 0 是有效值 |
| 可选参数（阈值/长度限制/严重度权重） | `if x is not None:` | 0 是合法配置 |
| 布尔变量（开关标志） | `if x:` | 布尔值语义安全 |
| 集合/列表（数据容器） | `if x:` | 空容器 = 无数据，语义正确 |
| 字符串（文本内容） | `if x:`（但需先 `x.strip()` 判断空白） | 空串 = 无内容；纯空白串需 strip |

## 正反示例

```python
# ❌ 错误：第 0 页（index=0）被跳过
if page.index:
    label = f"第 {page.index} 页"

# ✅ 正确
if page.index is not None:
    label = f"第 {page.index} 页"

# ❌ 错误：字号 0 / 数值 0 是合法输入，却被当作"未设置"
if font_size:
    sizes.append(font_size)

# ✅ 正确
if font_size is not None:
    sizes.append(font_size)
```

## 高风险变量名（遇到必须用 `is not None`）

| 变量名模式 | 原因 |
|-----------|------|
| `index`, `page_index`, `slide_number` | 页码/索引，0 是第一页 |
| `count`, `*_count`, `word_count` | 计数，0 是有效结果 |
| `font_size`, `size`, `*_size` | 字号/尺寸，0 是合法值（或用 None 表示未设置） |
| `width`, `height`, `left`, `top` | 坐标/尺寸（EMU/pt），0 是有效值 |
| `level`, `outline_level` | 大纲级别，0 是顶级 |
| `score`, `ratio`, `*_rate`, `percentage` | 数值/比例，0 表示无 |
| `value`, `*_value` | 数值一致性检查，0 是有效观测值 |
| `length`, `*_len` | 长度/截断参数，0 是合法限制 |

## 常见误判场景（历史案例）

1. `if page.index:` — 第 0 页（封面）被跳过，首条 finding 丢失
2. `if count:` — 计数=0 时跳过统计汇总
3. `if font_size:` — 字号 0 被当作"未设置"而漏检
4. `if ratio:` — 良率/占比=0 时误判"无数据"而非"数值为 0"
5. `if text:` — 纯空白串（"  "）为真；文本存在性应先 `text.strip()`
6. `if not re.search(...)` — 匹配 0 次与模式缺失混淆；先判 `pattern is not None`

## 审计方式

无独立审计脚本；新增/修改代码时对照本表自查，重点审查：
- `src/auditors/`（页码、字号、数值一致性）
- `src/engines/rule_parser.py`（配置阈值取值）
- `src/converters/`（坐标/尺寸提取）

## 相关 Skill

- 完整 Python 陷阱 → `skills/python-SKILL.md`
- 工具/脚本坑位 → `rules/tooling-pitfalls.md`
