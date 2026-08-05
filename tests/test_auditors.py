"""测试审计器 — 通过公共 audit() API 验证行为，确保测试与源码行为一致"""

import os
import tempfile

from src.auditors.factual import FactualAuditor
from src.auditors.format import FormatAuditor
from src.auditors.structure import StructureAuditor
from src.converters.pptx_converter import PptxConverter
from src.models.finding import FindingSeverity


class TestStructureAuditor:
    """通过 audit() 公共 API 和内部方法双重验证"""

    def test_title_slide_detection_via_audit(self):
        """STR-001: 第一页为标题版式 → audit() 不应产生 STR-001 ERROR"""
        doc = PptxConverter().convert("tests/fixtures/sample.pptx")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa.audit(doc)
        # sample.pptx 第一页为 Title Slide 版式 → 不应有 STR-001 告警
        str001_errors = [f for f in findings
                         if f.rule_id == "STR-001" and f.severity == FindingSeverity.ERROR]
        assert len(str001_errors) == 0, f"STR-001 should not fire on title slide, got: {str001_errors}"

    def test_title_slide_detection_direct(self):
        """STR-001: 直接调用 _check_title_slide → 空列表"""
        doc = PptxConverter().convert("tests/fixtures/sample.pptx")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_title_slide(doc)
        assert len(findings) == 0, f"Expected no title slide warning, got: {findings}"

    def test_every_slide_conclusion(self):
        """CON-004: 标题页豁免, 内容页应有足够内容"""
        doc = PptxConverter().convert("tests/fixtures/sample.pptx")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa.audit(doc)
        # 标题页豁免: 第一页不应有 CON-004 告警
        title_page_errors = [f for f in findings if f.page_index == 0
                            and f.rule_id == "CON-004"]
        assert len(title_page_errors) == 0, (
            f"Title slide should be exempt, got CON-004: {title_page_errors}"
        )

    def test_conclusion_findings_have_valid_structure(self):
        """CON-004: 所有 ERROR findings 必须有有效的 rule_id"""
        doc = PptxConverter().convert("tests/fixtures/sample.pptx")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_every_slide_has_conclusion(doc)
        for f in findings:
            if f.severity == FindingSeverity.ERROR:
                assert f.rule_id == "CON-004", f"Unexpected ERROR rule_id: {f.rule_id}"
                assert f.message, "Finding message should not be empty"
                assert f.page_index is not None, "Finding must have page_index"

    def test_title_length_or_condition(self):
        """STR-004: 纯中文超长标题应触发告警 — 验证 AND→OR 修复"""
        from pptx import Presentation
        prs = Presentation()
        slide_layout = prs.slide_layouts[0]
        s = prs.slides.add_slide(slide_layout)
        # 设置超长中文标题: ~50+ chars > 40 上限
        long_title = "这是一个非常长的中文标题用于测试标题长度检查功能是否正常工作验证超长标题检测逻辑是否正确触发告警机制"
        s.shapes.title.text = long_title

        tmp_path = None
        try:
            # 使用临时文件避免泄漏
            with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
                tmp_path = tmp.name
            prs.save(tmp_path)

            doc = PptxConverter().convert(tmp_path)
            sa = StructureAuditor(config={"required_sections": []})
            findings = sa._check_title_length(doc)
            assert len(findings) >= 1, (
                f"Long Chinese title ({len(long_title)} chars) should trigger STR-004. "
                f"Got {len(findings)} findings."
            )
            # 验证 finding 包含正确的元数据
            f = findings[0]
            assert f.rule_id == "STR-004"
            assert f.metadata.get("chinese_chars", 0) > 40
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)


class TestFormatAuditor:
    def test_font_consistency_audit_api(self):
        """FMT-001: 非标准字体应通过 audit() 被检测到"""
        doc = PptxConverter().convert("tests/fixtures/sample.pptx")
        findings = FormatAuditor().audit(doc)
        fmt001_findings = [f for f in findings if f.rule_id == "FMT-001"]
        assert len(fmt001_findings) >= 1, (
            f"Expected at least one FMT-001 (non-standard font) finding, got {len(fmt001_findings)}"
            + f"\nAll rule_ids: {[f.rule_id for f in findings]}"
        )
        # 验证 finding 结构完整
        for f in fmt001_findings:
            assert f.type.value == "format"
            assert f.message
            assert f.rule_id == "FMT-001"

    def test_font_size_max_check(self):
        """FMT-002: 验证字号最大值检查生效"""
        from pptx import Presentation
        from pptx.util import Pt
        prs = Presentation()
        slide_layout = prs.slide_layouts[0]
        s = prs.slides.add_slide(slide_layout)
        # 设置超大标题字号 (72pt > 40pt max)
        s.shapes.title.text = "Huge Title"
        s.shapes.title.text_frame.paragraphs[0].runs[0].font.size = Pt(72)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
                tmp_path = tmp.name
            prs.save(tmp_path)

            doc = PptxConverter().convert(tmp_path)
            findings = FormatAuditor().audit(doc)
            # 应检测到超大标题字号
            fmt002_max = [f for f in findings
                          if f.rule_id == "FMT-002" and "过大" in f.message]
            assert len(fmt002_max) >= 1, (
                f"72pt title should trigger FMT-002 max size warning. "
                f"All FMT-002: {[f.message for f in findings if f.rule_id == 'FMT-002']}"
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)


class TestFactualAuditor:
    def test_abbreviation_check_via_audit(self):
        """CON-003: 未定义缩写应通过 audit() 被检测"""
        doc = PptxConverter().convert("tests/fixtures/sample.pptx")
        findings = FactualAuditor().audit(doc)
        con003_findings = [f for f in findings if f.rule_id == "CON-003"]
        assert len(con003_findings) >= 1, (
            f"Expected at least one CON-003 (undefined abbreviation) finding, got {len(con003_findings)}"
        )
        # 验证发现包含正确信息
        for f in con003_findings:
            assert "未给出全称" in f.message, f"Unexpected message: {f.message}"
            assert f.type.value == "factual"
            assert f.severity == FindingSeverity.WARNING

    def test_common_uppercase_words_skipped(self):
        """CON-003: 常见英语大写单词 (THE, AND, NEW 等) 不应被标记为未定义缩写"""
        doc = PptxConverter().convert("tests/fixtures/sample.pptx")
        findings = FactualAuditor().audit(doc)
        # 验证 THE/AND/NEW 等常见词不在 findings 中
        con003_findings = [f for f in findings if f.rule_id == "CON-003"]
        common_words = {"THE", "AND", "FOR", "ALL", "BUT", "NOT", "CAN",
                        "ARE", "WAS", "HAS", "NEW", "SET", "END", "TOP"}
        for f in con003_findings:
            # 从 context 中提取缩写字面
            ctx = f.context or ""
            for word in common_words:
                if word in ctx:
                    # 确认这不是被标记的缩写
                    assert word not in (f.metadata.get("abbreviation") or ""), (
                        f"Common word '{word}' should not be flagged as undefined abbreviation"
                    )
