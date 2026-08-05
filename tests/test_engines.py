"""测试引擎层 — TerminologyChecker, Vocabulary, LanguageAuditor"""


from src.auditors.language import LanguageAuditor
from src.engines.terminology import (
    TermGlossary,
    TerminologyChecker,
    TermRule,
    _already_preferred,
)
from src.engines.vocabulary import Vocabulary, _has_regex_chars

# ── Terminology: _already_preferred ──────────────────────────

class TestAlreadyPreferred:
    """验证术语检查的守卫逻辑正确跳过已使用推荐写法的文本"""

    def test_preferred_with_parens_already_in_text(self):
        """文档已使用 'TSV (Through Silicon Via)' → 应跳过"""
        text = "TSV (Through Silicon Via, 硅通孔) 是实现 3D 集成的关键技术"
        preferred = "TSV (Through Silicon Via, 硅通孔)"
        # 模拟正则匹配到 "Through Silicon Via"
        match_start = text.find("Through Silicon Via")
        match_end = match_start + len("Through Silicon Via")
        assert _already_preferred(text, match_start, match_end, preferred) is True

    def test_preferred_abbrev_not_yet_used(self):
        """文档只有 'Through Silicon Via'，未使用 'TSV' → 不应跳过"""
        text = "Through Silicon Via 技术可用于 3D 集成"
        preferred = "TSV (Through Silicon Via, 硅通孔)"
        match_start = text.find("Through Silicon Via")
        match_end = match_start + len("Through Silicon Via")
        assert _already_preferred(text, match_start, match_end, preferred) is False

    def test_simple_preferred_word(self):
        """简单 preferred (如 'use') — 已在文本中 → 应跳过"""
        text = "you should use standard fonts"
        preferred = "use"
        match_start = text.find("use")
        match_end = match_start + len("use")
        assert _already_preferred(text, match_start, match_end, preferred) is True

    def test_short_search_term_skipped(self):
        """search_term < 2 字符 → 返回 False (不做守卫)"""
        text = "A simple test"
        preferred = "A"
        match_start = text.find("A")
        match_end = match_start + 1
        assert _already_preferred(text, match_start, match_end, preferred) is False

    def test_window_boundary_no_crash(self):
        """匹配位置在文本开头/结尾 → 窗口计算不越界"""
        text = "TSV tech"
        preferred = "TSV (Through Silicon Via)"
        # 匹配在开头
        assert _already_preferred(text, 0, 3, preferred) is True
        # 匹配在结尾
        text2 = "tech TSV"
        match_start = text2.find("TSV")
        assert _already_preferred(text2, match_start, match_start + 3, preferred) is True


# ── Terminology: TerminologyChecker ──────────────────────────

class TestTerminologyChecker:
    """验证术语检查器的加载、匹配和跳过逻辑"""

    def test_check_skips_already_preferred(self, tmp_path):
        """含推荐写法的文档 → 不产生误报"""
        glossary_file = tmp_path / "test_glossary.yaml"
        glossary_file.write_text("""
category: 测试
version: '1.0'
terms:
  - pattern: '(?i)through.silicon.via'
    preferred: 'TSV (Through Silicon Via, 硅通孔)'
    context: 硅通孔技术
    severity: error
""", encoding="utf-8")

        checker = TerminologyChecker()
        checker.load_glossaries(str(tmp_path))
        # 文档已正确使用 TSV 缩写
        findings = checker.check("使用 TSV (Through Silicon Via, 硅通孔) 技术", 0, "第1页")
        assert len(findings) == 0, f"Expected 0 findings, got: {findings}"

    def test_check_flags_unpreferred(self, tmp_path):
        """文档未使用推荐写法 → 产生 findings"""
        glossary_file = tmp_path / "test_glossary.yaml"
        glossary_file.write_text("""
category: 测试
version: '1.0'
terms:
  - pattern: '(?i)through.silicon.via'
    preferred: 'TSV (Through Silicon Via, 硅通孔)'
    context: 硅通孔技术
    severity: warning
""", encoding="utf-8")

        checker = TerminologyChecker()
        checker.load_glossaries(str(tmp_path))
        # 文档使用原始英文但未附 TSV 缩写 → 应产生 1 个 finding
        findings = checker.check("Through Silicon Via 是关键技术", 0, "第1页")
        assert len(findings) == 1, (
            f"Expected exactly 1 finding for non-preferred term, got {len(findings)}: {findings}"
        )
        assert "Through Silicon Via" in findings[0].context
        assert findings[0].suggestion
        assert findings[0].type.value == "terminology"

    def test_load_broken_yaml_graceful(self, tmp_path):
        """损坏的 YAML → 不崩溃，记录 warning"""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("not: valid: yaml: [", encoding="utf-8")
        checker = TerminologyChecker()
        checker.load_glossaries(str(tmp_path))  # 不应 raise
        assert len(checker.glossaries) == 0

    def test_termrule_compilation_failure(self):
        """无效正则 → compiled=None, check 时静默跳过"""
        rule = TermRule(pattern="[invalid", preferred="test")
        assert rule.compiled is None
        checker = TerminologyChecker()
        checker.glossaries = [TermGlossary(category="test", version="1", terms=[rule])]
        findings = checker.check("any text", 0, "第1页")
        assert len(findings) == 0


