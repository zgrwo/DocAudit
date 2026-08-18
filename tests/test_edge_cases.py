"""边界测试 — 空文档 / 单页 / 空元素等极端输入不应导致异常。

审查发现 P1：缺少空文档/0 页输入边界测试。本文件补充覆盖。
"""

from src.auditors.factual import FactualAuditor
from src.auditors.format import FormatAuditor
from src.auditors.structure import StructureAuditor
from src.models.document import Document, DocumentMetadata, Page, PageElement, Paragraph
from src.models.finding import FindingSeverity


def _make_doc(pages: list[Page]) -> Document:
    """构造测试文档"""
    return Document(
        source_path="test_empty.pptx",
        format="pptx",
        metadata=DocumentMetadata(),
        pages=pages,
    )


def _all_auditors():
    """返回全部无外部依赖的审计器实例"""
    return [
        StructureAuditor(config={"required_sections": []}),
        FormatAuditor(config={}),
        FactualAuditor(config={}),
    ]


class TestEmptyDocument:
    """空文档（0 页）不应崩溃"""

    def test_zero_pages_no_crash(self):
        """0 页文档：所有审计器应正常返回（可能产生提示，但不抛异常）"""
        doc = _make_doc([])
        for auditor in _all_auditors():
            findings = auditor.audit(doc)
            assert isinstance(findings, list)

    def test_zero_pages_all_text_empty(self):
        """0 页文档：all_text 应为空字符串"""
        doc = _make_doc([])
        assert doc.all_text == ""
        assert doc.all_paragraphs == []

    def test_zero_pages_required_sections_specific(self):
        """0 页文档：必含章节检查返回具体的 CON-002 ERROR (而非仅 isinstance 弱断言)"""
        doc = _make_doc([])
        sa = StructureAuditor(config={"required_sections": ["概述"]})
        findings = sa._check_required_sections(doc)
        assert len(findings) == 1
        assert findings[0].rule_id == "CON-002"
        assert findings[0].severity == FindingSeverity.ERROR
        assert "概述" in findings[0].message

    def test_zero_pages_conclusion_check_empty(self):
        """0 页文档：每页结论检查无页面可查 → 空列表"""
        doc = _make_doc([])
        sa = StructureAuditor(config={"required_sections": []})
        assert sa._check_every_slide_has_conclusion(doc) == []

    def test_zero_pages_structure_consistency_empty(self):
        """0 页文档：版式多样性检查无页面 → 不产生 STR-008 (不会因"0 种版式"误报)"""
        doc = _make_doc([])
        sa = StructureAuditor(config={"required_sections": []})
        assert sa._check_slide_structure_consistency(doc) == []


class TestEmptyPage:
    """单页但无元素"""

    def test_page_no_elements(self):
        """单页 0 元素：审计器不应崩溃"""
        doc = _make_doc([Page(index=0, elements=[])])
        for auditor in _all_auditors():
            findings = auditor.audit(doc)
            assert isinstance(findings, list)

    def test_page_flattened_elements_empty(self):
        """空页的 flattened_elements 应为空列表"""
        page = Page(index=0, elements=[])
        assert page.flattened_elements == []
        assert page.all_text == ""

    def test_empty_page_conclusion_flagged(self):
        """空页 (0 元素)：CON-004 每页结论检查必须触发 (无内容/无备注/无关键词)"""
        doc = _make_doc([Page(index=0, elements=[])])
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_every_slide_has_conclusion(doc)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "CON-004"
        assert f.severity == FindingSeverity.ERROR
        assert f.page_index == 0
        assert f.context == "(空白页)"

    def test_empty_page_with_conclusion_keyword_not_flagged(self):
        """空页含结论关键词（「结论」）→ CON-004 不触发"""
        elem = PageElement(
            type="text_frame", paragraphs=[Paragraph(text="结论：测试完成", runs=[])]
        )
        doc = _make_doc([Page(index=0, elements=[elem])])
        sa = StructureAuditor(config={"required_sections": []})
        assert sa._check_every_slide_has_conclusion(doc) == []

    def test_empty_page_with_three_content_paragraphs_not_flagged(self):
        """空页含 >=3 个内容段落 → CON-004 不触发 (实质性内容豁免)"""
        elems = [
            PageElement(type="text_frame", paragraphs=[Paragraph(text=f"内容 {i}", runs=[])])
            for i in range(3)
        ]
        doc = _make_doc([Page(index=0, elements=elems)])
        sa = StructureAuditor(config={"required_sections": []})
        assert sa._check_every_slide_has_conclusion(doc) == []


class TestEmptyElements:
    """元素存在但内容为空"""

    def test_text_frame_no_paragraphs(self):
        """文本框无段落：不应崩溃"""
        elem = PageElement(type="text_frame", paragraphs=[])
        doc = _make_doc([Page(index=0, elements=[elem])])
        for auditor in _all_auditors():
            findings = auditor.audit(doc)
            assert isinstance(findings, list)

    def test_empty_paragraph_text(self):
        """段落文本为空字符串/纯空白：不应崩溃"""
        elem = PageElement(
            type="text_frame",
            paragraphs=[Paragraph(text=""), Paragraph(text="   ")],
        )
        doc = _make_doc([Page(index=0, elements=[elem])])
        for auditor in _all_auditors():
            findings = auditor.audit(doc)
            assert isinstance(findings, list)

    def test_group_with_empty_children(self):
        """Group 元素含空子元素：flattened_elements 应正确展开"""
        child = PageElement(type="text_frame", paragraphs=[])
        group = PageElement(type="group", children=[child])
        page = Page(index=0, elements=[group])
        # group 自身 + 1 个子元素
        assert len(page.flattened_elements) == 2


class TestNoneTypeElement:
    """异常元素（type=None）应被安全跳过"""

    def test_none_type_element_skipped(self):
        """type=None 的元素应被 flattened_elements 跳过（不崩溃）"""
        bad_elem = PageElement(type=None, paragraphs=[])
        good_elem = PageElement(type="text_frame", paragraphs=[Paragraph(text="ok")])
        page = Page(index=0, elements=[bad_elem, good_elem])
        flat = page.flattened_elements
        # 坏元素被跳过，只剩好元素
        assert len(flat) == 1
        assert flat[0].type == "text_frame"
