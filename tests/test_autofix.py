"""AutoFixer 单元测试 — 字体修复 / 间距修复 / 原子写入 / 链式修复"""


import pytest
from pptx import Presentation
from pptx.util import Inches, Pt

from src.engines.autofix import AutoFixer


@pytest.fixture
def fixer():
    return AutoFixer(allowed_fonts=["微软雅黑", "Arial"])


@pytest.fixture
def sample_pptx(tmp_path):
    """创建含非标准字体的测试 PPTX"""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])  # blank
    txBox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = "测试文本"
    run.font.name = "宋体"  # 非标准字体
    run.font.size = Pt(10)  # 过小字号
    path = tmp_path / "test_input.pptx"
    prs.save(str(path))
    return path


@pytest.fixture
def spacing_pptx(tmp_path):
    """创建含中英文紧排的测试 PPTX"""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    txBox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = "使用FinFET技术"
    run.font.name = "Arial"
    path = tmp_path / "test_spacing.pptx"
    prs.save(str(path))
    return path


class TestFixPptx:
    """fix_pptx: 字体标准化 + 字号修正"""

    def test_nonstandard_font_replaced(self, fixer, sample_pptx, tmp_path):
        out = tmp_path / "output.pptx"
        fixer.fix_pptx(sample_pptx, out)
        assert out.exists()
        assert fixer.fix_count >= 1
        # 验证字体已替换
        prs = Presentation(str(out))
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        for run in para.runs:
                            if run.text:
                                assert run.font.name in fixer.allowed_fonts

    def test_small_font_size_corrected(self, fixer, sample_pptx, tmp_path):
        out = tmp_path / "output.pptx"
        fixer.fix_pptx(sample_pptx, out)
        prs = Presentation(str(out))
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        for run in para.runs:
                            if run.font.size:
                                assert run.font.size >= Pt(12)

    def test_atomic_write_no_corrupt_on_success(self, fixer, sample_pptx, tmp_path):
        """成功时目标文件存在且有效"""
        out = tmp_path / "output.pptx"
        result = fixer.fix_pptx(sample_pptx, out)
        assert result == out
        # 文件可被正常打开
        prs = Presentation(str(out))
        assert len(prs.slides) == 1

    def test_source_unchanged(self, fixer, sample_pptx, tmp_path):
        """源文件不被修改"""
        original_size = sample_pptx.stat().st_size
        out = tmp_path / "output.pptx"
        fixer.fix_pptx(sample_pptx, out)
        assert sample_pptx.stat().st_size == original_size


class TestFixSpacing:
    """fix_spacing: CJK-Latin 间距修复"""

    def test_spacing_inserted(self, fixer, spacing_pptx, tmp_path):
        out = tmp_path / "output_spacing.pptx"
        fixer.fix_spacing(spacing_pptx, out)
        assert out.exists()
        assert fixer.fix_count >= 1
        prs = Presentation(str(out))
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    text = shape.text_frame.text
                    if "FinFET" in text:
                        # 验证中英文之间有空格
                        assert " FinFET" in text or "FinFET " in text

    def test_unsupported_format_raises(self, fixer, tmp_path):
        """非 PPTX/DOCX 格式 → ValueError"""
        fake = tmp_path / "test.pdf"
        fake.write_text("fake")
        with pytest.raises(ValueError, match="仅支持"):
            fixer.fix_spacing(fake, tmp_path / "out.pdf")


class TestFixElementOverflow:
    """fix_element_overflow: 溢出元素移回边界"""

    def test_overflow_corrected(self, fixer, tmp_path):
        """负 left 值的 shape 被修正为 0"""
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        txBox = slide.shapes.add_textbox(Inches(0), Inches(0), Inches(2), Inches(1))
        # 手动设置为负值 (溢出左边界)
        txBox.left = -100000  # 负 EMU
        path = tmp_path / "overflow.pptx"
        prs.save(str(path))

        out = tmp_path / "overflow_fixed.pptx"
        fixer.fix_element_overflow(path, out)
        assert fixer.fix_count >= 1
        prs2 = Presentation(str(out))
        for shape in prs2.slides[0].shapes:
            assert shape.left >= 0

    def test_non_pptx_raises(self, fixer, tmp_path):
        fake = tmp_path / "test.docx"
        fake.write_text("fake")
        with pytest.raises(ValueError, match="仅支持 PPTX"):
            fixer.fix_element_overflow(fake, tmp_path / "out.docx")


class TestFixTitlePunctuation:
    """fix_title_punctuation: 标题末尾标点去除"""

    def test_trailing_punct_removed(self, fixer, tmp_path):
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[0])  # title slide
        slide.shapes.title.text = "项目总结。"
        path = tmp_path / "title.pptx"
        prs.save(str(path))

        out = tmp_path / "title_fixed.pptx"
        fixer.fix_title_punctuation(path, out)
        assert fixer.fix_count >= 1
        prs2 = Presentation(str(out))
        title_text = prs2.slides[0].shapes.title.text
        assert not title_text.endswith("。")


class TestFixBulletStyle:
    """fix_bullet_style: 项目符号统一"""

    def test_dash_replaced_with_bullet(self, fixer, tmp_path):
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        txBox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(2))
        tf = txBox.text_frame
        tf.paragraphs[0].add_run().text = "- 第一项"
        p2 = tf.add_paragraph()
        p2.add_run().text = "- 第二项"
        path = tmp_path / "bullet.pptx"
        prs.save(str(path))

        out = tmp_path / "bullet_fixed.pptx"
        fixer.fix_bullet_style(path, out)
        assert fixer.fix_count >= 1
        prs2 = Presentation(str(out))
        for shape in prs2.slides[0].shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        assert not run.text.strip().startswith("- ")


class TestChainedFix:
    """链式修复: 前一步输出作为后一步输入"""

    def test_font_then_spacing(self, fixer, tmp_path):
        """字体修复 → 间距修复 链式执行"""
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        txBox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
        tf = txBox.text_frame
        run = tf.paragraphs[0].add_run()
        run.text = "使用FinFET技术"
        run.font.name = "宋体"
        path = tmp_path / "chain.pptx"
        prs.save(str(path))

        out = tmp_path / "chain_fixed.pptx"
        fixer.fix_pptx(path, out)
        font_fixes = fixer.fix_count
        fixer.fix_spacing(out, out)  # 链式: 在字体修复输出上继续
        spacing_fixes = fixer.fix_count

        assert font_fixes >= 1
        assert spacing_fixes >= 1
        assert out.exists()
