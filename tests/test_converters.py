"""Converter 单元测试 — DocxConverter 字段正确性 + MarkdownConverter 边界"""

import logging

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
        """标题样式段落被识别（style_name 含 Heading）"""
        doc = docx_converter.convert(str(sample_docx))
        # python-docx add_heading 不设置 outlineLvl，但样式名含 Heading
        all_elements = [e for p in doc.pages for e in p.flattened_elements]
        heading_elements = [
            e for e in all_elements if e.style_name and "heading" in e.style_name.lower()
        ]
        assert len(heading_elements) >= 1

    def test_style_name_moved_from_shape_name(self, docx_converter, sample_docx):
        """DOCX 段落样式名移到 style_name 字段, shape_name 恢复 None"""
        doc = docx_converter.convert(str(sample_docx))
        all_elements = [e for p in doc.pages for e in p.flattened_elements]
        heading_elems = [
            e for e in all_elements if e.style_name and "heading" in e.style_name.lower()
        ]
        assert len(heading_elems) >= 1, "Heading 样式段落应有 style_name"
        # shape_name 不再被 DOCX 样式名占用 (保留给 PPTX shape 名)
        for e in all_elements:
            assert e.shape_name is None, f"DOCX 元素 shape_name 应为 None, got {e.shape_name!r}"

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
        table_elements = [e for p in doc.pages for e in p.flattened_elements if e.type == "table"]
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
        tables = [e for p in result.pages for e in p.flattened_elements if e.type == "table"]
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

    def test_docx_run_font_name_east_asia_extracted(self, docx_converter, tmp_path):
        """eastAsia 中文字体被提取到 Run.font_name_east_asia（FMT-001 中文判定数据源）"""
        from docx.oxml.ns import qn

        doc = DocxDocument()
        p = doc.add_paragraph()
        run = p.add_run("中文正文")
        rPr = run._element.get_or_add_rPr()
        rPr.get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
        rPr.rFonts.set(qn("w:ascii"), "Arial")
        path = tmp_path / "ea.docx"
        doc.save(str(path))

        result = docx_converter.convert(str(path))
        run_model = next(
            r
            for page in result.pages
            for e in page.flattened_elements
            for para in e.paragraphs
            for r in para.runs
        )
        assert run_model.font_name_east_asia == "宋体"
        assert run_model.font_name == "Arial"  # latin 字体不受影响

    def test_docx_run_font_name_east_asia_none_when_missing(self, docx_converter, tmp_path):
        """无 eastAsia 字体时 font_name_east_asia 为 None"""
        doc = DocxDocument()
        p = doc.add_paragraph()
        p.add_run("纯文本")
        path = tmp_path / "plain.docx"
        doc.save(str(path))

        result = docx_converter.convert(str(path))
        run_model = next(
            r
            for page in result.pages
            for e in page.flattened_elements
            for para in e.paragraphs
            for r in para.runs
        )
        assert run_model.font_name_east_asia is None


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
        table_elems = [e for p in doc.pages for e in p.flattened_elements if e.type == "table"]
        assert len(table_elems) >= 1

    def test_list_item_with_pipe_not_table(self, md_converter, tmp_path):
        """回归: 列表项含竖线不得误判为表格 (修复: 曾把 '- 项 A | 内容' 解析成 table)"""
        md = "- 列表项 A | 内容\n- 普通列表项\n"
        path = tmp_path / "list.md"
        path.write_text(md, encoding="utf-8")
        doc = md_converter.convert(str(path))
        table_elems = [e for p in doc.pages for e in p.flattened_elements if e.type == "table"]
        assert len(table_elems) == 0, f"列表项不应被解析为表格: {table_elems}"
        # 两个列表项都应在文本中完整保留
        assert "- 列表项 A | 内容" in doc.all_text
        assert "- 普通列表项" in doc.all_text

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


def _inject_fake_docling(monkeypatch, converter_cls) -> None:
    """封闭式注入假 docling 模块到 sys.modules (不触发真实 import, CI 无依赖也可跑)。"""
    import sys
    import types

    fake_pkg = types.ModuleType("docling")
    fake_conv = types.ModuleType("docling.document_converter")
    fake_conv.DocumentConverter = converter_cls
    fake_pkg.document_converter = fake_conv
    monkeypatch.setitem(sys.modules, "docling", fake_pkg)
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_conv)


