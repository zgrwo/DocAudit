"""Converter 单元测试 — DocxConverter 字段正确性 + MarkdownConverter 边界"""


import pytest
from docx import Document as DocxDocument
from docx.shared import Pt

from src.converters.docx_converter import DocxConverter
from src.converters.md_converter import MarkdownConverter


@pytest.fixture
def docx_converter():
    return DocxConverter()


@pytest.fixture
def md_converter():
    return MarkdownConverter()


@pytest.fixture
def sample_docx(tmp_path):
    """创建含标题+正文+表格的测试 DOCX"""
    doc = DocxDocument()
    # 标题
    doc.add_heading("测试标题", level=1)
    # 正文段落
    p = doc.add_paragraph("这是正文内容。")
    run = p.runs[0]
    run.font.name = "Arial"
    run.font.size = Pt(12)
    # 二级标题
    doc.add_heading("第二节", level=2)
    doc.add_paragraph("第二节的内容。")
    # 表格
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "A1"
    table.cell(0, 1).text = "B1"
    table.cell(1, 0).text = "A2"
    table.cell(1, 1).text = "B2"

    path = tmp_path / "test.docx"
    doc.save(str(path))
    return path


class TestDocxConverter:
    """DocxConverter 转换正确性"""

    def test_can_handle(self, docx_converter):
        assert docx_converter.can_handle("test.docx")
        assert docx_converter.can_handle("test.doc")
        assert not docx_converter.can_handle("test.pptx")
        assert not docx_converter.can_handle("test.pdf")

    def test_convert_returns_document(self, docx_converter, sample_docx):
        doc = docx_converter.convert(str(sample_docx))
        assert doc.format == "docx"
        assert doc.source_path == str(sample_docx)
        assert len(doc.pages) >= 1

    def test_heading_detected_as_title(self, docx_converter, sample_docx):
        """标题样式段落被识别（shape_name 含 Heading）"""
        doc = docx_converter.convert(str(sample_docx))
        # python-docx add_heading 不设置 outlineLvl，但样式名含 Heading
        all_elements = [e for p in doc.pages for e in p.flattened_elements]
        heading_elements = [
            e for e in all_elements
            if e.shape_name and "heading" in e.shape_name.lower()
        ]
        assert len(heading_elements) >= 1

    def test_paragraph_text_preserved(self, docx_converter, sample_docx):
        """正文文本完整保留"""
        doc = docx_converter.convert(str(sample_docx))
        assert "这是正文内容。" in doc.all_text
        assert "第二节的内容。" in doc.all_text

    def test_font_info_extracted(self, docx_converter, sample_docx):
        """Run 级字体信息被提取"""
        doc = docx_converter.convert(str(sample_docx))
        found_arial = False
        for page in doc.pages:
            for elem in page.flattened_elements:
                for para in elem.paragraphs:
                    for run in para.runs:
                        if run.font_name == "Arial":
                            found_arial = True
                            assert run.font_size == 12.0
        assert found_arial, "Should find Arial font in converted document"

    def test_table_converted(self, docx_converter, sample_docx):
        """表格被正确转换"""
        doc = docx_converter.convert(str(sample_docx))
        table_elements = [
            e for p in doc.pages
            for e in p.flattened_elements
            if e.type == "table"
        ]
        assert len(table_elements) >= 1
        # 验证表格内容
        table_elem = table_elements[0]
        all_cell_text = [cell.text for row in table_elem.tables for cell in row]
        assert "A1" in all_cell_text
        assert "B2" in all_cell_text

    def test_metadata_extracted(self, docx_converter, sample_docx):
        """元数据（字数）被提取"""
        doc = docx_converter.convert(str(sample_docx))
        assert doc.metadata.word_count is not None
        assert doc.metadata.word_count > 0

    def test_table_cell_colors_extracted(self, docx_converter, tmp_path):
        """表格单元格: w:shd 底色 + 字体色提取 (FMT-008 数据源)"""
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import RGBColor

        doc = DocxDocument()
        table = doc.add_table(rows=2, cols=2)
        # 深蓝底 + 白字
        cell = table.cell(0, 0)
        cell.text = "深底浅字"
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), "1E3A5F")
        tcPr.append(shd)
        cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        # 无底色单元格
        table.cell(0, 1).text = "无底色"

        path = tmp_path / "table_colors.docx"
        doc.save(str(path))

        result = docx_converter.convert(str(path))
        tables = [
            e for p in result.pages
            for e in p.flattened_elements
            if e.type == "table"
        ]
        assert tables, "应有表格元素"
        cells = [c for row in tables[0].tables for c in row]
        c00 = next(c for c in cells if (c.row, c.col) == (0, 0))
        assert c00.fill_color == "1E3A5F"
        assert c00.font_color == "FFFFFF"
        c01 = next(c for c in cells if (c.row, c.col) == (0, 1))
        assert c01.fill_color is None  # 无底色 → None (不误报)

    def test_empty_docx_no_crash(self, docx_converter, tmp_path):
        """空 DOCX 不崩溃"""
        doc = DocxDocument()
        path = tmp_path / "empty.docx"
        doc.save(str(path))
        result = docx_converter.convert(str(path))
        assert result.format == "docx"
        assert len(result.pages) >= 1


