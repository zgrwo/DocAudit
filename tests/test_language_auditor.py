"""LanguageAuditor 独立单元测试 — 中英混排检查 + 禁用词 + 混排格式"""

import pytest

from src.auditors.language import LanguageAuditor
from src.models.document import (
    Document,
    DocumentMetadata,
    Page,
    PageElement,
    Paragraph,
)
from src.models.finding import FindingSeverity, FindingType


def _make_doc(text: str, fmt: str = "pptx") -> Document:
    """构造单页测试文档"""
    return Document(
        source_path="test.pptx",
        format=fmt,
        metadata=DocumentMetadata(),
        pages=[Page(
            index=0,
            elements=[PageElement(
                type="text_frame",
                paragraphs=[Paragraph(text=text)],
            )],
            slide_number=1,
        )],
    )


@pytest.fixture
def auditor(tmp_path):
    """创建无外部依赖的 LanguageAuditor (无 LanguageTool, 无术语表)"""
    vocab_dir = tmp_path / "vocab"
    vocab_dir.mkdir()
    (vocab_dir / "accept.txt").write_text("FinFET\nTSV\n", encoding="utf-8")
    (vocab_dir / "reject.txt").write_text(
        "kind of # 非正式用语\n利用 # 建议使用'使用'\n", encoding="utf-8"
    )
    return LanguageAuditor(config={
        "glossary_dir": None,
        "vocab_dir": str(vocab_dir),
    })


class TestMixedFormatting:
    """_check_mixed_formatting: CJK-Latin 间距与标点检查"""

    def test_cjk_latin_missing_space(self, auditor):
        """中文紧接英文 → 产生 FMT-MIXED 提示"""
        findings = auditor._check_mixed_formatting("使用FinFET技术", 0, "第 1 页")
        rule_ids = [f.rule_id for f in findings]
        assert "FMT-MIXED-001" in rule_ids or "FMT-MIXED-002" in rule_ids

    def test_proper_spacing_no_finding(self, auditor):
        """中英文之间有空格 → 无 FMT-MIXED-001/002"""
        findings = auditor._check_mixed_formatting("使用 FinFET 技术", 0, "第 1 页")
        mixed_001_002 = [f for f in findings if f.rule_id in ("FMT-MIXED-001", "FMT-MIXED-002")]
        assert len(mixed_001_002) == 0

    def test_latin_chinese_punct(self, auditor):
        """英文后使用中文标点 → FMT-MIXED-003"""
        findings = auditor._check_mixed_formatting("FinFET，很好", 0, "第 1 页")
        rule_ids = [f.rule_id for f in findings]
        assert "FMT-MIXED-003" in rule_ids

    def test_pure_chinese_no_finding(self, auditor):
        """纯中文文本 → 无混排 finding"""
        findings = auditor._check_mixed_formatting("这是一段纯中文文本", 0, "第 1 页")
        assert len(findings) == 0

    def test_consolidated_finding_count(self, auditor):
        """多处违规 → 每种模式最多 1 条 consolidated finding"""
        text = "使用FinFET进行TSV工艺开发CMOS"
        findings = auditor._check_mixed_formatting(text, 0, "第 1 页")
        # 每种 rule_id 最多 1 条
        rule_ids = [f.rule_id for f in findings]
        assert len(rule_ids) == len(set(rule_ids))


class TestRejectedVocab:
    """_check_rejected_vocab: reject.txt 禁用词检查"""

    def test_reject_literal_word(self, auditor):
        """匹配禁用词 → 产生 finding"""
        findings = auditor._check_rejected_vocab("我们利用该技术", 0, "第 1 页")
        assert len(findings) >= 1
        assert any("利用" in f.message for f in findings)

    def test_reject_phrase(self, auditor):
        """匹配禁用短语"""
        findings = auditor._check_rejected_vocab("this is kind of slow", 0, "第 1 页")
        assert len(findings) >= 1
        assert any("kind of" in f.message for f in findings)

    def test_no_reject_clean_text(self, auditor):
        """干净文本 → 无禁用词 finding"""
        findings = auditor._check_rejected_vocab("我们使用该技术", 0, "第 1 页")
        assert len(findings) == 0

    def test_finding_metadata(self, auditor):
        """禁用词 finding 包含正确字段"""
        findings = auditor._check_rejected_vocab("利用先进工艺", 0, "第 1 页")
        assert len(findings) >= 1
        f = findings[0]
        assert f.type == FindingType.LANGUAGE
        assert f.severity == FindingSeverity.WARNING
        assert f.rule_id == "VOCAB-REJECT"
        assert f.page_index == 0


class TestSegmentByLanguage:
    """_segment_by_language: 中英混合分段"""

    def test_pure_chinese_single_segment(self, auditor):
        segments = auditor._segment_by_language("这是纯中文文本")
        assert len(segments) == 1
        assert segments[0][1] == "zh"

    def test_pure_english_single_segment(self, auditor):
        segments = auditor._segment_by_language("This is pure English")
        assert len(segments) == 1
        assert segments[0][1] == "en"

    def test_mixed_produces_multiple_segments(self, auditor):
        segments = auditor._segment_by_language("使用FinFET技术开发TSV")
        langs = [lang for _, lang in segments]
        assert "zh" in langs
        assert "en" in langs

    def test_numbers_dont_switch_language(self, auditor):
        """数字不触发语言切换"""
        segments = auditor._segment_by_language("良率达到95%以上")
        # 整段应视为中文（数字保持当前语言）
        zh_segments = [s for s, lang in segments if lang == "zh"]
        assert len(zh_segments) >= 1

    def test_empty_text(self, auditor):
        segments = auditor._segment_by_language("")
        assert segments == []


class TestVocabularyIntegration:
    """Vocabulary 白名单在 LanguageAuditor 中的集成"""

    def test_accepted_word_in_debug(self, auditor):
        """白名单词 (FinFET) 被正确识别"""
        assert auditor.vocabulary.is_accepted("FinFET")
        assert auditor.vocabulary.is_accepted("finfet")  # 大小写不敏感
        assert not auditor.vocabulary.is_accepted("unknown_word")