class TestPdfConverter:
    """PdfConverter 基本行为 (docling 可选依赖, 测试用封闭式 mock 不依赖安装)"""

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

    def test_convert_positive_path_with_cells_api(self, tmp_path, monkeypatch):
        """正路径: cells API 页面 → 文本完整保留 (docling mock, 封闭式注入不依赖安装)"""
        from src.converters.pdf_converter import PdfConverter

        class FakeCell:
            def __init__(self, text, row=0, col=0):
                self.text = text
                self.row = row
                self.col = col

        class FakePage:
            def __init__(self):
                self.cells = [FakeCell("第一段文本", 0, 0)]

        class FakeDoclingDoc:
            pages = {1: FakePage()}

        class FakeResult:
            document = FakeDoclingDoc()

        class FakeDoclingConverter:
            def __init__(self, *a, **kw):
                pass

            def convert(self, path):
                return FakeResult()

        # 封闭式注入: 直接挂 sys.modules, 不 import 真实 docling (CI 无该依赖也通过)
        _inject_fake_docling(monkeypatch, FakeDoclingConverter)
        fake = tmp_path / "sample.pdf"
        fake.write_bytes(b"%PDF-1.4 fake")

        doc = PdfConverter().convert(str(fake))
        assert doc.format == "pdf"
        assert doc.metadata.page_count == 1
        assert "第一段文本" in doc.all_text

    def test_convert_positive_path_with_tables_api(self, tmp_path, monkeypatch):
        """正路径: tables API + export_to_dataframe → table 元素 (docling/pandas mock 封闭)"""
        from src.converters.pdf_converter import PdfConverter

        class FakeDataFrame:
            """最小 iterrows 假实现, 避免依赖真实 pandas"""

            def iterrows(self):
                yield (0, ["表头A", "表头B"])
                yield (1, ["值1", "值2"])

        class FakeTable:
            def export_to_dataframe(self):
                return FakeDataFrame()

        class FakePage:
            def __init__(self):
                self.tables = [FakeTable()]

        class FakeDoclingDoc:
            pages = {1: FakePage()}

        class FakeResult:
            document = FakeDoclingDoc()

        class FakeDoclingConverter:
            def __init__(self, *a, **kw):
                pass

            def convert(self, path):
                return FakeResult()

        _inject_fake_docling(monkeypatch, FakeDoclingConverter)
        # 假 pandas 模块: 让 _convert_docling_table 的 import pandas 检查通过
        import sys
        import types

        monkeypatch.setitem(sys.modules, "pandas", types.ModuleType("pandas"))

        fake = tmp_path / "table.pdf"
        fake.write_bytes(b"%PDF-1.4 fake")

        doc = PdfConverter().convert(str(fake))
        tables = [e for p in doc.pages for e in p.flattened_elements if e.type == "table"]
        assert len(tables) == 1, f"期望 1 个表格元素, got {len(tables)}"
        cells = [c.text for row in tables[0].tables for c in row]
        assert cells == ["表头A", "表头B", "值1", "值2"]


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
        tables = [e for p in doc.pages for e in p.flattened_elements if e.type == "table"]
        assert tables, "应有表格元素"
        cells = [c for row in tables[0].tables for c in row]
        c00 = next(c for c in cells if (c.row, c.col) == (0, 0))
        assert c00.fill_color == "1E3A5F"
        assert c00.font_color == "FFFFFF"
        c01 = next(c for c in cells if (c.row, c.col) == (0, 1))
        assert c01.fill_color is None  # 无填充 → None (不误报)


class TestPptxConverterEastAsia:
    """PPTX a:ea (eastAsia) 中文字体提取"""

    def test_run_font_name_east_asia_extracted(self, tmp_path):
        """a:ea typeface 被提取到 Run.font_name_east_asia"""
        from lxml import etree
        from pptx import Presentation
        from pptx.oxml.ns import qn
        from pptx.util import Inches

        from src.converters.pptx_converter import PptxConverter

        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        txBox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
        run = txBox.text_frame.paragraphs[0].add_run()
        run.text = "中文正文"
        run.font.name = "Arial"
        # 手工创建 a:ea (python-pptx 1.0.2 无 get_or_add_ea)
        rPr = run.font._rPr
        ea = etree.SubElement(rPr, qn("a:ea"))
        ea.set("typeface", "宋体")

        path = tmp_path / "ea.pptx"
        prs.save(str(path))

        doc = PptxConverter().convert(str(path))
        run_model = next(
            r
            for page in doc.pages
            for e in page.flattened_elements
            for para in e.paragraphs
            for r in para.runs
        )
        assert run_model.font_name_east_asia == "宋体"
        assert run_model.font_name == "Arial"  # latin 字体不受影响

    def test_run_font_name_east_asia_none_when_missing(self, tmp_path):
        """无 a:ea 时 font_name_east_asia 为 None"""
        from pptx import Presentation
        from pptx.util import Inches

        from src.converters.pptx_converter import PptxConverter

        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        txBox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
        run = txBox.text_frame.paragraphs[0].add_run()
        run.text = "纯英文 text"
        run.font.name = "Arial"
        path = tmp_path / "plain.pptx"
        prs.save(str(path))

        doc = PptxConverter().convert(str(path))
        run_model = next(
            r
            for page in doc.pages
            for e in page.flattened_elements
            for para in e.paragraphs
            for r in para.runs
        )
        assert run_model.font_name_east_asia is None