class TestMarkdownConverter:
    """MarkdownConverter 边界测试"""

    def test_can_handle(self, md_converter):
        assert md_converter.can_handle("test.md")
        assert md_converter.can_handle("test.markdown")
        assert md_converter.can_handle("test.txt")
        assert not md_converter.can_handle("test.docx")

    def test_heading_levels(self, md_converter, tmp_path):
        """Markdown 标题层级正确映射"""
        md = "# H1\n\n## H2\n\n### H3\n\n正文\n"
        path = tmp_path / "test.md"
        path.write_text(md, encoding="utf-8")
        doc = md_converter.convert(str(path))
        # 应有标题元素
        all_paras = doc.all_paragraphs
        levels = [p.level for p in all_paras if p.level is not None]
        assert 1 in levels
        assert 2 in levels

    def test_code_block_preserved(self, md_converter, tmp_path):
        """围栏代码块完整保留"""
        md = "# Title\n\n```python\nprint('hello')\n```\n\nAfter code.\n"
        path = tmp_path / "code.md"
        path.write_text(md, encoding="utf-8")
        doc = md_converter.convert(str(path))
        assert "print('hello')" in doc.all_text

    def test_table_parsed(self, md_converter, tmp_path):
        """GFM 表格被解析为 table 元素"""
        md = "# Data\n\n| Name | Age |\n|------|-----|\n| Alice | 30 |\n"
        path = tmp_path / "table.md"
        path.write_text(md, encoding="utf-8")
        doc = md_converter.convert(str(path))
        table_elems = [
            e for p in doc.pages for e in p.flattened_elements if e.type == "table"
        ]
        assert len(table_elems) >= 1

    def test_gbk_encoding_fallback(self, md_converter, tmp_path):
        """GBK 编码文件正确读取"""
        path = tmp_path / "gbk.md"
        path.write_text("# 标题\n\n中文内容\n", encoding="gbk")
        doc = md_converter.convert(str(path))
        assert "中文内容" in doc.all_text

    def test_empty_file_no_crash(self, md_converter, tmp_path):
        """空文件不崩溃"""
        path = tmp_path / "empty.md"
        path.write_text("", encoding="utf-8")
        doc = md_converter.convert(str(path))
        assert doc.format == "md"

    def test_utf8_bom_frontmatter_still_detected(self, md_converter, tmp_path):
        """UTF-8 BOM 文件的 frontmatter 仍能正确解析 (BOM 剥离)"""
        path = tmp_path / "bom.md"
        content = "---\ntitle: BOM 文档\nauthor: tester\n---\n\n# 标题\n\n内容\n"
        path.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
        doc = md_converter.convert(str(path))
        assert doc.metadata.title == "BOM 文档"
        assert doc.metadata.author == "tester"
        assert "\ufeff" not in doc.all_text


class TestPdfConverter:
    """PdfConverter 基本行为 (docling 可选依赖)"""

    def test_can_handle(self):
        from src.converters.pdf_converter import PdfConverter
        cvt = PdfConverter()
        assert cvt.can_handle("test.pdf")
        assert cvt.can_handle("TEST.PDF")
        assert not cvt.can_handle("test.docx")

    def test_missing_docling_raises_helpful_error(self, tmp_path):
        """docling 未安装 → 抛出含安装指引的 ImportError"""
        pytest.importorskip("src.converters.pdf_converter")
        try:
            import docling  # noqa: F401
            pytest.skip("docling 已安装，无法验证缺失依赖路径")
        except ImportError:
            pass
        from src.converters.pdf_converter import PdfConverter
        fake = tmp_path / "fake.pdf"
        fake.write_bytes(b"%PDF-1.4 fake content")
        with pytest.raises(ImportError, match="docling"):
            PdfConverter().convert(str(fake))


class TestPptxConverterTableColors:
    """PPTX 表格单元格底色/字体色提取 (FMT-008 数据源)"""

    def test_table_cell_colors_extracted(self, tmp_path):
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.util import Inches

        from src.converters.pptx_converter import PptxConverter

        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        shape = slide.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(4), Inches(1))
        table = shape.table
        # 深蓝底 + 白字
        cell = table.cell(0, 0)
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor(0x1E, 0x3A, 0x5F)
        cell.text = "深底浅字"
        cell.text_frame.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        # 无填充单元格
        table.cell(0, 1).text = "无填充"

        path = tmp_path / "table_colors.pptx"
        prs.save(str(path))

        doc = PptxConverter().convert(str(path))
        tables = [
            e for p in doc.pages
            for e in p.flattened_elements
            if e.type == "table"
        ]
        assert tables, "应有表格元素"
        cells = [c for row in tables[0].tables for c in row]
        c00 = next(c for c in cells if (c.row, c.col) == (0, 0))
        assert c00.fill_color == "1E3A5F"
        assert c00.font_color == "FFFFFF"
        c01 = next(c for c in cells if (c.row, c.col) == (0, 1))
        assert c01.fill_color is None  # 无填充 → None (不误报)