# ── Vocabulary: _has_regex_chars ─────────────────────────────

class TestHasRegexChars:
    def test_literal_word(self):
        assert _has_regex_chars("flip-chip") is False
        assert _has_regex_chars("kind of") is False

    def test_regex_word(self):
        assert _has_regex_chars("flip-chip(?!.*bump)") is True
        assert _has_regex_chars(r"wire-bond(?!.*ing)") is True

    def test_empty(self):
        assert _has_regex_chars("") is False


# ── Vocabulary: Vocabulary ───────────────────────────────────

class TestVocabulary:
    def test_load_accept_and_reject(self, tmp_path):
        """加载 accept.txt 和 reject.txt"""
        accept_file = tmp_path / "accept.txt"
        accept_file.write_text("FinFET\nTSV\n", encoding="utf-8")
        reject_file = tmp_path / "reject.txt"
        reject_file.write_text("kind of # informal\nsort of\n", encoding="utf-8")

        vocab = Vocabulary(str(tmp_path))
        assert vocab.is_accepted("FinFET") is True
        assert vocab.is_accepted("finfet") is True  # case-insensitive

        hits = vocab.should_reject("this is a kind of test")
        assert len(hits) == 1
        assert hits[0][0] == "kind of"

    def test_reject_regex_pattern(self, tmp_path):
        """正则条目 (含特殊字符) → 使用 regex 匹配"""
        reject_file = tmp_path / "reject.txt"
        reject_file.write_text("flip-chip(?!.*bump) # 需要附带 bump\n", encoding="utf-8")

        vocab = Vocabulary(str(tmp_path))
        # "flip-chip" alone → should match exactly once
        hits = vocab.should_reject("we use flip-chip technology")
        assert len(hits) == 1, (
            f"Regex reject should match 'flip-chip' exactly once, got {len(hits)}: {hits}"
        )

    def test_reject_literal_boundary(self, tmp_path):
        """纯单词条目 → 单词边界匹配，避免子串误报"""
        reject_file = tmp_path / "reject.txt"
        reject_file.write_text("NA  # avoid standalone NA\n", encoding="utf-8")

        vocab = Vocabulary(str(tmp_path))
        # "NA" alone → 应匹配 (exactly 1 hit)
        hits = vocab.should_reject("the NA is 0.33")
        assert len(hits) == 1, f"Expected 1 hit for standalone 'NA', got {len(hits)}: {hits}"
        # "NANO" → 不应匹配 (NA 是子串但不在单词边界)
        hits2 = vocab.should_reject("NANO technology")
        assert len(hits2) == 0, f"'NA' should not match inside 'NANO', got {hits2}"

    def test_comment_lines_skipped(self, tmp_path):
        """# 开头的注释行 → 跳过"""
        reject_file = tmp_path / "reject.txt"
        reject_file.write_text("# this is a comment\nactual word\n", encoding="utf-8")
        vocab = Vocabulary(str(tmp_path))
        hits = vocab.should_reject("# this is a comment")
        assert len(hits) == 0  # comment line was skipped

    def test_filter_accepted(self, tmp_path):
        """filter_accepted 返回白名单中的词"""
        accept_file = tmp_path / "accept.txt"
        accept_file.write_text("FinFET\nTSV\n", encoding="utf-8")
        vocab = Vocabulary(str(tmp_path))
        result = vocab.filter_accepted({"FinFET", "badword", "TSV", "other"})
        assert result == {"FinFET", "TSV"}


# ── LanguageAuditor: CJK segmentation ────────────────────────

class TestLanguageSegmentation:
    """验证 _segment_by_language 的中英混合分段逻辑"""

    def test_pure_chinese(self):
        auditor = LanguageAuditor()
        segments = auditor._segment_by_language("这是纯中文文本")
        assert len(segments) > 0
        assert all(lang == "zh" for _, lang in segments)

    def test_pure_english(self):
        auditor = LanguageAuditor()
        segments = auditor._segment_by_language("This is pure English text")
        assert len(segments) > 0
        assert all(lang == "en" for _, lang in segments)

    def test_mixed_cjk_latin(self):
        """中英混合 → 正确分段，不交叉"""
        auditor = LanguageAuditor()
        segments = auditor._segment_by_language("当前工艺 node 为 5nm FinFET 技术")
        # 应产生合理的分段，短段不会错误合并
        languages = [lang for _, lang in segments]
        assert "zh" in languages
        assert "en" in languages

    def test_short_english_between_chinese(self):
        """短英文段 ('5nm') 在两个中文段之间 → 分段正确"""
        auditor = LanguageAuditor()
        segments = auditor._segment_by_language("工艺 5nm 技术已量产")
        # 验证存在 en 段
        en_segments = [t for t, lang in segments if lang == "en"]
        assert len(en_segments) > 0, f"Short English '5nm' should be in an 'en' segment, got: {segments}"
