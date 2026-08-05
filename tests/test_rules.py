"""测试规则解析器"""

from src.auditors.custom_rules import CustomRulesAuditor
from src.engines.rule_parser import extract_auditor_config, parse_rules_md


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
