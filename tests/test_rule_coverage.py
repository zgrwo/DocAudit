"""规则覆盖测试 — 补齐零定向断言的规则 (P1-7)。

背景: 审查发现以下规则没有任何定向测试 (tests/ 中 grep 不到 rule_id):
STR-005 / STR-006 / STR-008 / CON-001 / CON-002 / CON-003-A / CON-003-B /
CON-003-C / FMT-003 / FMT-004 / FMT-005 / FMT-006 / FMT-007。

每条规则: 触发场景 (finding 存在且 rule_id/severity 正确) + 不触发场景。
构造方式: 优先直接构造 Document 模型 (最可控)；CON-003 系列直接调用
FactualAuditor 方法 (不经 pipeline dispatch)；FMT-003~007 直接调用 FormatAuditor
的 dispatch 方法 (与 _DISPATCH 委托的同一方法)，另加一条 FMT-005 完整流水线
dispatch 集成测试证明 wiring 未断。
"""

from pathlib import Path

from src.auditors.factual import FactualAuditor
from src.auditors.format import FormatAuditor
from src.auditors.structure import StructureAuditor
from src.models.document import Document, DocumentMetadata, Page, PageElement, Paragraph
from src.models.finding import FindingSeverity

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _doc(pages: list[Page], fmt: str = "md", custom_properties: dict | None = None) -> Document:
    """构造统一文档模型。"""
    return Document(
        source_path="test.pptx" if fmt == "pptx" else "test.md",
        format=fmt,
        metadata=DocumentMetadata(custom_properties=custom_properties or {}),
        pages=pages,
    )


def _page(elements: list[PageElement], index: int = 0, layout: str | None = None) -> Page:
    return Page(index=index, slide_number=index + 1, elements=elements, layout_name=layout)


def _text_frame(paragraphs: list[Paragraph], **kw) -> PageElement:
    return PageElement(type="text_frame", paragraphs=paragraphs, **kw)


def _para(text: str) -> Paragraph:
    return Paragraph(text=text, runs=[])


class TestStr005DuplicateTitle:
    """STR-005: 禁止重复标题。"""

    def test_duplicate_title_flagged(self):
        """两页同标题 (is_title 元素) → STR-005 ERROR。"""
        sa = StructureAuditor(config={"required_sections": []})
        d = _doc(
            [
                _page([_text_frame([_para("重复标题")], is_title=True)]),
                _page([_text_frame([_para("重复标题")], is_title=True)], index=1),
            ]
        )
        findings = sa._check_duplicate_title(d)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "STR-005"
        assert f.severity == FindingSeverity.ERROR
        assert f.page_index == 0

    def test_unique_titles_not_flagged(self):
        """两页不同标题 → 不触发 STR-005。"""
        sa = StructureAuditor(config={"required_sections": []})
        d = _doc(
            [
                _page([_text_frame([_para("标题一")], is_title=True)]),
                _page([_text_frame([_para("标题二")], is_title=True)], index=1),
            ]
        )
        assert sa._check_duplicate_title(d) == []


class TestStr006TitleTrailingPunctuation:
    """STR-006: 标题末尾禁止标点。"""

    def test_trailing_punctuation_flagged(self):
        """标题「标题。」 → STR-006 INFO。"""
        sa = StructureAuditor(config={"required_sections": []})
        d = _doc([_page([_text_frame([_para("标题。")], is_title=True)])])
        findings = sa._check_title_trailing_punctuation(d.pages[0], d)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "STR-006"
        assert f.severity == FindingSeverity.INFO

    def test_clean_title_not_flagged(self):
        """标题无尾随标点 → 不触发 STR-006。"""
        sa = StructureAuditor(config={"required_sections": []})
        d = _doc([_page([_text_frame([_para("标题")], is_title=True)])])
        assert sa._check_title_trailing_punctuation(d.pages[0], d) == []


class TestStr008LayoutDiversity:
    """STR-008: 幻灯片版式多样性 (PPTX)。"""

    def test_single_layout_flagged(self):
        """全部同版式 → STR-008 INFO 触发。"""
        sa = StructureAuditor(config={"required_sections": []})
        d = _doc(
            [
                _page([_text_frame([_para("a")])], layout="内容页"),
                _page([_text_frame([_para("b")])], index=1, layout="内容页"),
            ],
            fmt="pptx",
        )
        findings = sa._check_slide_structure_consistency(d)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "STR-008"
        assert f.severity == FindingSeverity.INFO

    def test_multiple_layouts_not_flagged(self):
        """多版式 → 不触发 STR-008。"""
        sa = StructureAuditor(config={"required_sections": []})
        d = _doc(
            [
                _page([_text_frame([_para("a")])], layout="内容页"),
                _page([_text_frame([_para("b")])], index=1, layout="标题页"),
            ],
            fmt="pptx",
        )
        assert sa._check_slide_structure_consistency(d) == []


