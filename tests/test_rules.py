"""测试规则解析器"""

from pathlib import Path

from src.auditors.custom_rules import CustomRulesAuditor
from src.engines.pipeline import SKIP_TO_CHECK_TYPE
from src.engines.rule_parser import extract_auditor_config, parse_rules_md
from src.models.document import Document, DocumentMetadata, Page, PageElement, Paragraph

# 绝对路径锚点 — 不依赖 CWD (2026-08 审查 L16: 曾用相对 "rules.md"/"glossary")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULES_MD = str(PROJECT_ROOT / "rules.md")
GLOSSARY_DIR = str(PROJECT_ROOT / "glossary")
VOCAB_DIR = str(PROJECT_ROOT / "vocab")


def _md_doc(text: str) -> Document:
    """构造单页纯文本文档。"""
    page = Page(
        index=0,
        slide_number=1,
        elements=[PageElement(type="text_frame", paragraphs=[Paragraph(text=text, runs=[])])],
    )
    return Document(format="md", source_path="x", metadata=DocumentMetadata(), pages=[page])


# StructureAuditor/FactualAuditor 的 _skip_checks 简写 → _DISPATCH check_type 反向映射
# 单一真相来源: src/engines/pipeline.py:SKIP_TO_CHECK_TYPE (其余键名与 check_type 一致)


