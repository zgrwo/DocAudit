"""测试规则解析器"""

from src.auditors.custom_rules import CustomRulesAuditor
from src.engines.pipeline import SKIP_TO_CHECK_TYPE
from src.engines.rule_parser import extract_auditor_config, parse_rules_md
from src.models.document import Document, DocumentMetadata, Page, PageElement, Paragraph


def _md_doc(text: str) -> Document:
    """构造单页纯文本文档。"""
    page = Page(index=0, slide_number=1, elements=[
        PageElement(type="text_frame", paragraphs=[Paragraph(text=text, runs=[])])
    ])
    return Document(format="md", source_path="x", metadata=DocumentMetadata(), pages=[page])

# StructureAuditor/FactualAuditor 的 _skip_checks 简写 → _DISPATCH check_type 反向映射
# 单一真相来源: src/engines/pipeline.py:SKIP_TO_CHECK_TYPE (其余键名与 check_type 一致)


class TestRuleParser:
    def test_parse_rules_md(self):
        rules = parse_rules_md("rules.md")
        assert len(rules) >= 10

    def test_extract_auditor_config(self):
        rules = parse_rules_md("rules.md")
        config = extract_auditor_config(rules)
        assert "allowed_fonts" in config
        assert "body_size_range" in config
        assert "conclusion_keywords" in config
        assert isinstance(config["body_size_range"], tuple)
        assert config["body_size_range"][0] >= 10  # min 字号

    def test_rule_ids_unique(self):
        rules = parse_rules_md("rules.md")
        ids = [r.rule_id for r in rules]
        assert len(ids) == len(set(ids)), f"Duplicate rule IDs: {ids}"

    def test_str004_config_extraction(self):
        """STR-004 配置从 rules.md 正确提取"""
        rules = parse_rules_md("rules.md")
        config = extract_auditor_config(rules)
        assert config.get("max_english_words") == 10, (
            f"Expected max_english_words=10, got {config.get('max_english_words')}"
        )
        assert config.get("max_chinese_chars_title") == 40, (
            f"Expected max_chinese_chars_title=40, got {config.get('max_chinese_chars_title')}"
        )

    def test_str004_defaults_when_not_in_rules(self):
        """无 STR-004 规则的 rules.md → 使用默认值"""
        config = extract_auditor_config([])  # 空规则列表
        assert config["max_english_words"] == 10
        assert config["max_chinese_chars_title"] == 40

    def test_str001_min_title_font_size_extraction(self):
        """STR-001 最小标题字号 从 rules.md 提取 (配置驱动: 曾三处硬编码 28)"""
        rules = parse_rules_md("rules.md")
        config = extract_auditor_config(rules)
        assert config.get("min_title_font_size") == 28, (
            f"Expected min_title_font_size=28, got {config.get('min_title_font_size')}"
        )

    def test_str001_malformed_min_title_font_size_falls_back(self):
        """STR-001 非整数配置值 → 回退默认值，不崩溃"""
        from src.engines.rule_parser import AuditRule
        rule = AuditRule(
            rule_id="STR-001",
            category="structure",
            severity="error",
            description="必须有标题页",
            check_type="first_slide_has_title_layout",
            params={"最小标题字号": "not_a_number"},
        )
        config = extract_auditor_config([rule])
        assert config["min_title_font_size"] == 28

    def test_fmt008_config_extraction(self):
        """FMT-008 对比度阈值从 rules.md 正确提取 (配置驱动)"""
        rules = parse_rules_md("rules.md")
        config = extract_auditor_config(rules)
        assert config.get("min_contrast") == 4.5, (
            f"Expected min_contrast=4.5, got {config.get('min_contrast')}"
        )
        assert config.get("large_text_min_contrast") == 3.0
        assert config.get("large_text_threshold") == 18

    def test_fmt008_malformed_contrast_falls_back(self):
        """FMT-008 非数值配置值 → 回退默认值，不崩溃"""
        from src.engines.rule_parser import AuditRule
        rule = AuditRule(
            rule_id="FMT-008",
            category="format",
            severity="warning",
            description="表格文字与底色对比度",
            check_type="table_contrast",
            params={"最小对比度": "abc", "大字最小对比度": "xyz"},
        )
        config = extract_auditor_config([rule])
        assert config["min_contrast"] == 4.5
        assert config["large_text_min_contrast"] == 3.0

    def test_str004_malformed_int_falls_back_to_default(self):
        """STR-004 非整数配置值 → 回退到默认值，不崩溃"""
        from src.engines.rule_parser import AuditRule
        rule = AuditRule(
            rule_id="STR-004",
            category="structure",
            severity="warning",
            description="标题长度",
            check_type="",
            params={"最大英文词数": "not_a_number", "最大中文字数": "abc"},
        )
        config = extract_auditor_config([rule])
        # 应回退到默认值
        assert config["max_english_words"] == 10
        assert config["max_chinese_chars_title"] == 40

    def test_term003_skipped_on_pure_english_pages(self):
        """TERM-003: 纯英文页不检查中英混排 (曾对每个英文词报 INFO 洪水)"""
        auditor = CustomRulesAuditor(config={"rules_path": "rules.md"})
        auditor.load_rules()
        doc = _md_doc("This is a standard English sentence with TSV technology.")
        finds = [f for f in auditor.audit(doc) if f.rule_id == "TERM-003"]
        assert len(finds) == 0, f"纯英文页不应报 TERM-003, got {len(finds)} 条"

    def test_term003_flags_abbrev_without_translation(self):
        """TERM-003: 中英混排页中无中文翻译的英文术语仍被标记"""
        auditor = CustomRulesAuditor(config={"rules_path": "rules.md"})
        auditor.load_rules()
        doc = _md_doc("TSV 工艺用于先进封装。")
        finds = [f for f in auditor.audit(doc) if f.rule_id == "TERM-003"]
        assert len(finds) >= 1, "中英混排无翻译缩写应被标记"

    def test_term003_abbrev_with_chinese_parens_ok(self):
        """TERM-003: 已附 (中文) 翻译的术语不再标记"""
        auditor = CustomRulesAuditor(config={"rules_path": "rules.md"})
        auditor.load_rules()
        doc = _md_doc("TSV (硅通孔) 工艺用于先进封装。")
        finds = [f for f in auditor.audit(doc) if f.rule_id == "TERM-003"]
        assert len(finds) == 0, f"已附翻译不应报 TERM-003, got: {finds}"

    def test_term003_lowercase_function_words_skipped(self):
        """TERM-003: 中英混排页中的全小写功能词不标记 (仅术语特征)"""
        auditor = CustomRulesAuditor(config={"rules_path": "rules.md"})
        auditor.load_rules()
        doc = _md_doc("我们使用 standard 工艺，这是 a 测试。")
        finds = [f for f in auditor.audit(doc) if f.rule_id == "TERM-003"]
        assert len(finds) == 0, f"全小写功能词不应报 TERM-003, got: {finds}"

    def test_dispatch_exception_becomes_sys_error_finding(self, monkeypatch):
        """回归: 单条规则执行异常不再静默吞掉, 转为 SYS-ERROR finding (UI 可见)"""
        from src.auditors.format import FormatAuditor

        def boom(self, page, doc):
            raise RuntimeError("模拟 dispatch 方法崩溃")

        monkeypatch.setattr(FormatAuditor, "_check_bullet_consistency", boom)
        auditor = CustomRulesAuditor(config={"rules_path": "rules.md"})
        auditor.load_rules()
        findings = auditor.audit(_md_doc("bullet 测试"))
        sys_errors = [f for f in findings if f.rule_id == "SYS-ERROR"]
        assert len(sys_errors) >= 1, "规则执行异常应产生 SYS-ERROR finding"
        assert "bullet_consistency" in (sys_errors[0].metadata or {}).get("rule_id", "") or \
            "模拟 dispatch" in sys_errors[0].message