class TestCon001NumericConsistency:
    """CON-001: 数值一致性 — 同上下文不同数值 → ERROR。"""

    def test_inconsistent_values_flagged(self):
        """同一指标 (成品良率) 两页数值不同 → CON-001 ERROR。"""
        fca = FactualAuditor()
        d = _doc(
            [
                _page([_text_frame([_para("成品良率 95.3%")])]),
                _page([_text_frame([_para("成品良率 95.4%")])], index=1),
            ]
        )
        findings = fca._check_numeric_consistency(d)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "CON-001"
        assert f.severity == FindingSeverity.ERROR

    def test_consistent_values_not_flagged(self):
        """同一指标数值一致 → 不触发 CON-001。"""
        fca = FactualAuditor()
        d = _doc(
            [
                _page([_text_frame([_para("成品良率 95.3%")])]),
                _page([_text_frame([_para("成品良率 95.3%")])], index=1),
            ]
        )
        assert fca._check_numeric_consistency(d) == []


class TestCon002RequiredSections:
    """CON-002: 必须包含的章节。"""

    def test_missing_section_flagged(self):
        """required_sections 未包含 → CON-002 ERROR。"""
        sa = StructureAuditor(config={"required_sections": ["概述"]})
        d = _doc([_page([_text_frame([_para("正文内容")])])])
        findings = sa._check_required_sections(d)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "CON-002"
        assert f.severity == FindingSeverity.ERROR
        assert "概述" in f.message

    def test_present_section_not_flagged(self):
        """required_sections 已包含 (全文回退匹配) → 不触发 CON-002。"""
        sa = StructureAuditor(config={"required_sections": ["概述"]})
        d = _doc([_page([_text_frame([_para("这是概述部分")])])])
        assert sa._check_required_sections(d) == []


class TestCon003ADefinedNeverUsed:
    """CON-003-A: 缩写定义后未再使用 (INFO)。"""

    def test_defined_never_used_flagged(self):
        """TSV 定义一次后未再出现 → CON-003-A INFO。"""
        fca = FactualAuditor()
        d = _doc([_page([_text_frame([_para("TSV (Through Silicon Via) 工艺。")])])])
        findings = fca._check_abbreviation_defined_never_used(d)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "CON-003-A"
        assert f.severity == FindingSeverity.INFO

    def test_defined_and_reused_not_flagged(self):
        """定义后再次使用 → 不触发 CON-003-A。"""
        fca = FactualAuditor()
        d = _doc(
            [_page([_text_frame([_para("TSV (Through Silicon Via) 工艺。TSV 用于先进封装。")])])]
        )
        assert fca._check_abbreviation_defined_never_used(d) == []


class TestCon003BMultiplyDefined:
    """CON-003-B: 同一缩写重复定义 (WARNING)。"""

    def test_multiply_defined_flagged(self):
        """TSV 定义两次 → CON-003-B WARNING。"""
        fca = FactualAuditor()
        d = _doc(
            [
                _page(
                    [
                        _text_frame(
                            [_para("TSV (Through Silicon Via) 工艺。TSV (硅通孔) 用于先进封装。")]
                        )
                    ]
                )
            ]
        )
        findings = fca._check_abbreviation_multiply_defined(d)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "CON-003-B"
        assert f.severity == FindingSeverity.WARNING

    def test_single_definition_not_flagged(self):
        """仅定义一次 → 不触发 CON-003-B。"""
        fca = FactualAuditor()
        d = _doc([_page([_text_frame([_para("TSV (Through Silicon Via) 工艺。TSV 用于封装。")])])])
        assert fca._check_abbreviation_multiply_defined(d) == []


class TestCon003CUsedBeforeDefined:
    """CON-003-C: 缩写在定义前使用 (WARNING)。"""

    def test_used_before_defined_flagged(self):
        """TSV 先裸用、后定义 → CON-003-C WARNING。"""
        fca = FactualAuditor()
        d = _doc(
            [
                _page(
                    [_text_frame([_para("TSV 用于先进封装。TSV (Through Silicon Via) 是硅通孔。")])]
                )
            ]
        )
        findings = fca._check_abbreviation_used_before_defined(d)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "CON-003-C"
        assert f.severity == FindingSeverity.WARNING

    def test_defined_first_not_flagged(self):
        """首次出现即定义 → 不触发 CON-003-C。"""
        fca = FactualAuditor()
        d = _doc([_page([_text_frame([_para("TSV (Through Silicon Via) 工艺。TSV 用于封装。")])])])
        assert fca._check_abbreviation_used_before_defined(d) == []