class TestRuleParser:
    def test_parse_rules_md(self):
        rules = parse_rules_md(RULES_MD)
        # 精确锚定 (2026-09-06 审查 G-1): 宽松下限 (>=10) 拦不住规则数缓慢缩减;
        # 规则数变更需同步 rules.md / api-reference.md / ci.yml 断言 / 白名单文档
        assert len(rules) == 30

    def test_extract_auditor_config(self):
        rules = parse_rules_md(RULES_MD)
        config = extract_auditor_config(rules)
        assert "allowed_fonts" in config
        assert "body_size_range" in config
        assert "conclusion_keywords" in config
        assert isinstance(config["body_size_range"], tuple)
        assert config["body_size_range"][0] >= 10  # min 字号
        # 2026-10-29: 默认上限对齐 Office 主题 (标题 44 / 正文 32)
        assert config["title_size_range"] == (28, 44)
        assert config["body_size_range"] == (12, 32)

    def test_rule_ids_unique(self):
        rules = parse_rules_md(RULES_MD)
        ids = [r.rule_id for r in rules]
        assert len(ids) == len(set(ids)), f"Duplicate rule IDs: {ids}"

    def test_str004_config_extraction(self):
        """STR-004 配置从 rules.md 正确提取"""
        rules = parse_rules_md(RULES_MD)
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
        rules = parse_rules_md(RULES_MD)
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

    def test_languagetool_url_extracted_from_rules(self):
        """languagetool_url 接线: 任一规则 params 含该键 → extract_auditor_config 注入"""
        from src.engines.rule_parser import AuditRule

        rule = AuditRule(
            rule_id="CON-001",
            category="content",
            severity="error",
            description="数值一致性",
            check_type="numeric_cross_reference",
            params={"languagetool_url": "http://localhost:8011/v2"},
        )
        config = extract_auditor_config([rule])
        assert config.get("languagetool_url") == "http://localhost:8011/v2"

    def test_languagetool_url_absent_when_not_declared(self):
        """无 languagetool_url 声明 → config 不含该键 (build_auditors 不注入)"""
        config = extract_auditor_config([])
        assert "languagetool_url" not in config

    def test_exempt_layouts_default_when_rules_not_declared(self, tmp_path):
        """build_auditors: rules.md 未声明 豁免版式 → 结构审查器使用内置默认 (修复: 曾传 [] 覆盖)"""
        from src.engines.pipeline import build_auditors

        rules_file = tmp_path / "rules.md"
        rules_file.write_text(
            "# 内容规则\n\n"
            "## CON-001: 数值一致性\n"
            "- 严重度: error\n"
            "- 检查: numeric_cross_reference\n",
            encoding="utf-8",
        )
        glossary = tmp_path / "glossary"
        glossary.mkdir(exist_ok=True)
        auditors = build_auditors(str(rules_file), str(glossary))
        structure_auditor = next(a for n, a in auditors if n == "结构审查")
        assert structure_auditor.exempt_layouts, "未声明时应使用内置默认豁免版式"
        assert "标题幻灯片" in structure_auditor.exempt_layouts

    def test_languagetool_url_wired_through_build_auditors(self, tmp_path):
        """build_auditors: rules 声明 languagetool_url → LanguageAuditor 配置生效"""
        from src.engines.pipeline import build_auditors

        rules_file = tmp_path / "rules.md"
        rules_file.write_text(
            "# 内容规则\n\n"
            "## CON-001: 数值一致性\n"
            "- 严重度: error\n"
            "- 检查: numeric_cross_reference\n"
            "- languagetool_url: http://localhost:8011/v2\n",
            encoding="utf-8",
        )
        glossary = tmp_path / "glossary"
        glossary.mkdir(exist_ok=True)
        auditors = build_auditors(str(rules_file), str(glossary))
        language_auditor = next(a for n, a in auditors if n == "语言审查")
        # localhost 在客户端内归一为 127.0.0.1（避免 Windows IPv6 白等 ~2s，2026-10-29）
        assert language_auditor.lt_client.base_url == "http://127.0.0.1:8011/v2"

    def test_languagetool_url_external_blocked_by_whitelist(self, tmp_path):
        """白名单拦截: rules 声明外部 languagetool_url → build_auditors 抛 ValueError"""
        import pytest

        from src.engines.pipeline import build_auditors

        rules_file = tmp_path / "rules.md"
        rules_file.write_text(
            "# 内容规则\n\n"
            "## CON-001: 数值一致性\n"
            "- 严重度: error\n"
            "- 检查: numeric_cross_reference\n"
            "- languagetool_url: http://evil.example.com/v2\n",
            encoding="utf-8",
        )
        glossary = tmp_path / "glossary"
        glossary.mkdir(exist_ok=True)
        with pytest.raises(ValueError):
            build_auditors(str(rules_file), str(glossary))

    def test_fmt008_config_extraction(self):
        """FMT-008 对比度阈值从 rules.md 正确提取 (配置驱动)"""
        rules = parse_rules_md(RULES_MD)
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
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        doc = _md_doc("This is a standard English sentence with TSV technology.")
        finds = [f for f in auditor.audit(doc) if f.rule_id == "TERM-003"]
        assert len(finds) == 0, f"纯英文页不应报 TERM-003, got {len(finds)} 条"

    def test_term003_flags_abbrev_without_translation(self):
        """TERM-003: 中英混排页中无中文翻译的英文术语仍被标记"""
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        doc = _md_doc("TSV 工艺用于先进封装。")
        finds = [f for f in auditor.audit(doc) if f.rule_id == "TERM-003"]
        assert len(finds) >= 1, "中英混排无翻译缩写应被标记"

    def test_term003_abbrev_with_chinese_parens_ok(self):
        """TERM-003: 已附 (中文) 翻译的术语不再标记"""
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        doc = _md_doc("TSV (硅通孔) 工艺用于先进封装。")
        finds = [f for f in auditor.audit(doc) if f.rule_id == "TERM-003"]
        assert len(finds) == 0, f"已附翻译不应报 TERM-003, got: {finds}"

    def test_term003_ordinary_capitalized_words_not_flagged(self):
        """TERM-003: 普通首字母大写英文词 (Yield/Node/Analysis) 不是技术缩写。"""
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        doc = _md_doc("Yield Analysis 与 Node Comparison 数据。")
        finds = [f for f in auditor.audit(doc) if f.rule_id == "TERM-003"]
        assert len(finds) == 0, f"普通英文词不应报 TERM-003, got: {finds}"

    def test_term003_definition_suppresses_later_use(self):
        """TERM-003: 首次出现已附中文定义，后续复用不应再报未翻译。"""
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        doc = _md_doc("TSV (硅通孔) 工艺。TSV 用于先进封装。")
        finds = [f for f in auditor.audit(doc) if f.rule_id == "TERM-003"]
        assert finds == [], f"已定义缩写的后续复用不应报 TERM-003, got: {finds}"

    def test_term003_reports_only_first_occurrence(self):
        """TERM-003: 同一缩写全文档只报首次出现，避免每页重复。"""
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        doc = _md_doc("TSV 工艺用于先进封装。TSV 设备也需要检查。")
        finds = [f for f in auditor.audit(doc) if f.rule_id == "TERM-003"]
        assert len(finds) == 1, f"同一缩写应只报一次, got: {finds}"

    def test_term003_accept_whitelist_skipped(self):
        """TERM-003: vocab/accept.txt 已认可缩写 (FOWLP) 不再报未翻译。"""
        from pathlib import Path as _Path

        auditor = CustomRulesAuditor(
            config={
                "rules_path": RULES_MD,
                "vocab_dir": str(_Path(RULES_MD).parent / "vocab"),
            }
        )
        auditor.load_rules()
        doc = _md_doc("FOWLP 工艺用于先进封装。")
        finds = [f for f in auditor.audit(doc) if f.rule_id == "TERM-003"]
        assert len(finds) == 0, f"白名单缩写不应报 TERM-003, got: {finds}"

    def test_term003_lowercase_function_words_skipped(self):
        """TERM-003: 中英混排页中的全小写功能词不标记 (仅术语特征)"""
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        doc = _md_doc("我们使用 standard 工艺，这是 a 测试。")
        finds = [f for f in auditor.audit(doc) if f.rule_id == "TERM-003"]
        assert len(finds) == 0, f"全小写功能词不应报 TERM-003, got: {finds}"

    def test_term003_words_inside_parens_definition_skipped(self):
        """TERM-003: 括号内的全称定义词不标记 (CON-003 推荐格式 'TSV (Through Silicon Via)' 不误报)"""
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        doc = _md_doc("TSV (Through Silicon Via) 工艺用于先进封装。")
        finds = [f for f in auditor.audit(doc) if f.rule_id == "TERM-003"]
        assert len(finds) == 0, f"括号内全称词不应报 TERM-003, got: {finds}"

    def test_term003_alphanumeric_compound_not_flagged(self):
        """TERM-003: 字母数字复合词前缀不误报 ('CDMA2000' 不报 'CDMA', 'TSVstack' 不报 'TSV')"""
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        doc = _md_doc("CDMA2000 与 TSVstack 技术对比。")
        finds = [f for f in auditor.audit(doc) if f.rule_id == "TERM-003"]
        assert len(finds) == 0, f"复合词前缀不应报 TERM-003, got: {finds}"

    def test_unknown_check_type_becomes_sys_error(self):
        """回归: 未知 check_type 不再静默跳过, 转 SYS-ERROR finding (拼写错误 UI 可见)"""
        from src.engines.rule_parser import AuditRule

        rule = AuditRule(
            rule_id="FMT-999",
            category="format",
            severity="warning",
            description="测试规则",
            check_type="table_contras",  # 拼写错误
            params={},
        )
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        findings = auditor._execute_rule(rule, _md_doc("测试"))
        sys_errors = [f for f in findings if f.rule_id == "SYS-ERROR"]
        assert len(sys_errors) == 1, f"未知 check_type 应产生 SYS-ERROR, got: {findings}"
        assert "table_contras" in sys_errors[0].message

    def test_invalid_regex_becomes_sys_error(self):
        """回归: 无效正则不再静默返回空, 转 SYS-ERROR 保证配置错误可见。"""
        from src.engines.rule_parser import AuditRule

        rule = AuditRule(
            rule_id="TERM-999",
            category="terminology",
            severity="warning",
            description="测试非法正则",
            check_type="regex",
            params={"pattern": "["},
        )
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        findings = auditor._execute_rule(rule, _md_doc("测试"))
        sys_errors = [f for f in findings if f.rule_id == "SYS-ERROR"]
        assert len(sys_errors) == 1, f"无效正则应产生 SYS-ERROR, got: {findings}"
        assert "TERM-999" in sys_errors[0].message

    def test_pptx_only_dispatch_skips_docx_page_char_limit(self):
        """FMT-003 是幻灯片语义；DOCX 经 dispatch 也必须跳过。"""
        from src.engines.rule_parser import AuditRule

        rule = AuditRule(
            rule_id="FMT-003",
            category="format",
            severity="warning",
            description="每页文本量",
            check_type="per_page_char_limit",
            params={},
        )
        doc = _md_doc("测" * 300)
        doc.format = "docx"
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        findings = auditor._execute_rule(rule, doc)
        assert [f for f in findings if f.rule_id == "FMT-003"] == []

    def test_heading_levels_dispatch_skipped_for_pptx(self):
        """STR-003: PPTX 文档不报标题层级跳级 (para.level 是缩进级别, 方法内守卫早退)"""
        from src.engines.rule_parser import AuditRule

        rule = AuditRule(
            rule_id="STR-003",
            category="structure",
            severity="warning",
            description="标题层级不跳级",
            check_type="heading_level_sequential",
            params={},
        )
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        page = Page(
            index=0,
            slide_number=1,
            elements=[
                PageElement(
                    type="text_frame",
                    paragraphs=[
                        Paragraph(text="a", runs=[], level=0),
                        Paragraph(text="b", runs=[], level=2),
                    ],
                )
            ],
        )
        doc = Document(
            format="pptx", source_path="x.pptx", metadata=DocumentMetadata(), pages=[page]
        )
        findings = auditor._execute_rule(rule, doc)
        str003 = [f for f in findings if f.rule_id == "STR-003"]
        assert len(str003) == 0, f"PPTX 缩进级别不应报 STR-003, got: {str003}"

    def test_str003_fires_through_dispatch_for_non_pptx(self):
        """回归 2026-09-06: 非 PPTX 文档必须能经 dispatch 触发 STR-003。

        _skip_checks 屏蔽 audit() 直调路径后, dispatch 是 STR-003 唯一执行通道;
        曾因 pptx_only=True 被整体跳过, 而方法自身又在 PPTX 早退 → 规则静默失效。
        """
        from src.engines.rule_parser import AuditRule

        rule = AuditRule(
            rule_id="STR-003",
            category="structure",
            severity="warning",
            description="标题层级不跳级",
            check_type="heading_level_sequential",
            params={},
        )
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        page = Page(
            index=0,
            slide_number=1,
            elements=[
                PageElement(
                    type="text_frame",
                    paragraphs=[
                        Paragraph(text="一级标题", runs=[], level=0),
                        Paragraph(text="三级标题", runs=[], level=2),
                    ],
                )
            ],
        )
        doc = Document(
            format="docx", source_path="x.docx", metadata=DocumentMetadata(), pages=[page]
        )
        findings = auditor._execute_rule(rule, doc)
        str003 = [f for f in findings if f.rule_id == "STR-003"]
        assert len(str003) == 1, f"非 PPTX 跳级 (H0→H2) 应报 STR-003, got: {str003}"

    def test_con004_dispatch_skipped_for_non_pptx(self):
        """CON-004 dispatch: 非 PPTX 文档不执行每页结论检查 (pptx_only 修复)"""
        from src.engines.rule_parser import AuditRule

        rule = AuditRule(
            rule_id="CON-004",
            category="content",
            severity="error",
            description="每页须有结论",
            check_type="every_slide_has_conclusion",
            params={},
        )
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        findings = auditor._execute_rule(
            rule, _md_doc("这是第一段普通正文，第二段补充说明，第三段技术描述。")
        )
        con004 = [f for f in findings if f.rule_id == "CON-004"]
        assert len(con004) == 0, f"非 PPTX 文档不应 dispatch CON-004, got: {con004}"

    def test_only_chinese_page_false_string_not_truthy(self):
        """回归: 仅中文页面='false' (字符串) 不得误开启过滤器"""
        from src.engines.rule_parser import AuditRule

        rule = AuditRule(
            rule_id="TERM-999",
            category="terminology",
            severity="info",
            description="测试",
            check_type="",
            params={"pattern": r"[A-Z]{2,8}", "仅中文页面": "false"},
        )
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        doc = _md_doc("THIS IS ENGLISH ONLY")
        findings = [f for f in auditor._execute_rule(rule, doc) if f.rule_id == "TERM-999"]
        assert len(findings) >= 1, f"'false' 不应开启仅中文页面过滤, got: {findings}"

    def test_dispatch_exception_becomes_sys_error_finding(self, monkeypatch):
        """回归: 单条规则执行异常不再静默吞掉, 转为 SYS-ERROR finding (UI 可见)"""
        from src.auditors.format import FormatAuditor

        def boom(self, page, doc):
            raise RuntimeError("模拟 dispatch 方法崩溃")

        monkeypatch.setattr(FormatAuditor, "_check_bullet_consistency", boom)
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        findings = auditor.audit(_md_doc("bullet 测试"))
        sys_errors = [f for f in findings if f.rule_id == "SYS-ERROR"]
        assert len(sys_errors) >= 1, "规则执行异常应产生 SYS-ERROR finding"
        # 2026-11 审查: 旧断言用 `or "模拟 dispatch" in message` —— 后半支恒真
        # (异常文本必然拼进 message)，前半支拿 check_type 比 rule_id 恒假，整体零约束。
        # 现锚定失败规则的 rule_id (FMT-007) 与异常文本两侧。
        assert (sys_errors[0].metadata or {}).get("rule_id") == "FMT-007", (
            f"SYS-ERROR 应记录失败规则 ID, got: {(sys_errors[0].metadata or {}).get('rule_id')}"
        )
        assert "模拟 dispatch" in sys_errors[0].message

    def test_multiple_sys_errors_not_deduped(self, monkeypatch):
        """回归: 多条规则同时失败时 SYS-ERROR 不得被 deduplicate 折叠为一条"""
        from src.auditors.factual import FactualAuditor
        from src.auditors.format import FormatAuditor
        from src.models.finding import AuditFinding

        def boom_fmt(self, page, doc):
            raise RuntimeError("FMT 崩溃")

        def boom_fca(self, doc):
            raise RuntimeError("FCA 崩溃")

        monkeypatch.setattr(FormatAuditor, "_check_bullet_consistency", boom_fmt)
        monkeypatch.setattr(FactualAuditor, "_check_numeric_consistency", boom_fca)
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        findings = AuditFinding.deduplicate(auditor.audit(_md_doc("测试")))
        sys_errors = [f for f in findings if f.rule_id == "SYS-ERROR"]
        assert len(sys_errors) == 2, (
            f"两条规则失败应保留 2 条 SYS-ERROR, 实际 {len(sys_errors)}: {sys_errors}"
        )
        msgs = " | ".join(f.message for f in sys_errors)
        assert "FMT 崩溃" in msgs and "FCA 崩溃" in msgs, f"两条失败信息都应保留: {msgs}"

    def test_sys_errors_same_exception_text_not_deduped(self, monkeypatch):
        """回归: 两条不同规则抛出逐字节相同异常文本时, SYS-ERROR 不得折叠为一条
        (2026-09-06 四轮审查 N-3: 上方用例用不同异常文本, 旧代码本就能区分,
        拦不住同文本折叠; 本用例锚定 context 前缀带 rule_id 的修复)。"""
        from src.auditors.factual import FactualAuditor
        from src.auditors.format import FormatAuditor
        from src.models.finding import AuditFinding

        def boom_same(self, *args, **kwargs):
            raise RuntimeError("IDENTICAL-BOOM")

        monkeypatch.setattr(FormatAuditor, "_check_bullet_consistency", boom_same)
        monkeypatch.setattr(FactualAuditor, "_check_numeric_consistency", boom_same)
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        findings = AuditFinding.deduplicate(auditor.audit(_md_doc("测试")))
        sys_errors = [f for f in findings if f.rule_id == "SYS-ERROR"]
        assert len(sys_errors) == 2, (
            f"两条规则相同异常文本应保留 2 条 SYS-ERROR, 实际 {len(sys_errors)}: {sys_errors}"
        )
        assert all("IDENTICAL-BOOM" in (f.context or "") for f in sys_errors)
        rules = {f.metadata.get("rule_id") for f in sys_errors}
        assert "FMT-007" in rules and "CON-001" in rules, f"两条 SYS-ERROR 应分属两规则: {rules}"


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

        sa = StructureAuditor(
            config={
                "required_sections": [],
                "_skip_checks": ["title_slide", "heading_levels"],
            }
        )
        assert "title_slide" in sa._skip_checks
        assert "heading_levels" in sa._skip_checks

    def test_every_dispatch_check_type_declared_in_rules_md(self):
        """守卫: _DISPATCH 每个 check_type 必须在 rules.md 中声明。

        防止 STR-004 式静默失效: 检查被 _skip_checks 跳过，
        但 rules.md 未声明对应 check_type 导致 dispatch 也不执行。
        """
        rules = parse_rules_md(RULES_MD)
        declared = {r.check_type for r in rules if r.check_type}
        missing = [ct for ct in CustomRulesAuditor._DISPATCH if ct not in declared]
        assert not missing, (
            f"以下 check_type 在 _DISPATCH 中但 rules.md 未声明 (规则静默失效风险): {missing}"
        )

    def test_skip_checks_covered_by_rules_md_declaration(self):
        """守卫: build_auditors 的每个 _skip_checks 键必须对应 rules.md 中已声明的 dispatch 规则。

        若某检查被跳过但无 dispatch 规则驱动 → 该检查在流水线中永不执行。
        """
        from src.engines.pipeline import build_auditors

        rules = parse_rules_md(RULES_MD)
        declared = {r.check_type for r in rules if r.check_type}

        auditors = build_auditors(RULES_MD, GLOSSARY_DIR, VOCAB_DIR)
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

        long_title = (
            "这是一个非常非常长的中文标题用来测试标题长度限制规则是否会正常触发告警超过四十个字"
        )
        doc = Document(
            source_path="str004_repro.pptx",
            format="pptx",
            metadata=DocumentMetadata(),
            pages=[
                Page(
                    index=0,
                    slide_number=1,
                    elements=[
                        PageElement(
                            type="text_frame",
                            is_title=True,
                            paragraphs=[Paragraph(text=long_title, runs=[])],
                        )
                    ],
                )
            ],
        )
        auditors = build_auditors(RULES_MD, GLOSSARY_DIR, VOCAB_DIR)
        findings = run_auditors(doc, auditors)
        str004 = [f for f in findings if f.rule_id == "STR-004"]
        assert str004, "流水线未产生 STR-004 发现 — 标题长度检查静默失效"


