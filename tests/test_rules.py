"""测试规则解析器"""

from src.auditors.custom_rules import CustomRulesAuditor
from src.engines.rule_parser import extract_auditor_config, parse_rules_md

# StructureAuditor/FactualAuditor 的 _skip_checks 简写 → _DISPATCH check_type 反向映射
# (与 pipeline.build_auditors 注释一致)
_SKIP_TO_CHECK_TYPE = {
    "title_slide": "first_slide_has_title_layout",
    "heading_levels": "heading_level_sequential",
    "figure_numbering": "figure_numbering_sequential",
    "every_slide_conclusion": "every_slide_has_conclusion",
    "numeric_consistency": "numeric_cross_reference",
    # 其余键名与 _DISPATCH check_type 一致
}


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
                check_type = _SKIP_TO_CHECK_TYPE.get(key, key)
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