class TestFmt003PerPageCharLimit:
    """FMT-003: 单页文本量限制。"""

    def test_over_limit_flagged(self):
        """单页 >200 字 → FMT-003 WARNING。"""
        fa = FormatAuditor()
        d = _doc([_page([_text_frame([_para("测" * 250)])])])
        findings = fa._check_per_page_char_limit(d.pages[0], d)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "FMT-003"
        assert f.severity == FindingSeverity.WARNING

    def test_under_limit_not_flagged(self):
        """单页少量文本 → 不触发 FMT-003。"""
        fa = FormatAuditor()
        d = _doc([_page([_text_frame([_para("短文本")])])])
        assert fa._check_per_page_char_limit(d.pages[0], d) == []


class TestFmt004ParagraphLength:
    """FMT-004: 单段不超过 3 行 (中文超限 / 显式换行)。"""

    def test_chinese_over_limit_flagged(self):
        """中文超限 (>=150 字) → FMT-004 WARNING。"""
        fa = FormatAuditor()
        d = _doc([_page([_text_frame([_para("中" * 160)])])])
        findings = fa._check_paragraph_length(d.pages[0])
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "FMT-004"
        assert f.severity == FindingSeverity.WARNING

    def test_explicit_newlines_flagged(self):
        """显式换行 >=3 行 → FMT-004 WARNING。"""
        fa = FormatAuditor()
        text = "第一行\n第二行\n第三行\n第四行"
        d = _doc([_page([_text_frame([_para(text)])])])
        findings = fa._check_paragraph_length(d.pages[0])
        assert len(findings) == 1
        assert findings[0].rule_id == "FMT-004"

    def test_short_paragraph_not_flagged(self):
        """短段落 → 不触发 FMT-004。"""
        fa = FormatAuditor()
        d = _doc([_page([_text_frame([_para("短段落")])])])
        assert fa._check_paragraph_length(d.pages[0]) == []


class TestFmt005ElementOverflow:
    """FMT-005: 元素不超出页面边界 (默认 960x540, 容差 5pt)。"""

    def test_overflow_flagged(self):
        """right=1100 > 965 → FMT-005 ERROR。"""
        fa = FormatAuditor()
        d = _doc([_page([_text_frame([], left=1000.0, top=100.0, width=100.0, height=50.0)])])
        findings = fa._check_element_overflow(d.pages[0], d)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "FMT-005"
        assert f.severity == FindingSeverity.ERROR

    def test_within_bounds_not_flagged(self):
        """元素在边界内 → 不触发 FMT-005。"""
        fa = FormatAuditor()
        d = _doc([_page([_text_frame([], left=100.0, top=100.0, width=200.0, height=100.0)])])
        assert fa._check_element_overflow(d.pages[0], d) == []

    def test_overflow_fires_through_full_pipeline(self):
        """FMT-005 经完整流水线 (build_auditors → run_auditors, dispatch 模式) 必须触发。"""
        from src.engines.pipeline import build_auditors, run_auditors

        d = _doc([_page([_text_frame([], left=1000.0, top=100.0, width=100.0, height=50.0)])])
        auditors = build_auditors(
            str(PROJECT_ROOT / "rules.md"),
            str(PROJECT_ROOT / "glossary"),
            str(PROJECT_ROOT / "vocab"),
        )
        findings = run_auditors(d, auditors)
        fmt005 = [f for f in findings if f.rule_id == "FMT-005"]
        assert fmt005, "流水线未产生 FMT-005 — element_overflow 检查静默失效"


class TestFmt006EmptyPlaceholder:
    """FMT-006: 空占位符检测 (PPTX)。"""

    def test_empty_placeholder_flagged(self):
        """空占位符 (is_placeholder 且无内容) → FMT-006 WARNING。"""
        fa = FormatAuditor()
        d = _doc([_page([_text_frame([_para("")], is_placeholder=True)])], fmt="pptx")
        findings = fa._check_empty_placeholders(d.pages[0], d)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "FMT-006"
        assert f.severity == FindingSeverity.WARNING

    def test_filled_placeholder_not_flagged(self):
        """占位符有内容 → 不触发 FMT-006。"""
        fa = FormatAuditor()
        d = _doc([_page([_text_frame([_para("有内容")], is_placeholder=True)])], fmt="pptx")
        assert fa._check_empty_placeholders(d.pages[0], d) == []


class TestFmt007BulletConsistency:
    """FMT-007: 项目符号样式一致性。"""

    def test_mixed_bullets_flagged(self):
        """同页混用符号 (•) 与数字 (1.) → FMT-007 INFO。"""
        fa = FormatAuditor()
        d = _doc([_page([_text_frame([_para("• 第一项"), _para("1. 第二项")])])])
        findings = fa._check_bullet_consistency(d.pages[0], d)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "FMT-007"
        assert f.severity == FindingSeverity.INFO

    def test_single_bullet_style_not_flagged(self):
        """同页仅一种符号样式 → 不触发 FMT-007。"""
        fa = FormatAuditor()
        d = _doc([_page([_text_frame([_para("• 第一项"), _para("• 第二项")])])])
        assert fa._check_bullet_consistency(d.pages[0], d) == []