class TestCheckRegistry:
    """2026-10-29: 规则注册表 SSOT — _DISPATCH / _skip_checks 由 CHECK_REGISTRY 派生。"""

    def test_dispatch_derived_from_registry(self):
        from src.auditors.custom_rules import CHECK_REGISTRY

        assert set(CustomRulesAuditor._DISPATCH) == set(CHECK_REGISTRY)
        for check_type, spec in CHECK_REGISTRY.items():
            assert CustomRulesAuditor._DISPATCH[check_type] == (
                spec.auditor,
                spec.method,
                spec.per_page,
                spec.pptx_only,
            )

    def test_skip_checks_cover_each_auditor(self):
        from src.auditors.custom_rules import CHECK_REGISTRY

        for key in ("sa", "fa", "fca"):
            expected = [
                spec.skip_key or ct for ct, spec in CHECK_REGISTRY.items() if spec.auditor == key
            ]
            assert CustomRulesAuditor.skip_checks_for(key) == expected
            assert expected, f"{key} 应有注册的检查"

    def test_skip_keys_unique_per_auditor(self):
        """同一 Auditor 内 skip_key 不得重复，否则一条跳过会误伤另一条检查。"""
        from collections import Counter

        from src.auditors.custom_rules import CHECK_REGISTRY

        for key in ("sa", "fa", "fca"):
            skip_keys = [
                spec.skip_key or ct for ct, spec in CHECK_REGISTRY.items() if spec.auditor == key
            ]
            assert not [k for k, n in Counter(skip_keys).items() if n > 1]

    def test_registry_auditor_keys_known(self):
        from src.auditors.custom_rules import CHECK_REGISTRY

        assert {spec.auditor for spec in CHECK_REGISTRY.values()} <= {"sa", "fa", "fca"}