class TestDocxNestedContentWarnings:
    """DOCX 未解析嵌套内容 (文本框/页眉页脚/脚注) 跳过时输出 logger.warning"""

    @staticmethod
    def _make_textbox_docx(path) -> None:
        """构造含 w:txbxContent 文本框的 docx (python-docx 无文本框 API，手工注入 XML)"""
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls

        WPS = 'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"'
        doc = DocxDocument()
        p = doc.add_paragraph("正文")
        run = p.add_run()
        drawing_xml = (
            "<w:drawing {w}>"
            "<wp:inline {wp}>"
            '<a:graphic {a}><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            "<wps:wsp {wps}><wps:txbx><w:txbxContent>"
            "<w:p><w:r><w:t>文本框内容</w:t></w:r></w:p>"
            "</w:txbxContent></wps:txbx></wps:wsp>"
            "</a:graphicData></a:graphic></wp:inline></w:drawing>"
        ).format(w=nsdecls("w"), wp=nsdecls("wp"), a=nsdecls("a"), wps=WPS)
        run._element.append(parse_xml(drawing_xml))
        doc.save(str(path))

    def test_textbox_content_skip_warned(self, docx_converter, tmp_path, caplog):
        """含 w:txbxContent 文本框 → logger.warning 提示跳过范围"""
        path = tmp_path / "txbx.docx"
        self._make_textbox_docx(path)
        with caplog.at_level(logging.WARNING, logger="src.converters.docx_converter"):
            docx_converter.convert(str(path))
        assert any("文本框" in r.message for r in caplog.records), (
            f"应输出文本框跳过警告, got: {[r.message for r in caplog.records]}"
        )

    def test_header_footer_skip_warned(self, docx_converter, tmp_path, caplog):
        """含页眉内容 → logger.warning 提示跳过范围"""
        path = tmp_path / "hdr.docx"
        doc = DocxDocument()
        doc.sections[0].header.paragraphs[0].text = "页眉内容"
        doc.save(str(path))
        with caplog.at_level(logging.WARNING, logger="src.converters.docx_converter"):
            docx_converter.convert(str(path))
        assert any("页眉" in r.message for r in caplog.records), (
            f"应输出页眉/页脚跳过警告, got: {[r.message for r in caplog.records]}"
        )

    def test_footnote_skip_warned(self, docx_converter, tmp_path, caplog):
        """含脚注部件 → logger.warning 提示跳过范围"""
        from docx.opc.constants import CONTENT_TYPE, RELATIONSHIP_TYPE
        from docx.opc.packuri import PackURI
        from docx.opc.part import Part

        path = tmp_path / "fn.docx"
        doc = DocxDocument()
        fn_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
            '<w:footnote w:id="1"><w:p><w:r><w:t xml:space="preserve"> 脚注内容</w:t></w:r></w:p></w:footnote>'
            "</w:footnotes>"
        )
        part = Part(
            PackURI("/word/footnotes.xml"),
            CONTENT_TYPE.WML_FOOTNOTES,
            fn_xml.encode("utf-8"),
            doc.part.package,
        )
        doc.part.relate_to(part, RELATIONSHIP_TYPE.FOOTNOTES)
        doc.save(str(path))
        with caplog.at_level(logging.WARNING, logger="src.converters.docx_converter"):
            docx_converter.convert(str(path))
        assert any("脚注" in r.message for r in caplog.records), (
            f"应输出脚注跳过警告, got: {[r.message for r in caplog.records]}"
        )
