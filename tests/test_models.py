"""测试统一文档模型"""

from src.models.document import Document, DocumentMetadata, Page, PageElement, Paragraph, Run
from src.models.finding import AuditFinding, FindingSeverity, FindingType


class TestDocumentModel:
    def test_page_all_text(self):
        page = Page(index=0, elements=[
            PageElement(type="text_frame", paragraphs=[
                Paragraph(text="Hello", runs=[Run(text="Hello")]),
                Paragraph(text="World", runs=[Run(text="World")]),
            ]),
        ])
        assert "Hello" in page.all_text
        assert "World" in page.all_text

    def test_page_all_text_caching(self):
        page = Page(index=0, elements=[
            PageElement(type="text_frame", paragraphs=[
                Paragraph(text="Cached", runs=[Run(text="Cached")]),
            ]),
        ])
        t1 = page.all_text
        t2 = page.all_text
        assert t1 is t2  # same object, cached

    def test_flattened_elements(self):
        child = PageElement(type="text_frame", paragraphs=[
            Paragraph(text="child", runs=[])
        ])
        group = PageElement(type="group", children=[child])
        page = Page(index=0, elements=[group])
        flat = page.flattened_elements
        assert len(flat) == 2  # group + child

    def test_document_all_text(self):
        doc = Document(
            source_path="test.pptx", format="pptx",
            metadata=DocumentMetadata(),
            pages=[Page(index=0, elements=[
                PageElement(type="text_frame", paragraphs=[
                    Paragraph(text="Page 1", runs=[]),
                ]),
            ])],
        )
        assert "Page 1" in doc.all_text


class TestAuditFinding:
    def test_dedup_removes_duplicates(self):
        f1 = AuditFinding(
            type=FindingType.STRUCTURE, severity=FindingSeverity.ERROR,
            message="test", rule_id="STR-001", page_index=0, context="ctx",
        )
        f2 = AuditFinding(
            type=FindingType.STRUCTURE, severity=FindingSeverity.WARNING,
            message="test", rule_id="STR-001", page_index=0, context="ctx",
        )
        result = AuditFinding.deduplicate([f1, f2])
        assert len(result) == 1
        assert result[0].severity == FindingSeverity.ERROR  # keeps higher severity

    def test_dedup_keeps_different(self):
        f1 = AuditFinding(
            type=FindingType.STRUCTURE, severity=FindingSeverity.ERROR,
            message="a", rule_id="STR-001", page_index=0, context="a",
        )
        f2 = AuditFinding(
            type=FindingType.STRUCTURE, severity=FindingSeverity.ERROR,
            message="b", rule_id="STR-001", page_index=1, context="b",
        )
        result = AuditFinding.deduplicate([f1, f2])
        assert len(result) == 2

    def test_dedup_key_different_types(self):
        f1 = AuditFinding(
            type=FindingType.STRUCTURE, severity=FindingSeverity.ERROR,
            message="test", rule_id="X", page_index=0, context="x",
        )
        f2 = AuditFinding(
            type=FindingType.FORMAT, severity=FindingSeverity.ERROR,
            message="test", rule_id="X", page_index=0, context="x",
        )
        result = AuditFinding.deduplicate([f1, f2])
        assert len(result) == 2  # different types, keep both