class TestGlobalParameters:
    """2026-11: rules.md frontmatter `parameters:` 全局阈值（原硬编码）。"""

    @staticmethod
    def _rules_file(tmp_path: Path, parameters_yaml: str) -> Path:
        path = tmp_path / "rules.md"
        path.write_text(
            "---\n"
            'version: "1.0"\n'
            f"{parameters_yaml}\n"
            "---\n\n"
            "# 结构规则\n\n"
            "## STR-001: 必须有标题页\n"
            "- 严重度: error\n"
            "- 检查: first_slide_has_title_layout\n",
            encoding="utf-8",
        )
        return path

    def test_defaults_when_not_declared(self):
        from src.engines.rule_parser import global_param_defaults

        cfg = extract_auditor_config(parse_rules_md(RULES_MD), {})
        defaults = global_param_defaults()
        assert cfg["alignment_tolerance"] == defaults["alignment_tolerance"]
        assert cfg["max_font_types"] == defaults["max_font_types"]
        assert cfg["numeric_length_units"] == defaults["numeric_length_units"]

    def test_declared_values_override(self, tmp_path):
        from src.engines.rule_parser import parse_rules_globals

        rules_file = self._rules_file(
            tmp_path,
            "parameters:\n"
            "  alignment_tolerance: 9.5\n"
            "  max_font_types: 5\n"
            "  numeric_length_units: [nm, mm]\n"
            "  common_uppercase_extra: [ABCX]\n",
        )
        globals_ = parse_rules_globals(rules_file)
        cfg = extract_auditor_config(parse_rules_md(rules_file), globals_)
        assert cfg["alignment_tolerance"] == 9.5
        assert cfg["max_font_types"] == 5
        assert cfg["numeric_length_units"] == ["nm", "mm"]
        assert cfg["common_uppercase_extra"] == ["ABCX"]

    def test_invalid_value_falls_back_with_warning(self, tmp_path, caplog):
        from src.engines.rule_parser import parse_rules_globals

        rules_file = self._rules_file(
            tmp_path,
            "parameters:\n  alignment_tolerance: not-a-number\n  max_font_types: 999\n",
        )
        globals_ = parse_rules_globals(rules_file)
        with caplog.at_level("WARNING", logger="src.engines.rule_parser"):
            cfg = extract_auditor_config(parse_rules_md(rules_file), globals_)
        assert cfg["alignment_tolerance"] == 5.0
        assert cfg["max_font_types"] == 3
        assert any("alignment_tolerance" in r.message for r in caplog.records)

    def test_unknown_key_warns(self, tmp_path, caplog):
        from src.engines.rule_parser import parse_rules_globals

        rules_file = self._rules_file(tmp_path, "parameters:\n  not_a_param: 1\n")
        with caplog.at_level("WARNING", logger="src.engines.rule_parser"):
            extract_auditor_config(parse_rules_md(rules_file), parse_rules_globals(rules_file))
        assert any("not_a_param" in r.message for r in caplog.records)

    def test_pipeline_and_fallback_share_config_keys(self):
        """配置装配 SSOT: build_auditors 与 custom_rules 回退路径键集一致 (特检 #4)。"""
        from src.auditors.custom_rules import CustomRulesAuditor
        from src.engines.auditor_config import build_auditor_configs

        config = extract_auditor_config(parse_rules_md(RULES_MD), {})
        pipeline_cfgs = build_auditor_configs(
            config,
            enabled_rule_ids={"FMT-001"},
            skip_checks={"sa": ["x"], "fa": ["y"], "fca": ["z"]},
        )
        standalone_cfgs = build_auditor_configs(config, enabled_rule_ids={"FMT-001"})
        assert set(pipeline_cfgs) == {"sa", "fa", "la", "fca"}
        for key in ("sa", "fa", "fca"):
            assert set(pipeline_cfgs[key]) - {"_skip_checks"} == set(standalone_cfgs[key]), (
                f"{key} 键集在 pipeline 与回退路径间漂移"
            )
        # CustomRulesAuditor 回退路径实际实例化不抛错
        auditor = CustomRulesAuditor(config={"rules_path": RULES_MD})
        auditor.load_rules()
        assert auditor._create_auditor("fa") is not None

    def test_bom_frontmatter_parameters_are_loaded(self, tmp_path):
        """UTF-8 BOM 的 rules.md 不得丢掉 parameters（reaudit S7）。"""
        from src.engines.rule_parser import parse_rules_globals

        path = tmp_path / "rules.md"
        path.write_text(
            "---\n"
            'version: "1.0"\n'
            "parameters:\n"
            "  alignment_tolerance: 9.5\n"
            "---\n\n"
            "# 结构规则\n\n"
            "## STR-001: x\n- 严重度: error\n- 检查: first_slide_has_title_layout\n",
            encoding="utf-8-sig",
        )
        assert parse_rules_globals(path) == {"alignment_tolerance": 9.5}
        cfg = extract_auditor_config(parse_rules_md(path), parse_rules_globals(path))
        assert cfg["alignment_tolerance"] == 9.5
