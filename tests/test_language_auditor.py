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

pytestmark = pytest.mark.slow  # 含 LanguageTool 探测/语言引擎集成：快测跳过


def _make_doc(text: str, fmt: str = "pptx") -> Document:
    """构造单页测试文档"""
    return Document(
        source_path="test.pptx",
        format=fmt,
        metadata=DocumentMetadata(),
        pages=[
            Page(
                index=0,
                elements=[
                    PageElement(
                        type="text_frame",
                        paragraphs=[Paragraph(text=text)],
                    )
                ],
                slide_number=1,
            )
        ],
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
    return LanguageAuditor(
        config={
            "glossary_dir": None,
            "vocab_dir": str(vocab_dir),
        }
    )


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


class TestPunctuation:
    """2026-10-28: 标点冗余/冲突/全半角/配对检查。"""

    def test_repeated_semicolon(self, auditor):
        findings = auditor._check_punctuation("参数如下；；请确认。", 0, "第 1 页")
        assert [f.rule_id for f in findings] == ["PUNCT-001"]

    def test_adjacent_conflicting_punctuation(self, auditor):
        findings = auditor._check_punctuation("参数如下，。请确认。", 0, "第 1 页")
        assert [f.rule_id for f in findings] == ["PUNCT-002"]

    def test_chinese_followed_by_ascii_punctuation(self, auditor):
        findings = auditor._check_punctuation("中文, English", 0, "第 1 页")
        assert [f.rule_id for f in findings] == ["PUNCT-003"]

    def test_fullwidth_alnum(self, auditor):
        findings = auditor._check_punctuation("版本ＡＢＣ１２３", 0, "第 1 页")
        assert [f.rule_id for f in findings] == ["PUNCT-004"]

    def test_unmatched_quote(self, auditor):
        findings = auditor._check_punctuation("“未闭合的引号", 0, "第 1 页")
        assert [f.rule_id for f in findings] == ["PUNCT-005"]

    def test_english_ellipsis_in_chinese_context(self, auditor):
        findings = auditor._check_punctuation("中文 test... 内容", 0, "第 1 页")
        assert [f.rule_id for f in findings] == ["PUNCT-006"]

    def test_double_hyphen_in_chinese_context(self, auditor):
        findings = auditor._check_punctuation("中文--测试", 0, "第 1 页")
        assert [f.rule_id for f in findings] == ["PUNCT-007"]

    def test_url_with_comma_not_flagged(self, auditor):
        findings = auditor._check_punctuation(
            "详见 https://example.com/a,b，然后继续。", 0, "第 1 页"
        )
        assert all(f.rule_id != "PUNCT-003" for f in findings)

    def test_fenced_code_not_flagged(self, auditor):
        findings = auditor._check_punctuation("```python\n中文, English\n```", 0, "第 1 页")
        assert findings == []

    def test_redundant_phrase(self, auditor):
        findings = auditor._check_redundancy("原因是设备故障造成的。", 0, "第 1 页")
        assert [f.rule_id for f in findings] == ["TXT-REDUNDANT"]

    def test_punctuation_and_chinese_patterns_run_without_lt(self, auditor, monkeypatch):
        """LanguageTool 后端可用 (或 _check_text 返回空) 时，自定义检查仍执行。"""
        monkeypatch.setattr(auditor, "_check_text", lambda *args, **kwargs: [])
        doc = _make_doc("他仔细的看了看，；；参数。")
        findings = auditor.audit(doc)
        rule_ids = {f.rule_id for f in findings}
        assert "PY-ZH-GRAMMAR" in rule_ids
        assert "PUNCT-001" in rule_ids


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


class TestDocumentConsistency:
    """2026-10-29: 日期/范围/单位写法、项目符号标点、重复句、近似重复页。"""

    @staticmethod
    def _doc(texts: list[str], fmt="md") -> Document:
        pages = [
            Page(
                index=i,
                slide_number=i + 1,
                elements=[PageElement(type="text_frame", paragraphs=[Paragraph(text=t)])],
            )
            for i, t in enumerate(texts)
        ]
        return Document(format=fmt, source_path="x", metadata=DocumentMetadata(), pages=pages)

    @staticmethod
    def _rule_ids(findings, *wanted) -> set[str]:
        return {f.rule_id for f in findings if f.rule_id in wanted}

    def test_date_format_mixed_flagged(self, auditor):
        doc = self._doc(["会议日期 2026年10月29日", "交付日期 2026-10-29"])
        ids = self._rule_ids(auditor.audit(doc), "PUNCT-008")
        assert ids == {"PUNCT-008"}

    def test_single_date_format_not_flagged(self, auditor):
        doc = self._doc(["会议日期 2026年10月29日", "交付日期 2026年11月1日"])
        assert "PUNCT-008" not in self._rule_ids(auditor.audit(doc), "PUNCT-008")

    def test_range_separator_mixed_flagged(self, auditor):
        doc = self._doc(["温度 10-20℃", "湿度 30~40%"])
        assert "PUNCT-009" in self._rule_ids(auditor.audit(doc), "PUNCT-009")

    def test_range_consistent_not_flagged(self, auditor):
        doc = self._doc(["温度 10-20℃", "湿度 30-40%"])
        assert "PUNCT-009" not in self._rule_ids(auditor.audit(doc), "PUNCT-009")

    def test_iso_date_not_treated_as_range(self, auditor):
        """2026-10-29 是日期，不应被范围连接符检查误判。"""
        doc = self._doc(["发布 2026-10-29", "温度 10-20℃"])
        assert "PUNCT-009" not in self._rule_ids(auditor.audit(doc), "PUNCT-009")

    def test_unit_spacing_mixed_flagged(self, auditor):
        doc = self._doc(["重量 10kg", "承重 20 kg"])
        assert "PUNCT-010" in self._rule_ids(auditor.audit(doc), "PUNCT-010")

    def test_unit_spacing_consistent_not_flagged(self, auditor):
        doc = self._doc(["重量 10 kg", "承重 20 kg"])
        assert "PUNCT-010" not in self._rule_ids(auditor.audit(doc), "PUNCT-010")

    def test_bullet_trailing_punct_mixed_flagged(self, auditor):
        page = Page(
            index=0,
            slide_number=1,
            elements=[
                PageElement(
                    type="text_frame",
                    paragraphs=[
                        Paragraph(text="• 第一条没有句号"),
                        Paragraph(text="• 第二条有句号。"),
                        Paragraph(text="• 第三条也没有"),
                    ],
                )
            ],
        )
        doc = Document(format="pptx", source_path="x", metadata=DocumentMetadata(), pages=[page])
        assert "TXT-BULLET-PUNCT" in self._rule_ids(auditor.audit(doc), "TXT-BULLET-PUNCT")

    def test_bullet_trailing_punct_consistent_not_flagged(self, auditor):
        page = Page(
            index=0,
            slide_number=1,
            elements=[
                PageElement(
                    type="text_frame",
                    paragraphs=[
                        Paragraph(text="• 第一条有句号。"),
                        Paragraph(text="• 第二条有句号。"),
                        Paragraph(text="• 第三条有句号。"),
                    ],
                )
            ],
        )
        doc = Document(format="pptx", source_path="x", metadata=DocumentMetadata(), pages=[page])
        assert "TXT-BULLET-PUNCT" not in self._rule_ids(auditor.audit(doc), "TXT-BULLET-PUNCT")

    def test_duplicate_sentence_across_pages_flagged(self, auditor):
        sentence = "这是第一页的完整句子内容，用于检测重复情况。"
        doc = self._doc([sentence + "另一句唯一内容。", sentence])
        assert "TXT-DUP-SENTENCE" in self._rule_ids(auditor.audit(doc), "TXT-DUP-SENTENCE")

    def test_unique_sentences_not_flagged(self, auditor):
        doc = self._doc(["第一页唯一句子内容，长度足够触发检测。", "第二页完全不同的句子内容。"])
        assert "TXT-DUP-SENTENCE" not in self._rule_ids(auditor.audit(doc), "TXT-DUP-SENTENCE")

    def test_near_duplicate_pages_flagged(self, auditor):
        body = "本页内容是完全相同的正文段落，用于近似重复页检测。" * 3
        doc = self._doc([body, body])
        assert "TXT-NEAR-DUP" in self._rule_ids(auditor.audit(doc), "TXT-NEAR-DUP")

    def test_near_duplicate_short_pages_ignored(self, auditor):
        doc = self._doc(["短", "短"])
        assert "TXT-NEAR-DUP" not in self._rule_ids(auditor.audit(doc), "TXT-NEAR-DUP")


class TestAuxiliaryReview:
    """2026-10-29: 页眉/页脚/脚注参与语言类审查。"""

    @staticmethod
    def _aux(kind: str, text: str) -> PageElement:
        return PageElement(
            type="text_frame",
            placeholder_type=kind,
            paragraphs=[Paragraph(text=text)],
        )

    def test_header_mixed_formatting_flagged(self, auditor):
        doc = _make_doc("正文")
        doc.auxiliary_elements.append(self._aux("header", "使用FinFET工艺。"))
        findings = auditor.audit(doc)
        hits = [f for f in findings if f.page_index is None and f.rule_id == "FMT-MIXED-002"]
        assert hits
        assert hits[0].location == "页眉"

    def test_footer_rejected_vocab_flagged(self, auditor):
        doc = _make_doc("正文")
        doc.auxiliary_elements.append(self._aux("footer", "kind of 说明"))
        findings = auditor.audit(doc)
        hits = [f for f in findings if f.page_index is None and f.rule_id == "VOCAB-REJECT"]
        assert hits
        assert hits[0].location == "页脚"

    def test_footnote_punctuation_flagged(self, auditor):
        doc = _make_doc("正文")
        doc.auxiliary_elements.append(self._aux("footnote", "注意：这是脚注内容！！"))
        findings = auditor.audit(doc)
        hits = [f for f in findings if f.page_index is None and f.rule_id == "PUNCT-001"]
        assert hits
        assert hits[0].location == "脚注"

    def test_no_auxiliary_no_neg_page_findings(self, auditor):
        findings = auditor.audit(_make_doc("正文内容。"))
        assert all(f.page_index is not None for f in findings)


class TestCjkBoundaryRegressions:
    """2026-10-29 深度审查回归：汉字紧邻数字时 \\b 失效。"""

    def test_date_format_flagged_when_cjk_adjacent(self, auditor):
        doc = _make_doc("自2026-10-29起生效，发布日期 2026年10月29日。")
        findings = auditor.audit(doc)
        assert any(f.rule_id == "PUNCT-008" for f in findings), findings

    def test_iso_date_adjacent_cjk_not_a_range(self, auditor):
        """日期连字符不得被 PUNCT-009 当范围连接符。"""
        doc = _make_doc("自2026-10-29起，量程3~5mm。")
        findings = auditor.audit(doc)
        assert not any(f.rule_id == "PUNCT-009" for f in findings), findings

    def test_unit_spacing_flagged_when_cjk_adjacent(self, auditor):
        doc = _make_doc("厚度为10mm的薄膜，另一处厚度 10 mm。")
        findings = auditor.audit(doc)
        assert any(f.rule_id == "PUNCT-010" for f in findings), findings

    def test_footer_not_counted_as_duplicate_sentence(self, auditor):
        doc = _make_doc("第一页正文内容。", "第二页正文内容。")
        footer = PageElement(
            type="text_frame",
            placeholder_type="footer",
            paragraphs=[Paragraph(text="本文件为内部资料，请勿外传。")],
        )
        for page in doc.pages:
            page.elements.append(footer)
        findings = auditor.audit(doc)
        assert not any(f.rule_id == "TXT-DUP-SENTENCE" for f in findings), findings


class TestLanguageToolBatching:
    """2026-10-29 深度审查 P1 回归：逐段 HTTP → 同语言合批 + 段级缓存。"""

    def test_one_request_per_language_and_cache(self, auditor):
        calls = []

        class FakeClient:
            is_available = True

            def check(self, text, language=None):
                calls.append((language, text))
                return []

        auditor.lt_client = FakeClient()
        text = "这是中文句子，含FinFET与TSV工艺参数。"
        auditor._check_text(text, 0, "第 1 页")
        first = len(calls)
        assert first <= 2, f"同页同语言应合并为至多 1 次请求，实际 {first}"
        # 同样的段再次出现（下一页/模板句）→ 命中缓存，零新增请求
        auditor._check_text(text, 1, "第 2 页")
        assert len(calls) == first
