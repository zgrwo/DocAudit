"""FMT-008 表格文字与底色对比度：WCAG 对比度算法 + FormatAuditor 检查。

规则语义: 深色底色配浅色文字、浅色底色配深色文字。
判定: 单元格底色与字体色的 WCAG 对比度 >= 阈值
  - 正文(字号 < 18pt): 4.5:1
  - 大字(字号 >= 18pt): 3.0:1
缺色(无填充/主题色/未提取到)或空单元格 → 跳过，不误报。
"""

import pytest

from src.auditors.format import (
    FormatAuditor,
    _contrast_ratio,
    _hex_to_rgb,
    _relative_luminance,
)
from src.models.document import Document, DocumentMetadata, Page, PageElement, TableCell

# ── 算法纯函数 ──────────────────────────────────────────────────────────

def test_hex_to_rgb():
    assert _hex_to_rgb("1E3A5F") == (0x1E, 0x3A, 0x5F)
    assert _hex_to_rgb("#FFFFFF") == (255, 255, 255)
    assert _hex_to_rgb("000000") == (0, 0, 0)


def test_hex_to_rgb_invalid():
    with pytest.raises(ValueError):
        _hex_to_rgb("12345")
    with pytest.raises(ValueError):
        _hex_to_rgb("GGGGGG")


def test_relative_luminance_black_white():
    assert _relative_luminance((0, 0, 0)) == pytest.approx(0.0)
    assert _relative_luminance((255, 255, 255)) == pytest.approx(1.0)


def test_relative_luminance_known_color():
    # WCAG 参考值: 纯蓝 #0000FF 的相对亮度 = 0.0722
    assert _relative_luminance((0, 0, 255)) == pytest.approx(0.0722, abs=1e-4)


def test_contrast_ratio_black_white():
    assert _contrast_ratio("000000", "FFFFFF") == pytest.approx(21.0)
    assert _contrast_ratio("FFFFFF", "000000") == pytest.approx(21.0)  # 顺序无关
    assert _contrast_ratio("000000", "000000") == pytest.approx(1.0)


def test_contrast_ratio_gray_white_between_3_and_4_5():
    # #808080 vs #FFFFFF ≈ 3.95 — 介于大字阈值(3.0)与正文阈值(4.5)之间
    r = _contrast_ratio("808080", "FFFFFF")
    assert 3.0 < r < 4.5


# ── 检查器 ──────────────────────────────────────────────────────────────

def _make_doc(cells: list[TableCell], fmt: str = "pptx") -> tuple[Document, Page]:
    elem = PageElement(type="table", tables=[cells])
    page = Page(index=0, slide_number=1, elements=[elem])
    return Document(format=fmt, source_path="x", metadata=DocumentMetadata(), pages=[page]), page


def _check(cells: list[TableCell], fmt: str = "pptx"):
    doc, page = _make_doc(cells, fmt)
    return FormatAuditor()._check_table_contrast(page, doc)


def test_deep_fill_deep_font_flagged():
    cell = TableCell(text="深底深字", row=0, col=0, fill_color="1E3A5F", font_color="1E3A5F")
    findings = _check([cell])
    assert len(findings) == 1
    assert findings[0].rule_id == "FMT-008"
    assert "对比度" in findings[0].message
    assert findings[0].metadata["ratio"] == pytest.approx(1.0)


def test_deep_fill_light_font_ok():
    cell = TableCell(text="深底浅字", row=0, col=0, fill_color="1E3A5F", font_color="FFFFFF")
    assert _check([cell]) == []


def test_light_fill_deep_font_ok():
    cell = TableCell(text="浅底深字", row=0, col=0, fill_color="FFFFFF", font_color="000000")
    assert _check([cell]) == []


def test_light_fill_light_font_flagged():
    cell = TableCell(text="浅底浅字", row=0, col=0, fill_color="FFFFFF", font_color="F5F5F5")
    findings = _check([cell])
    assert len(findings) == 1


def test_missing_colors_skipped():
    """无填充/未提取到颜色 → 跳过不误报"""
    cell = TableCell(text="无色", row=0, col=0)
    assert _check([cell]) == []


def test_only_fill_skipped():
    cell = TableCell(text="只有底色", row=0, col=0, fill_color="1E3A5F")
    assert _check([cell]) == []


def test_only_font_color_skipped():
    cell = TableCell(text="只有字色", row=0, col=0, font_color="000000")
    assert _check([cell]) == []


def test_empty_cell_skipped():
    cell = TableCell(text="", row=0, col=0, fill_color="1E3A5F", font_color="1E3A5F")
    assert _check([cell]) == []


def test_large_text_uses_lower_threshold():
    """#808080 底 + 白字: 对比度≈3.95 — 大字(18pt+) 通过 3.0 阈值, 正文不通过 4.5"""
    large = TableCell(text="大字", row=0, col=0, fill_color="808080",
                      font_color="FFFFFF", font_size=18)
    assert _check([large]) == []
    body = TableCell(text="正文", row=0, col=0, fill_color="808080",
                     font_color="FFFFFF", font_size=12)
    assert len(_check([body])) == 1


def test_custom_threshold_config():
    """配置驱动: 阈值可从 auditor config 覆盖"""
    cell = TableCell(text="正文", row=0, col=0, fill_color="808080",
                     font_color="FFFFFF", font_size=12)
    doc, page = _make_doc([cell])
    auditor = FormatAuditor(config={"min_contrast": 3.0})
    assert auditor._check_table_contrast(page, doc) == []


def test_docx_format_supported():
    cell = TableCell(text="深底深字", row=0, col=0, fill_color="1E3A5F", font_color="1E3A5F")
    assert len(_check([cell], fmt="docx")) == 1


def test_same_text_different_cells_not_deduped():
    """回归: dedup 不得折叠同页同文本的不同单元格违规 (context 必须含行列坐标)。

    曾出现: dedup_key = type|rule_id|page|context哈希, 同文本单元格被合并为一条,
    location 只指向第一个单元格, 其余同类违规从报告消失。
    """
    c1 = TableCell(text="待确认", row=0, col=0, fill_color="1E3A5F", font_color="1E3A5F")
    c2 = TableCell(text="待确认", row=1, col=0, fill_color="1E3A5F", font_color="1E3A5F")
    doc, page = _make_doc([c1, c2])

    auditor = FormatAuditor()
    findings = auditor.audit(doc)
    fmt8 = [f for f in findings if f.rule_id == "FMT-008"]
    assert len(fmt8) == 2, f"期望 2 条 FMT-008 (不同单元格), 实际 {len(fmt8)}"
    # 每条 context 必须带各自行列, 使 dedup_key 互异
    keys = {f.dedup_key for f in fmt8}
    assert len(keys) == 2
    locations = sorted(f.location for f in fmt8)
    assert "第1行" in locations[0] and "第2行" in locations[1]
