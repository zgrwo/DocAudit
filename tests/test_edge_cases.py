"""边界测试 — 空文档 / 单页 / 空元素等极端输入不应导致异常。

审查发现 P1：缺少空文档/0 页输入边界测试。本文件补充覆盖。
"""

import pytest

from src.auditors.structure import StructureAuditor
from src.auditors.format import FormatAuditor
from src.auditors.factual import FactualAuditor
from src.auditors.language import LanguageAuditor
from src.models.document import Document, DocumentMetadata, Page, PageElement, Paragraph


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