class TestDispatchValidation:
    def test_all_dispatch_entries_valid(self):
        """_DISPATCH 表中所有条目对应的方法存在于审计器类上"""
        errors = CustomRulesAuditor.validate_dispatch()
        assert len(errors) == 0, f"Dispatch validation errors: {errors}"

    def test_skip_checks_standalone_mode(self):
        """独立模式（无 _skip_checks 参数）→ 所有检查执行"""
        from src.auditors.structure import StructureAuditor
        sa = StructureAuditor(config={"required_sections": []})
        assert sa._skip_checks == set()

    def test_skip_checks_pipeline_mode(self):
        """流水线模式 → _skip_checks 包含 dispatched 检查"""
        from src.auditors.structure import StructureAuditor
        sa = StructureAuditor(config={
            "required_sections": [],
            "_skip_checks": ["title_slide", "heading_levels"],
        })
        assert "title_slide" in sa._skip_checks
        assert "heading_levels" in sa._skip_checks

    def test_every_dispatch_check_type_declared_in_rules_md(self):
        """守卫: _DISPATCH 每个 check_type 必须在 rules.md 中声明。

        防止 STR-004 式静默失效: 检查被 _skip_checks 跳过，
        但 rules.md 未声明对应 check_type 导致 dispatch 也不执行。
        """
        rules = parse_rules_md("rules.md")
        declared = {r.check_type for r in rules if r.check_type}
        missing = [
            ct for ct in CustomRulesAuditor._DISPATCH
            if ct not in declared
        ]
        assert not missing, (
            f"以下 check_type 在 _DISPATCH 中但 rules.md 未声明 (规则静默失效风险): {missing}"
        )

    def test_skip_checks_covered_by_rules_md_declaration(self):
        """守卫: build_auditors 的每个 _skip_checks 键必须对应 rules.md 中已声明的 dispatch 规则。

        若某检查被跳过但无 dispatch 规则驱动 → 该检查在流水线中永不执行。
        """
        from src.engines.pipeline import build_auditors

        rules = parse_rules_md("rules.md")
        declared = {r.check_type for r in rules if r.check_type}

        auditors = build_auditors("rules.md", "glossary", "vocab")
        for _name, auditor in auditors:
            skip_keys = getattr(auditor, "_skip_checks", set())
            for key in skip_keys:
                check_type = SKIP_TO_CHECK_TYPE.get(key, key)
                assert check_type in CustomRulesAuditor._DISPATCH, (
                    f"{type(auditor).__name__}._skip_checks 键 '{key}' 映射的 "
                    f"check_type '{check_type}' 不在 _DISPATCH 中 → 检查静默失效"
                )
                assert check_type in declared, (
                    f"{type(auditor).__name__}._skip_checks 含 '{key}' "
                    f"(check_type='{check_type}')，但 rules.md 未声明 → 该检查永不执行"
                )

    def test_str004_fires_through_pipeline(self):
        """回归测试 (P0): STR-004 必须经完整流水线产生发现。

        复现场景: 45 字中文标题 → 审查后必须含 STR-004 finding。
        """
        from src.engines.pipeline import build_auditors, run_auditors
        from src.models.document import Document, DocumentMetadata, Page, PageElement, Paragraph

        long_title = "这是一个非常非常长的中文标题用来测试标题长度限制规则是否会正常触发告警超过四十个字"
        doc = Document(
            source_path="str004_repro.pptx",
            format="pptx",
            metadata=DocumentMetadata(),
            pages=[Page(
                index=0,
                slide_number=1,
                elements=[PageElement(
                    type="text_frame",
                    is_title=True,
                    paragraphs=[Paragraph(text=long_title, runs=[])],
                )],
            )],
        )
        auditors = build_auditors("rules.md", "glossary", "vocab")
        findings = run_auditors(doc, auditors)
        str004 = [f for f in findings if f.rule_id == "STR-004"]
        assert str004, "流水线未产生 STR-004 发现 — 标题长度检查静默失效"
