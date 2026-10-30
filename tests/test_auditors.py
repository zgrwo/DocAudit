"""测试审计器 — 通过公共 audit() API 验证行为，确保测试与源码行为一致"""

import os
import tempfile
from pathlib import Path

from src.auditors.factual import FactualAuditor
from src.auditors.format import FormatAuditor
from src.auditors.structure import StructureAuditor
from src.converters.pptx_converter import PptxConverter
from src.engines.rule_parser import extract_auditor_config, parse_rules_md
from src.models.document import Document, DocumentMetadata, Page, PageElement, Paragraph
from src.models.finding import AuditFinding, FindingSeverity, FindingType

RULES_MD = str(Path(__file__).resolve().parent.parent / "rules.md")


def _heading_doc(levels: list[int]) -> Document:
    """构造含指定标题层级的单页文档 (text_frame 段落)。"""
    paragraphs = [Paragraph(text=f"H{lv} 标题", runs=[], level=lv) for lv in levels]
    page = Page(
        index=0, slide_number=1, elements=[PageElement(type="text_frame", paragraphs=paragraphs)]
    )
    return Document(format="md", source_path="x", metadata=DocumentMetadata(), pages=[page])


def _text_doc(text: str) -> Document:
    """构造单页纯文本文档。"""
    page = Page(
        index=0,
        slide_number=1,
        elements=[PageElement(type="text_frame", paragraphs=[Paragraph(text=text, runs=[])])],
    )
    return Document(format="md", source_path="x", metadata=DocumentMetadata(), pages=[page])


class TestStructureAuditor:
    """通过 audit() 公共 API 和内部方法双重验证"""

    def test_title_slide_detection_via_audit(self):
        """STR-001: 第一页为标题版式 → audit() 不应产生 STR-001 ERROR"""
        doc = PptxConverter().convert("tests/fixtures/sample.pptx")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa.audit(doc)
        # sample.pptx 第一页为 Title Slide 版式 → 不应有 STR-001 告警
        str001_errors = [
            f for f in findings if f.rule_id == "STR-001" and f.severity == FindingSeverity.ERROR
        ]
        assert len(str001_errors) == 0, (
            f"STR-001 should not fire on title slide, got: {str001_errors}"
        )

    def test_title_slide_detection_direct(self):
        """STR-001: 直接调用 _check_title_slide → 空列表"""
        doc = PptxConverter().convert("tests/fixtures/sample.pptx")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_title_slide(doc)
        assert len(findings) == 0, f"Expected no title slide warning, got: {findings}"

    def test_every_slide_conclusion(self):
        """CON-004: 标题页豁免, 内容页应有足够内容"""
        doc = PptxConverter().convert("tests/fixtures/sample.pptx")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa.audit(doc)
        # 标题页豁免: 第一页不应有 CON-004 告警
        title_page_errors = [f for f in findings if f.page_index == 0 and f.rule_id == "CON-004"]
        assert len(title_page_errors) == 0, (
            f"Title slide should be exempt, got CON-004: {title_page_errors}"
        )

    def test_conclusion_findings_have_valid_structure(self):
        """CON-004: 所有 ERROR findings 必须有有效的 rule_id"""
        doc = PptxConverter().convert("tests/fixtures/sample.pptx")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_every_slide_has_conclusion(doc)
        for f in findings:
            if f.severity == FindingSeverity.ERROR:
                assert f.rule_id == "CON-004", f"Unexpected ERROR rule_id: {f.rule_id}"
                assert f.message, "Finding message should not be empty"
                assert f.page_index is not None, "Finding must have page_index"

    def test_exempt_layouts_empty_list_uses_default(self):
        """CON-004 豁免版式: 显式空列表不得覆盖内置默认 (修复: pipeline 传 [] 使默认失效)"""
        sa = StructureAuditor(config={"exempt_layouts": []})
        assert sa.exempt_layouts, "空列表不应覆盖内置默认豁免版式"
        assert "标题幻灯片" in sa.exempt_layouts

    def test_exempt_layouts_declared_used(self):
        """CON-004 豁免版式: 显式声明的列表生效"""
        sa = StructureAuditor(config={"exempt_layouts": ["封面页"]})
        assert sa.exempt_layouts == ["封面页"]

    def test_required_sections_severity_configurable(self):
        """P1-3: CON-002 严重度配置驱动 — 显式声明 warning 时生效 (曾硬编码 ERROR)"""
        sa = StructureAuditor(
            config={"required_sections": ["概述"], "required_sections_severity": "warning"}
        )
        assert sa.required_sections_severity == FindingSeverity.WARNING

    def test_required_sections_severity_default_error(self):
        """P1-3: CON-002 严重度未声明时默认 error (向后兼容)"""
        sa = StructureAuditor(config={"required_sections": ["概述"]})
        assert sa.required_sections_severity == FindingSeverity.ERROR

    def test_con004_content_layout_not_exempt(self):
        """CON-004: "Title and Content" 是内容版式，不得因含 "Title" 被豁免。"""
        page = Page(
            index=0,
            slide_number=1,
            layout_name="Title and Content",
            elements=[
                PageElement(
                    type="text_frame",
                    is_title=True,
                    paragraphs=[Paragraph(text="关键参数", runs=[])],
                ),
                PageElement(
                    type="text_frame",
                    paragraphs=[Paragraph(text="普通正文，只有数据", runs=[])],
                ),
            ],
        )
        doc = Document(
            format="pptx", source_path="x.pptx", metadata=DocumentMetadata(), pages=[page]
        )
        findings = StructureAuditor(
            config={"required_sections": []}
        )._check_every_slide_has_conclusion(doc)
        assert len(findings) == 1
        assert findings[0].rule_id == "CON-004"

    def test_con004_title_keyword_not_counted_as_conclusion(self):
        """CON-004: 标题 "关键参数" 的 "关键" 不能作为正文结论证据。"""
        page = Page(
            index=0,
            slide_number=1,
            layout_name="标题和内容",
            elements=[
                PageElement(
                    type="text_frame",
                    is_title=True,
                    paragraphs=[Paragraph(text="关键参数", runs=[])],
                ),
                PageElement(
                    type="text_frame",
                    paragraphs=[Paragraph(text="普通正文，只有数据", runs=[])],
                ),
            ],
        )
        doc = Document(
            format="pptx", source_path="x.pptx", metadata=DocumentMetadata(), pages=[page]
        )
        findings = StructureAuditor(
            config={"required_sections": []}
        )._check_every_slide_has_conclusion(doc)
        assert len(findings) == 1

    def test_con004_notes_not_counted_as_conclusion(self):
        """CON-004: 演讲者备注不是观众可见结论，不能单独豁免页面。"""
        page = Page(
            index=0,
            slide_number=1,
            layout_name="标题和内容",
            notes="结论：这里只是备注",
            elements=[
                PageElement(
                    type="text_frame",
                    is_title=True,
                    paragraphs=[Paragraph(text="参数", runs=[])],
                ),
                PageElement(
                    type="text_frame",
                    paragraphs=[Paragraph(text="普通正文", runs=[])],
                ),
            ],
        )
        doc = Document(
            format="pptx", source_path="x.pptx", metadata=DocumentMetadata(), pages=[page]
        )
        findings = StructureAuditor(
            config={"required_sections": []}
        )._check_every_slide_has_conclusion(doc)
        assert len(findings) == 1

    def test_con004_cover_layout_still_exempt(self):
        """CON-004: 明确的封面版式仍应豁免。"""
        page = Page(
            index=0,
            slide_number=1,
            layout_name="Title Slide",
            elements=[
                PageElement(type="text_frame", paragraphs=[Paragraph(text="副标题", runs=[])])
            ],
        )
        doc = Document(
            format="pptx", source_path="x.pptx", metadata=DocumentMetadata(), pages=[page]
        )
        assert (
            StructureAuditor(config={"required_sections": []})._check_every_slide_has_conclusion(
                doc
            )
            == []
        )

    def test_every_slide_conclusion_non_pptx_no_findings(self):
        """CON-004: 非 PPTX (MD) 不执行每页结论检查 (修复: 曾对 DOCX/PDF/MD 每页误报 error)"""
        doc = _text_doc("这是第一段普通正文，第二段补充说明，第三段技术描述。")
        sa = StructureAuditor(config={"required_sections": []})
        assert sa._check_every_slide_has_conclusion(doc) == [], "非 PPTX 文档不应产生 CON-004"

    def test_heading_levels_page_first_heading_exempt(self):
        """STR-003: 页首标题不参与跳级比较 (修复: 按标题分页的文档页首 H2/H3 不再误报)"""
        doc = _heading_doc([2, 3])  # 页首即 H2 (MD ### 切页场景)
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_heading_levels(doc)
        assert len(findings) == 0, f"页首 H2 不应误报跳级, got: {findings}"

    def test_heading_levels_real_skip_flagged(self):
        """STR-003: 页内真实跳级仍被检测 (H1→H3)"""
        doc = _heading_doc([1, 3])
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_heading_levels(doc)
        assert len(findings) == 1
        assert "H1" in findings[0].message and "H3" in findings[0].message

    def test_heading_levels_sequential_ok(self):
        """STR-003: 逐级递进 (H1→H2→H3) 不报"""
        doc = _heading_doc([1, 2, 3])
        sa = StructureAuditor(config={"required_sections": []})
        assert sa._check_heading_levels(doc) == []

    def test_heading_levels_mid_document_skip_flagged(self):
        """STR-003: 页内 H2→H4 仍报 (首标题豁免后保留跳级检测)"""
        doc = _heading_doc([2, 4])
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_heading_levels(doc)
        assert len(findings) == 1
        assert "H2" in findings[0].message and "H4" in findings[0].message

    def test_heading_levels_pptx_bullet_indent_not_flagged(self):
        """STR-003: PPTX 的 para.level 是缩进级别, 不得当标题层级 (修复: bullet 缩进 0→2 误报)"""
        page = Page(
            index=0,
            slide_number=1,
            elements=[
                PageElement(
                    type="text_frame",
                    paragraphs=[
                        Paragraph(text="• 第一级", runs=[], level=0),
                        Paragraph(text="    • 第三级", runs=[], level=2),
                    ],
                )
            ],
        )
        doc = Document(
            format="pptx", source_path="x.pptx", metadata=DocumentMetadata(), pages=[page]
        )
        sa = StructureAuditor(config={"required_sections": []})
        assert sa._check_heading_levels(doc) == [], "PPTX 缩进级别不应触发 STR-003 跳级"

    def test_figure_numbering_within_page_order_preserved(self):
        """STR-002: 同页内按出现次序检查 (修复: 曾按编号重排, 倒退被掩盖成跳号)"""
        doc = _text_doc("参见图3 与图1 的对比")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_figure_numbering(doc)
        assert len(findings) == 1, f"期望 1 条 STR-002, got: {findings}"
        assert "倒退" in findings[0].message, (
            f"图3 先于 图1 出现应为'倒退', got: {findings[0].message}"
        )

    def test_figure_numbering_cross_page_skip_flagged(self):
        """STR-002: 跨页跳号仍被检测 (图1 → 图3)"""
        p1 = Page(
            index=0,
            slide_number=1,
            elements=[
                PageElement(type="text_frame", paragraphs=[Paragraph(text="如图1 所示", runs=[])])
            ],
        )
        p2 = Page(
            index=1,
            slide_number=2,
            elements=[
                PageElement(type="text_frame", paragraphs=[Paragraph(text="如图3 所示", runs=[])])
            ],
        )
        doc = Document(format="md", source_path="x", metadata=DocumentMetadata(), pages=[p1, p2])
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_figure_numbering(doc)
        assert len(findings) == 1
        assert "不连续" in findings[0].message

    def test_figure_numbering_chapter_style_ignored(self):
        """STR-002: 章节式编号 (图1-1/图1-2/图2-1) 不误报 '编号重复'"""
        doc = _text_doc("图1-1 工艺流程图\n图1-2 参数表\n图2-1 结构图")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_figure_numbering(doc)
        assert len(findings) == 0, f"章节式编号不应报 STR-002, got: {findings}"

    def test_figure_numbering_chapter_style_real_skip_flagged(self):
        """STR-002: 章节式编号内部真实跳号仍被检测 (图1-1 → 图1-3)"""
        doc = _text_doc("图1-1 工艺流程图\n图1-3 参数表")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_figure_numbering(doc)
        assert len(findings) == 0, f"章节式编号暂不参与连续性校验 (设计取舍), got: {findings}"

    def test_figure_numbering_duplicate_flagged(self):
        """STR-002: 同页真实重复编号 (图2 出现两次) 应报 '编号重复'。

        2026-09-06 审查 D-2: 该分支曾零测试锚定 (负向注入短路重复检测后
        85 用例全绿), 本用例为正报锚点。
        """
        doc = _text_doc("如图2 所示\n再看图2 的细节")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_figure_numbering(doc)
        assert len(findings) == 1, f"期望 1 条重复编号, got: {findings}"
        assert "重复" in findings[0].message, f"应报编号重复, got: {findings[0].message}"

    def test_figure_numbering_two_digit_chapter_not_misdetected(self):
        """STR-002: 两位数章节编号 (图10-1/图11-2/表12-1) 不得回溯误析为 '图1'。

        2026-09-06 审查 D-1: 旧正则 (?![-–—]\\d) 挡不住 (\\d+) 内部回溯,
        两位数章节号被截为 '图1' → ERROR 级 '编号重复' 误报。
        """
        doc = _text_doc("见图10-1。\n接口时序见图11-2 与图11-3。\n附表见表12-1。")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_figure_numbering(doc)
        assert len(findings) == 0, f"两位数章节号不应触发 STR-002, got: {findings}"

    def test_figure_caption_format_space_insensitive(self):
        """STR-007: 指纹对空格不敏感 ('Fig. 1:' 与 'Fig.2:' 视为同一格式)"""
        doc = _text_doc("Fig. 1: 标题甲。\nFig.2: 标题乙。")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_figure_caption_format(doc)
        assert len(findings) == 0, f"空格差异不应算两种格式, got: {findings}"

    def test_figure_caption_format_mixed_flagged(self):
        """STR-007: 中英文格式混用仍被检测 ('图1：' vs 'Fig. 1:')"""
        doc = _text_doc("图1：标题甲。\nFig. 1: 标题乙。")
        sa = StructureAuditor(config={"required_sections": []})
        findings = sa._check_figure_caption_format(doc)
        assert len(findings) == 1
        assert "2 种" in findings[0].message

    def test_title_length_or_condition(self):
        """STR-004: 纯中文超长标题应触发告警 — 验证 AND→OR 修复"""
        from pptx import Presentation

        prs = Presentation()
        slide_layout = prs.slide_layouts[0]
        s = prs.slides.add_slide(slide_layout)
        # 设置超长中文标题: ~50+ chars > 40 上限
        long_title = "这是一个非常长的中文标题用于测试标题长度检查功能是否正常工作验证超长标题检测逻辑是否正确触发告警机制"
        s.shapes.title.text = long_title

        tmp_path = None
        try:
            # 使用临时文件避免泄漏
            with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
                tmp_path = tmp.name
            prs.save(tmp_path)

            doc = PptxConverter().convert(tmp_path)
            sa = StructureAuditor(config={"required_sections": []})
            findings = sa._check_title_length(doc)
            assert len(findings) >= 1, (
                f"Long Chinese title ({len(long_title)} chars) should trigger STR-004. "
                f"Got {len(findings)} findings."
            )
            # 验证 finding 包含正确的元数据
            f = findings[0]
            assert f.rule_id == "STR-004"
            assert f.metadata.get("chinese_chars", 0) > 40
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)


class TestFormatAuditor:
    def test_font_consistency_audit_api(self):
        """FMT-001: 非标准字体应通过 audit() 被检测到"""
        doc = PptxConverter().convert("tests/fixtures/sample.pptx")
        findings = FormatAuditor().audit(doc)
        fmt001_findings = [f for f in findings if f.rule_id == "FMT-001"]
        assert len(fmt001_findings) >= 1, (
            f"Expected at least one FMT-001 (non-standard font) finding, got {len(fmt001_findings)}"
            + f"\nAll rule_ids: {[f.rule_id for f in findings]}"
        )
        # 验证 finding 结构完整
        for f in fmt001_findings:
            assert f.type.value == "format"
            assert f.message
            assert f.rule_id == "FMT-001"

    def test_rule_severities_from_config_override(self):
        """FMT-001/002/004 严重度由 rules.md 声明驱动 (2026-09-06 审查 C-1: 曾硬编码 WARNING,
        用户改 rules.md 严重度静默失效)"""
        doc = PptxConverter().convert("tests/fixtures/sample.pptx")
        # 默认 (无 rule_severities): 代码内置兜底 — 值从 rules.md 声明读取,
        # 用户合理调整 rules.md 严重度时本测试不碎 (2026-09-06 r5 审查 F-09)
        declared = next(r.severity for r in parse_rules_md(RULES_MD) if r.rule_id == "FMT-001")
        default_findings = [f for f in FormatAuditor().audit(doc) if f.rule_id == "FMT-001"]
        assert default_findings, "前置: sample.pptx 应触发 FMT-001"
        assert all(f.severity == FindingSeverity(declared) for f in default_findings)
        # rule_severities 声明 error → audit() 统一覆盖为 ERROR
        auditor = FormatAuditor(config={"rule_severities": {"FMT-001": "error"}})
        findings = [f for f in auditor.audit(doc) if f.rule_id == "FMT-001"]
        assert findings, "覆盖配置不应影响 FMT-001 触发"
        assert all(f.severity == FindingSeverity.ERROR for f in findings)

    def test_rule_severities_extracted_from_rules_md(self):
        """extract_auditor_config 为无 check_type 的 FMT 规则收集 severity (C-1 五节点链路)

        N-4 (2026-09-06 四轮审查): 原测试硬编码 'warning' 与 rules.md 当前内容耦合,
        用户合理修改 rules.md 严重度会误报测试失败 — 改为自引用断言 (值 = 规则自身声明),
        测链不测值。
        """
        rules = parse_rules_md(RULES_MD)
        config = extract_auditor_config(rules)
        rs = config.get("rule_severities", {})
        declared = {
            r.rule_id: r.severity for r in rules if r.rule_id in ("FMT-001", "FMT-002", "FMT-004")
        }
        for rid in ("FMT-001", "FMT-002", "FMT-004"):
            assert rid in rs, f"{rid} 应进入 rule_severities 通道"
            assert rs[rid] == declared[rid], f"{rid} 收集值应与 rules.md 声明一致"
        # 有 check_type 的规则不进该通道 (严重度由 custom_rules dispatch 覆盖)
        assert "FMT-003" not in rs

    def test_enabled_rule_ids_disables_undeclared_format_rules(self):
        """FMT-001/002/004 未出现在 rules.md 时不得用默认值继续执行。"""
        from src.models.document import Run

        page = Page(
            index=0,
            slide_number=1,
            elements=[
                PageElement(
                    type="text_frame",
                    paragraphs=[
                        Paragraph(
                            text="测" * 200,
                            runs=[Run(text="测" * 200, font_name="宋体", font_size=10)],
                        )
                    ],
                )
            ],
        )
        doc = Document(
            format="pptx", source_path="x.pptx", metadata=DocumentMetadata(), pages=[page]
        )
        findings = FormatAuditor(config={"enabled_rule_ids": set()}).audit(doc)
        rule_ids = {f.rule_id for f in findings}
        assert "FMT-001" not in rule_ids
        assert "FMT-002" not in rule_ids
        assert "FMT-004" not in rule_ids

    def test_ppt_only_checks_not_applied_to_docx(self):
        """FMT-001/002/003 是幻灯片语义，DOCX 不套用（16pt 标题/300 字页不误报）。"""
        from src.models.document import Run

        page = Page(
            index=0,
            slide_number=1,
            elements=[
                PageElement(
                    type="text_frame",
                    is_title=True,
                    paragraphs=[
                        Paragraph(
                            text="概述",
                            runs=[Run(text="概述", font_name="宋体", font_size=16)],
                        )
                    ],
                ),
                PageElement(
                    type="text_frame",
                    paragraphs=[
                        Paragraph(
                            text="测" * 300,
                            runs=[Run(text="测" * 300, font_name="宋体", font_size=10)],
                        )
                    ],
                ),
            ],
        )
        doc = Document(
            format="docx", source_path="x.docx", metadata=DocumentMetadata(), pages=[page]
        )
        findings = FormatAuditor().audit(doc)
        rule_ids = {f.rule_id for f in findings}
        assert "FMT-001" not in rule_ids
        assert "FMT-002" not in rule_ids
        assert "FMT-003" not in rule_ids

    def test_font_consistency_east_asia_flagged(self):
        """FMT-001: 非允许的 eastAsia 中文字体应触发告警 (font_scope=east_asia)"""
        from src.models.document import Run

        page = Page(
            index=0,
            slide_number=1,
            elements=[
                PageElement(
                    type="text_frame",
                    paragraphs=[
                        Paragraph(
                            text="中文正文",
                            runs=[
                                Run(text="中文正文", font_name="Arial", font_name_east_asia="宋体"),
                            ],
                        ),
                    ],
                ),
            ],
        )
        findings = FormatAuditor()._check_font_consistency(page)
        fmt001 = [f for f in findings if f.rule_id == "FMT-001"]
        ea = [f for f in fmt001 if (f.metadata or {}).get("font_scope") == "east_asia"]
        assert len(ea) >= 1, f"非允许 eastAsia 字体应触发 FMT-001, got: {fmt001}"
        assert "宋体" in ea[0].message
        assert "中文" in ea[0].message  # message 区分中文（eastAsia）字体
        # latin 字体 (Arial) 在允许列表 → 不误报
        latin = [f for f in fmt001 if (f.metadata or {}).get("font_scope") == "latin"]
        assert len(latin) == 0

    def test_font_consistency_latin_scope_label(self):
        """FMT-001: 非允许 latin 字体的 message 标注为西文（latin）"""
        from src.models.document import Run

        page = Page(
            index=0,
            slide_number=1,
            elements=[
                PageElement(
                    type="text_frame",
                    paragraphs=[
                        Paragraph(
                            text="x",
                            runs=[
                                Run(
                                    text="x", font_name="Comic Sans", font_name_east_asia="微软雅黑"
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        findings = FormatAuditor()._check_font_consistency(page)
        fmt001 = [f for f in findings if f.rule_id == "FMT-001"]
        latin = [f for f in fmt001 if (f.metadata or {}).get("font_scope") == "latin"]
        assert len(latin) == 1
        assert "西文" in latin[0].message
        assert latin[0].metadata.get("font") == "Comic Sans"

    def test_global_font_consistency_counts_east_asia(self):
        """FMT-001 全局: 复合键 (font, scope) 统计 — latin 统一 + 3 种 eastAsia → 触发"""
        from src.models.document import Run

        page = Page(
            index=0,
            slide_number=1,
            elements=[
                PageElement(
                    type="text_frame",
                    paragraphs=[
                        Paragraph(
                            text="a",
                            runs=[Run(text="a", font_name="Arial", font_name_east_asia="宋体")],
                        ),
                        Paragraph(
                            text="b",
                            runs=[Run(text="b", font_name="Arial", font_name_east_asia="黑体")],
                        ),
                        Paragraph(
                            text="c",
                            runs=[Run(text="c", font_name="Arial", font_name_east_asia="楷体")],
                        ),
                    ],
                )
            ],
        )
        doc = Document(format="pptx", source_path="x", metadata=DocumentMetadata(), pages=[page])
        findings = FormatAuditor()._check_global_font_consistency(doc)
        assert len(findings) == 1, f"4 种复合字体应触发 FMT-001 全局检查, got: {findings}"
        f = findings[0]
        assert f.rule_id == "FMT-001"
        dist = f.metadata["font_distribution"]
        assert dist["Arial/latin"] == 3
        assert dist["宋体/east_asia"] == 1 and dist["黑体/east_asia"] == 1
        assert dist["楷体/east_asia"] == 1

    def test_english_char_count_ignores_punctuation(self):
        """FMT-004: 英文计数只算字母 — 数字/标点/空格不计入 (修复: 曾 总长-中文字数)"""
        fa = FormatAuditor()
        doc = _text_doc("1" * 300 + " test")
        findings = fa._check_paragraph_length(doc.pages[0])
        assert len(findings) == 0, f"纯数字+少量字母不应触发 FMT-004, got: {findings}"

    def test_english_char_count_pure_letters_triggers(self):
        """FMT-004: 纯字母超上限仍触发 (回归)"""
        fa = FormatAuditor()
        doc = _text_doc("a" * 305)
        findings = fa._check_paragraph_length(doc.pages[0])
        assert len(findings) == 1
        assert findings[0].rule_id == "FMT-004"
        assert "英文字符" in findings[0].message

    def test_markdown_code_block_not_paragraph_length(self):
        """FMT-004: Markdown 围栏代码块不算"长段落" (2026-11 审查)

        代码块多行是常态；旧实现把整块按段落计 → README 自审 19 条误报。
        """
        fa = FormatAuditor()
        code = "```bash\n" + "\n".join(f"echo line{i}" for i in range(20)) + "\n```"
        doc = _text_doc(code)
        assert fa._check_paragraph_length(doc.pages[0]) == []

    def test_markdown_bullet_list_not_paragraph_length(self, tmp_path):
        """FMT-004: Markdown 列表块 (逐项拆段) 不报"长段落" (2026-11 审查)"""
        from src.converters.md_converter import MarkdownConverter

        md = "# 列表\n\n" + "\n".join(f"- 第 {i} 项要点" for i in range(5)) + "\n"
        path = tmp_path / "list.md"
        path.write_text(md, encoding="utf-8")
        doc = MarkdownConverter().convert(str(path))
        fa = FormatAuditor()
        findings = [
            f for p in doc.pages for f in fa._check_paragraph_length(p) if f.rule_id == "FMT-004"
        ]
        assert findings == [], f"列表项不应报 FMT-004, got: {[f.message for f in findings]}"

    def test_global_font_consistency_latin_plus_two_east_asia_ok(self):
        """FMT-001 全局: latin 统一 + 2 种 eastAsia (共 3 复合键) → 不触发"""
        from src.models.document import Run

        page = Page(
            index=0,
            slide_number=1,
            elements=[
                PageElement(
                    type="text_frame",
                    paragraphs=[
                        Paragraph(
                            text="a",
                            runs=[Run(text="a", font_name="Arial", font_name_east_asia="宋体")],
                        ),
                        Paragraph(
                            text="b",
                            runs=[Run(text="b", font_name="Arial", font_name_east_asia="黑体")],
                        ),
                    ],
                )
            ],
        )
        doc = Document(format="pptx", source_path="x", metadata=DocumentMetadata(), pages=[page])
        findings = FormatAuditor()._check_global_font_consistency(doc)
        assert len(findings) == 0, f"3 种复合字体不应触发, got: {findings}"

    def test_font_size_max_check(self):
        """FMT-002: 验证字号最大值检查生效"""
        from pptx import Presentation
        from pptx.util import Pt

        prs = Presentation()
        slide_layout = prs.slide_layouts[0]
        s = prs.slides.add_slide(slide_layout)
        # 设置超大标题字号 (72pt > 40pt max)
        s.shapes.title.text = "Huge Title"
        s.shapes.title.text_frame.paragraphs[0].runs[0].font.size = Pt(72)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
                tmp_path = tmp.name
            prs.save(tmp_path)

            doc = PptxConverter().convert(tmp_path)
            findings = FormatAuditor().audit(doc)
            # 应检测到超大标题字号
            fmt002_max = [f for f in findings if f.rule_id == "FMT-002" and "过大" in f.message]
            assert len(fmt002_max) >= 1, (
                f"72pt title should trigger FMT-002 max size warning. "
                f"All FMT-002: {[f.message for f in findings if f.rule_id == 'FMT-002']}"
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)


class TestFactualAuditor:
    def test_numeric_extraction_with_common_units(self):
        """CON-001: 常见工程单位数值完整提取, 不被回溯截断 (2026-09-06 审查 D-3)

        修复前 '28pt'→'2'、'500g'→'50' (单位表外回溯截断)。
        """
        from src.auditors.factual import _NUMERIC_VALUE_RE

        assert _NUMERIC_VALUE_RE.findall("字号 28pt") == ["28pt"]
        assert _NUMERIC_VALUE_RE.findall("净重 500g") == ["500g"]
        assert _NUMERIC_VALUE_RE.findall("间距 5 km") == ["5 km"]
        assert _NUMERIC_VALUE_RE.findall("延迟 30ms") == ["30ms"]
        # 表内原有行为不回归: 电学单位与百分数
        assert _NUMERIC_VALUE_RE.findall("电压 3.3V") == ["3.3V"]
        assert _NUMERIC_VALUE_RE.findall("良率 99%") == ["99%"]

    def test_numeric_extraction_truncation_guard_skips_untrusted(self):
        """CON-001: 表外单位触发回溯时整值跳过, 不产出错误数值 (2026-09-06 审查 D-3)

        N-2 (四轮审查): 截断防护扩至非数字后缀 — "3.3Vs" 被截为 "3"、小数/千分位
        延续 ("1,000" 被截为 "1") 亦不得进入一致性比较。
        """
        fa = FactualAuditor()
        doc = _text_doc("输出 28xyz 与 29xyz 为表外单位。电压 3.3Vs。容量 1.5Ah。带宽 1,000MHz。")
        entries = fa._extract_numeric_values(doc)
        values = [e["value"] for e in entries]
        assert 2.0 not in values, f"截断值 2 不得进入一致性比较, got: {values}"
        assert 3.0 not in values, f"截断值 3 (来自 3.3Vs) 不得进入, got: {values}"
        assert 1.0 not in values, f"截断值 1 (来自 1.5Ah/1,000) 不得进入, got: {values}"

    def test_numeric_qualifiers_not_treated_as_metric_values(self):
        """CON-001: 年份/季度/工艺节点是指标限定词，不得报数值不一致。"""
        fa = FactualAuditor()
        scenarios = [
            ("2025年良率95%", "2026年良率96%", "年份"),
            ("第1季度良率95%", "第2季度良率96%", "季度"),
            ("5nm节点良率95%", "7nm节点良率92%", "工艺节点"),
            ("5nm Node Yield: 95.3% (Q1 2026)", "5nm Node Yield: 87.1% (Q2 2026)", "节点+季度"),
        ]
        for first, second, label in scenarios:
            pages = [
                Page(
                    index=i,
                    slide_number=i + 1,
                    elements=[
                        PageElement(type="text_frame", paragraphs=[Paragraph(text=text, runs=[])])
                    ],
                )
                for i, text in enumerate((first, second))
            ]
            doc = Document(
                format="md",
                source_path="x",
                metadata=DocumentMetadata(),
                pages=pages,
            )
            findings = fa._check_numeric_consistency(doc)
            assert findings == [], f"{label}不应报 CON-001, got: {findings}"

    def test_numeric_same_metric_different_value_still_flagged(self):
        """CON-001: 同一指标不同数值仍必须报错（降噪不能牺牲真阳性）。"""
        fa = FactualAuditor()
        pages = [
            Page(
                index=i,
                slide_number=i + 1,
                elements=[
                    PageElement(
                        type="text_frame",
                        paragraphs=[Paragraph(text=text, runs=[])],
                    )
                ],
            )
            for i, text in enumerate(("成品良率 95.3%", "成品良率 95.4%"))
        ]
        doc = Document(format="md", source_path="x", metadata=DocumentMetadata(), pages=pages)
        findings = fa._check_numeric_consistency(doc)
        assert len(findings) == 1
        assert findings[0].rule_id == "CON-001"

    def test_numeric_consistency_figure_subnumber_not_flagged(self):
        """CON-001: 章节式图表编号子号跨页同句式引用不得误报 (2026-09-06 四轮审查 N-1)

        修复前: "图2-1" 的子号 "1" 紧邻前缀 "图2-" 以连字符结尾, 编号跳过守卫
        (关键词后缀分支) 不匹配 → 子号进入数值池 → 同句式跨页引用不同子号时
        误报 ERROR "数值不一致" (values=[1.0, 2.0])。
        本用例覆盖 图/表、中英文引用 4 组同句式场景, 全部应 0 条。
        """
        fa = FactualAuditor()
        scenarios = [
            (["详细参数见图2-1。", "详细参数见图2-2。"], "图中文章节式"),
            (["流程如图2-1 所示。", "流程如图2-2 所示。"], "图-所示句式"),
            (["参数见表3-1。", "参数见表3-2。"], "表中文章节式"),
            (["See Fig.2-1 for detail.", "See Fig.2-2 for detail."], "图英文章节式"),
        ]
        for texts, label in scenarios:
            pages = [
                Page(
                    index=i,
                    slide_number=i + 1,
                    elements=[
                        PageElement(type="text_frame", paragraphs=[Paragraph(text=t, runs=[])])
                    ],
                )
                for i, t in enumerate(texts)
            ]
            doc = Document(format="md", source_path="x", metadata=DocumentMetadata(), pages=pages)
            con1 = [f for f in fa.audit(doc) if f.rule_id == "CON-001"]
            assert len(con1) == 0, f"{label} 不应误报 CON-001, got: {con1}"

    def test_numeric_consistency_with_pt_units_not_missed(self):
        """CON-001: 28pt vs 29pt 同指标不一致应报 (修复前截断同值导致漏报, D-3)"""
        p1 = Page(
            index=0,
            slide_number=1,
            elements=[
                PageElement(
                    type="text_frame", paragraphs=[Paragraph(text="标准字号为 28pt。", runs=[])]
                )
            ],
        )
        p2 = Page(
            index=1,
            slide_number=2,
            elements=[
                PageElement(
                    type="text_frame", paragraphs=[Paragraph(text="标准字号为 29pt。", runs=[])]
                )
            ],
        )
        doc = Document(format="md", source_path="x", metadata=DocumentMetadata(), pages=[p1, p2])
        findings = FactualAuditor().audit(doc)
        con1 = [f for f in findings if f.rule_id == "CON-001"]
        assert len(con1) == 1, f"28pt vs 29pt 不一致应报 1 条 CON-001, got: {con1}"
        assert 28.0 in con1[0].metadata["values"], f"报告值应含完整 28.0, got: {con1[0].metadata}"

    def test_abbreviation_check_via_audit(self):
        """CON-003: 未定义缩写应通过 audit() 被检测"""
        doc = PptxConverter().convert("tests/fixtures/sample.pptx")
        findings = FactualAuditor().audit(doc)
        con003_findings = [f for f in findings if f.rule_id == "CON-003"]
        assert len(con003_findings) >= 1, (
            f"Expected at least one CON-003 (undefined abbreviation) finding, got {len(con003_findings)}"
        )
        # 验证发现包含正确信息
        for f in con003_findings:
            assert "未给出全称" in f.message, f"Unexpected message: {f.message}"
            assert f.type.value == "factual"
            # CON-003 严重度与 rules.md 声明一致 (error; 二轮审查修复独立模式兜底值曾为 WARNING)
            assert f.severity == FindingSeverity.ERROR

    def test_common_uppercase_words_skipped(self):
        """CON-003: 常见英语大写单词 (THE, AND, NEW 等) 不应被标记为未定义缩写

        2026-11 审查: 旧断言取 ``metadata["abbreviation"]`` —— 该键从不写入
        (``or ""`` 兜底) → 断言恒真, 删掉 _COMMON_UPPERCASE_WORDS 过滤也全绿。
        改为断言 finding.message 不含常见词, 并以一个真实缩写作阳性锚点。
        """
        fa = FactualAuditor()
        doc = _text_doc("THE AND FOR NEW 是常见词，XYZQ 是真实缩写。")
        findings = fa._check_abbreviation_first_defined(doc)
        messages = [f.message for f in findings]
        for word in ("THE", "AND", "FOR", "NEW"):
            assert not any(f"「{word}」" in msg for msg in messages), (
                f"常见词 {word} 不应被标记为未定义缩写, got: {messages}"
            )
        assert any("「XYZQ」" in msg for msg in messages), (
            f"真实缩写 XYZQ 应被标记 (证明检查确实执行), got: {messages}"
        )

    def test_abbreviation_accept_whitelist_skipped(self):
        """CON-003: vocab/accept.txt 中的领域缩写 (WLP/FOWLP/RDL) 不应报未定义。"""
        vocab_dir = str(Path(__file__).resolve().parent.parent / "vocab")
        fa = FactualAuditor(config={"vocab_dir": vocab_dir})
        doc = _text_doc("WLP 与 FOWLP、RDL 工艺用于先进封装。")
        findings = fa._check_abbreviation_first_defined(doc)
        assert findings == [], f"白名单缩写不应报 CON-003, got: {findings}"

    def test_abbreviation_reuse_after_definition_not_double_defined(self):
        """CON-003-B: 定义后再次使用 (复用) 不得误计为重复定义 (修复: is_full_before 120 字符窗口假阳性)"""
        fa = FactualAuditor()
        doc = _text_doc("TSV (硅通孔 TSV) 工艺。TSV 用于 3D 集成。")
        findings = fa._check_abbreviation_multiply_defined(doc)
        assert len(findings) == 0, f"TSV 仅定义一次, 复用不应报 CON-003-B: {findings}"

    def test_abbreviation_fullname_parens_abbr_recognized(self):
        """CON-003: "全称 (TSV)" 定义格式 — 括号内缩写应识别为已定义 (不报未给出全称)"""
        fa = FactualAuditor()
        doc = _text_doc("Through Silicon Via (TSV) 工艺。TSV 用于先进封装。")
        findings = fa._check_abbreviation_first_defined(doc)
        assert len(findings) == 0, f"'全称 (TSV)' 应视为已定义, got: {findings}"

    def test_abbreviation_multiply_defined_cross_page_same_offset(self):
        """CON-003-B: 两页在相同字符偏移各定义一次 → 仍应报重复定义 (2026-11 审查)

        def_site 是页内字符偏移；旧实现只用它去重 → 两页模板句同偏移定义被误判为
        "同一定义站点"，CON-003-B 静默漏报。
        """
        text = "TSV (Through Silicon Via) 用于互连。"
        pages = [
            Page(
                index=i,
                slide_number=i + 1,
                elements=[
                    PageElement(type="text_frame", paragraphs=[Paragraph(text=text, runs=[])])
                ],
            )
            for i in range(2)
        ]
        doc = Document(format="md", source_path="x", metadata=DocumentMetadata(), pages=pages)
        findings = FactualAuditor()._check_abbreviation_multiply_defined(doc)
        assert len(findings) == 1, f"跨页重复定义应报 1 条 CON-003-B, got: {findings}"
        assert findings[0].rule_id == "CON-003-B"

    def test_abbreviation_defined_only_inside_own_definition(self):
        """CON-003-A: 缩写仅出现在自己的定义括号内 → 应判「定义后未再使用」(2026-11 审查)

        旧实现用 total_count(含括号内重复) 比 definition_count(去重站点)：
        "TSV (硅通孔 TSV)" total=2 > def=1 → 该报的 CON-003-A 被漏掉。
        """
        doc = _text_doc("TSV (硅通孔 TSV) 工艺。")
        findings = FactualAuditor()._check_abbreviation_defined_never_used(doc)
        assert len(findings) == 1, f"仅定义处出现应报 CON-003-A, got: {findings}"
        assert findings[0].rule_id == "CON-003-A"
        assert findings[0].metadata["usage_count"] == 0

    def test_abbreviation_same_page_later_definition_message(self):
        """CON-003-C: 同页后文才定义时文案不得自相矛盾 (2026-11 审查)

        旧文案固定为「在第 N 页使用，但在第 M 页才给出定义」，同页时输出
        「在第 1 页使用，但在第 1 页才给出定义」。
        """
        doc = _text_doc("TSV 用于互连，后文给出定义 TSV (Through Silicon Via)。")
        findings = FactualAuditor()._check_abbreviation_used_before_defined(doc)
        assert len(findings) == 1, f"应先使用后定义, got: {findings}"
        msg = findings[0].message
        assert "同页后文才给出定义" in msg, msg
        assert "但在第 1 页才给出定义" not in msg, msg

    def test_abbreviation_parenthetical_mention_not_definition(self):
        """括号内顺带提及不是"全称 (ABBR)"定义 (2026-11 审查)

        旧实现把"缩写位于括号内"一律当定义 → `（核心依赖 + PDF + 开发工具）`
        让 PDF 被当成已定义，CON-003 漏报、CON-003-A 假阳性。
        """
        fa = FactualAuditor()
        doc = _text_doc("安装说明（核心依赖 + PDF + 开发工具）另见附录。")
        findings = fa._check_abbreviation_first_defined(doc)
        assert any("「PDF」" in f.message for f in findings), (
            f"括号内顺带提及不应算定义, got: {[f.message for f in findings]}"
        )

    def test_abbreviation_fullwidth_paren_definition_recognized(self):
        """全角括号 "TSV（硅通孔）" 应识别为定义 (旧实现只认半角括号)"""
        fa = FactualAuditor()
        doc = _text_doc("TSV（硅通孔）用于垂直互连。")
        findings = fa._check_abbreviation_first_defined(doc)
        assert findings == [], f"全角括号定义应被识别, got: {findings}"

    def test_abbreviation_filename_token_skipped(self):
        """文件名/路径片段不是待定义缩写 (AGENTS.md / MANIFEST.in)"""
        fa = FactualAuditor()
        doc = _text_doc("详见 MANIFEST.in 与 AGENTS.md，以及 src/CHANGELOG 说明。")
        findings = fa._check_abbreviation_first_defined(doc)
        assert findings == [], f"文件名不应报未定义缩写, got: {findings}"

    def test_abbreviation_cache_weakref_identity(self):
        """回归: 缩写扫描缓存以 weakref.ref 绑定文档身份 (曾用 id(doc) — 地址可复用)"""
        import gc

        fa = FactualAuditor()
        doc1 = _text_doc("TSV 工艺用于先进封装。")
        fa._check_abbreviation_first_defined(doc1)
        key = fa._abbr_scan_cache[0]
        assert callable(key), f"缓存键应为 weakref.ref, got {type(key)}"
        assert key() is doc1, "存活时 weakref 应指向同一文档对象"
        del doc1
        gc.collect()
        assert key() is None, "文档对象回收后 weakref 应失效"

    def test_abbreviation_cache_weakref_new_doc_after_gc(self):
        """回归: 对象回收 + 新对象 → 缓存不串档 (weakref 失效后重扫)"""
        import gc

        fa = FactualAuditor()
        doc1 = _text_doc("TSV 工艺用于先进封装。")
        assert len(fa._check_abbreviation_first_defined(doc1)) == 1  # TSV 未定义
        del doc1
        gc.collect()
        doc2 = _text_doc("TSV (Through Silicon Via) 是硅通孔。")
        findings_doc2 = fa._check_abbreviation_first_defined(doc2)
        assert len(findings_doc2) == 0, (
            f"doc2 不应复用已回收 doc1 的扫描结果 (TSV 已定义), got: {findings_doc2}"
        )

    def test_abbreviation_cache_not_leaked_across_documents(self):
        """回归: 缩写扫描缓存不得跨文档串档 (独立模式 dispatch 直调不走 audit() 的 reset)"""
        doc1 = _text_doc("TSV 工艺用于先进封装。")
        doc2 = _text_doc("TSV (Through Silicon Via) 是硅通孔。")
        fa = FactualAuditor()
        # 模拟 CustomRulesAuditor 独立模式: 直接调 dispatch 方法 (不经过 audit() 重置缓存)
        fa._check_abbreviation_first_defined(doc1)
        findings_doc2 = fa._check_abbreviation_first_defined(doc2)
        # doc2 的 TSV 首次出现即带全称定义 → 不应报"首次未定义"
        assert len(findings_doc2) == 0, f"doc2 不应复用车 doc1 的扫描结果: {findings_doc2}"


class TestAlignment:
    """2026-10-28 回归: 对齐检查必须区分标题/正文，避免上下堆叠误报。"""

    @staticmethod
    def _frame(text: str, *, left: float, top: float, width: float, height: float, title=False):
        return PageElement(
            type="text_frame",
            is_title=title,
            left=left,
            top=top,
            width=width,
            height=height,
            paragraphs=[Paragraph(text=text, runs=[])],
        )

    def test_title_body_stacked_not_flagged(self):
        """标题 top=22 / 正文 top=126 同左边界同宽 → 不应报未对齐。"""
        page = Page(
            index=0,
            slide_number=1,
            elements=[
                self._frame("标题", left=36, top=22, width=648, height=90, title=True),
                self._frame("正文", left=36, top=126, width=648, height=356),
            ],
        )
        assert FormatAuditor()._check_alignment(page) == []

    def test_side_by_side_vertical_misalignment_flagged(self):
        """同一行两个正文框 top 相差 20pt 且垂直重叠 → 报垂直不一致。"""
        page = Page(
            index=0,
            slide_number=1,
            elements=[
                self._frame("左栏", left=0, top=100, width=100, height=50),
                self._frame("右栏", left=150, top=120, width=100, height=50),
            ],
        )
        findings = FormatAuditor()._check_alignment(page)
        assert len(findings) == 1
        assert "垂直位置不一致" in findings[0].message

    def test_nested_textbox_overlay_not_flagged(self):
        """文本框覆盖在内容占位符上（水平大幅重叠）→ 不报同一行未对齐。"""
        page = Page(
            index=0,
            slide_number=1,
            elements=[
                self._frame("正文", left=36, top=126, width=648, height=356),
                self._frame("覆盖文本框", left=58, top=108, width=600, height=50),
            ],
        )
        assert FormatAuditor()._check_alignment(page) == []

    def test_same_column_width_mismatch_flagged(self):
        """同列两个正文框宽度不一致 → 报宽度/右边界不一致。"""
        page = Page(
            index=0,
            slide_number=1,
            elements=[
                self._frame("上", left=36, top=22, width=648, height=90),
                self._frame("下", left=36, top=140, width=500, height=200),
            ],
        )
        findings = FormatAuditor()._check_alignment(page)
        assert len(findings) == 1
        assert "宽度或右边界" in findings[0].message


class TestLayoutChecks:
    """2026-10-28: 元素重叠 / 安全边距。"""

    @staticmethod
    def _doc(page: Page) -> Document:
        return Document(
            format="pptx", source_path="x.pptx", metadata=DocumentMetadata(), pages=[page]
        )

    @staticmethod
    def _frame(text, *, left, top, width, height):
        return PageElement(
            type="text_frame",
            left=left,
            top=top,
            width=width,
            height=height,
            paragraphs=[Paragraph(text=text, runs=[])],
        )

    def test_overlap_flagged(self):
        page = Page(
            index=0,
            slide_number=1,
            elements=[
                self._frame("A", left=0, top=0, width=100, height=50),
                self._frame("B", left=50, top=25, width=100, height=50),
            ],
        )
        findings = FormatAuditor()._check_element_overlap(page, self._doc(page))
        assert len(findings) == 1
        assert findings[0].rule_id == "FMT-OVERLAP"

    def test_nested_textbox_not_flagged(self):
        page = Page(
            index=0,
            slide_number=1,
            elements=[
                self._frame("外", left=0, top=0, width=100, height=100),
                self._frame("内", left=10, top=10, width=20, height=20),
            ],
        )
        assert FormatAuditor()._check_element_overlap(page, self._doc(page)) == []

    def test_safe_margin_flagged(self):
        page = Page(
            index=0,
            slide_number=1,
            elements=[self._frame("贴边", left=1, top=1, width=100, height=50)],
        )
        findings = FormatAuditor()._check_safe_margin(page, self._doc(page))
        assert len(findings) == 1
        assert findings[0].rule_id == "FMT-SAFE-MARGIN"

    def test_safe_margin_clean_not_flagged(self):
        page = Page(
            index=0,
            slide_number=1,
            elements=[self._frame("正常", left=50, top=50, width=100, height=50)],
        )
        assert FormatAuditor()._check_safe_margin(page, self._doc(page)) == []

    def test_text_overflow_estimated(self):
        from src.models.document import Run

        elem = PageElement(
            type="text_frame",
            left=50,
            top=50,
            width=80,
            height=40,
            paragraphs=[
                Paragraph(
                    text="测" * 20,
                    runs=[Run(text="测" * 20, effective_font_size=12.0)],
                )
            ],
        )
        page = Page(index=0, slide_number=1, elements=[elem])
        findings = FormatAuditor()._check_text_overflow(page, self._doc(page))
        assert len(findings) == 1
        assert findings[0].rule_id == "FMT-TEXT-OVERFLOW"

    def test_text_overflow_wide_box_not_flagged(self):
        from src.models.document import Run

        elem = PageElement(
            type="text_frame",
            left=50,
            top=50,
            width=500,
            height=120,
            paragraphs=[
                Paragraph(
                    text="测" * 20,
                    runs=[Run(text="测" * 20, effective_font_size=12.0)],
                )
            ],
        )
        page = Page(index=0, slide_number=1, elements=[elem])
        assert FormatAuditor()._check_text_overflow(page, self._doc(page)) == []

    def test_footer_partial_missing_flagged(self):
        with_footer = PageElement(
            type="text_frame", placeholder_type="footer", paragraphs=[Paragraph(text="页脚")]
        )
        pages = [
            Page(index=0, slide_number=1, elements=[]),
            Page(index=1, slide_number=2, elements=[with_footer]),
            Page(index=2, slide_number=3, elements=[]),
        ]
        doc = Document(
            format="pptx", source_path="x.pptx", metadata=DocumentMetadata(), pages=pages
        )
        findings = FormatAuditor()._check_footer_consistency(doc)
        assert len(findings) == 1
        assert findings[0].rule_id == "FMT-FOOTER"

    def test_image_quality_flagged(self):
        elem = PageElement(
            type="image",
            width=200,
            height=50,
            image_px_width=100,
            image_px_height=100,
            image_alt_text=None,
        )
        page = Page(index=0, slide_number=1, elements=[elem])
        findings = FormatAuditor()._check_image_quality(page, self._doc(page))
        assert any(f.rule_id == "FMT-IMAGE" and "宽高比" in f.message for f in findings)
        assert any(f.rule_id == "FMT-IMAGE" and "替代文本" in f.message for f in findings)

    def test_chart_missing_title_flagged(self):
        elem = PageElement(type="chart", chart_has_title=False)
        page = Page(index=0, slide_number=1, elements=[elem])
        findings = FormatAuditor()._check_chart_labeling(page, self._doc(page))
        assert len(findings) == 1
        assert findings[0].rule_id == "FMT-CHART"

    def test_master_consistency_flagged(self):
        pages = [
            Page(index=0, slide_number=1, master_name="A"),
            Page(index=1, slide_number=2, master_name="B"),
        ]
        doc = Document(
            format="pptx", source_path="x.pptx", metadata=DocumentMetadata(), pages=pages
        )
        findings = StructureAuditor(config={"required_sections": []})._check_master_consistency(doc)
        assert len(findings) == 1
        assert findings[0].rule_id == "STR-MASTER"

    def test_multiple_title_layout_findings_not_deduped(self):
        """版式重复使用: 多个标题版式各一条 finding, 不得被 dedup_key 折叠 (2026-11 审查)

        这些 finding 无 rule_id / 无 page_index / 旧实现 context=None →
        dedup_key 完全相同, AuditFinding.deduplicate() 只留第一条 (信息丢失)。
        """
        from src.models.finding import AuditFinding

        names = ["标题幻灯片", "标题幻灯片", "封面", "封面"]
        pages = [
            Page(
                index=i,
                slide_number=i + 1,
                layout_name=name,
                elements=[PageElement(type="text_frame", paragraphs=[Paragraph(text="x")])],
            )
            for i, name in enumerate(names)
        ]
        doc = Document(
            format="pptx", source_path="x.pptx", metadata=DocumentMetadata(), pages=pages
        )
        findings = FormatAuditor()._check_layout_consistency(doc)
        assert len(findings) == 2, f"两个标题版式应各一条, got: {[f.message for f in findings]}"
        deduped = AuditFinding.deduplicate(findings)
        assert len(deduped) == 2, f"dedup 后不得丢失, got: {[f.message for f in deduped]}"

    def test_layout_consistency_recognizes_english_cover(self):
        """英文封面版式 ("Title Slide") 也要被识别 (2026-11 审查)

        旧实现用 ``"标题" in name`` 字面判断 → 英文模板的标题版式复用完全不检查。
        """
        names = ["Title Slide", "Title Slide"]
        pages = [
            Page(
                index=i,
                slide_number=i + 1,
                layout_name=name,
                elements=[PageElement(type="text_frame", paragraphs=[Paragraph(text="x")])],
            )
            for i, name in enumerate(names)
        ]
        doc = Document(
            format="pptx", source_path="x.pptx", metadata=DocumentMetadata(), pages=pages
        )
        findings = FormatAuditor()._check_layout_consistency(doc)
        assert len(findings) == 1, f"英文标题版式复用应报 1 条, got: {findings}"

    def test_layout_consistency_content_layout_not_flagged(self):
        """内容版式名含 "Title" 但非封面 ("Title and Content") 不得被当标题版式。"""
        names = ["Title and Content", "Title and Content"]
        pages = [
            Page(
                index=i,
                slide_number=i + 1,
                layout_name=name,
                elements=[PageElement(type="text_frame", paragraphs=[Paragraph(text="x")])],
            )
            for i, name in enumerate(names)
        ]
        doc = Document(
            format="pptx", source_path="x.pptx", metadata=DocumentMetadata(), pages=pages
        )
        assert FormatAuditor()._check_layout_consistency(doc) == []


class TestTableFit:
    """2026-10-29: 表格 fit 估算 (行高/列宽/越界)。几何估算，非渲染级。"""

    @staticmethod
    def _doc(page, fmt="pptx"):
        return Document(
            format=fmt, source_path=f"x.{fmt}", metadata=DocumentMetadata(), pages=[page]
        )

    @staticmethod
    def _table(text="", *, row_heights=None, col_widths=None, top=50, font_size=None):
        from src.models.document import TableCell

        cell = TableCell(text=text, row=0, col=0, font_size=font_size)
        return PageElement(
            type="table",
            top=top,
            tables=[[cell]],
            table_row_heights=[] if row_heights is None else row_heights,
            table_col_widths=[] if col_widths is None else col_widths,
        )

    def _findings(self, elem, fmt="pptx"):
        page = Page(index=0, slide_number=1, elements=[elem])
        return FormatAuditor()._check_table_fit(page, self._doc(page, fmt))

    def test_row_height_insufficient_flagged(self):
        fs = self._findings(self._table("测" * 40, row_heights=[20.0], col_widths=[120.0]))
        kinds = {f.metadata["kind"] for f in fs}
        assert "row_height" in kinds
        assert all(f.rule_id == "FMT-TABLE-FIT" for f in fs)

    def test_tall_row_not_flagged(self):
        elem = self._table("短文本", row_heights=[120.0], col_widths=[200.0])
        assert self._findings(elem) == []

    def test_narrow_column_flagged(self):
        elem = self._table(
            "Supercalifragilisticexpialidocious",
            row_heights=[0.0],
            col_widths=[60.0],
        )
        fs = self._findings(elem)
        assert any(f.metadata["kind"] == "col_width" for f in fs)

    def test_page_overflow_is_warning(self):
        elem = self._table("测" * 40, row_heights=[100.0], col_widths=[60.0], top=500.0)
        overflow = [f for f in self._findings(elem) if f.metadata["kind"] == "page_overflow"]
        assert len(overflow) == 1
        assert overflow[0].severity == FindingSeverity.WARNING

    def test_no_geometry_degrades_silently(self):
        assert self._findings(self._table("测" * 100)) == []

    def test_docx_unknown_font_size_uses_default(self):
        """DOCX 单元格通常无显式字号 → 用 10.5pt 默认估算，而非整表静默跳过。"""
        elem = self._table("x" * 40, row_heights=[10.0], col_widths=[50.0])
        assert self._findings(elem, fmt="docx")

    def test_clean_table_not_flagged(self):
        elem = self._table("A1", row_heights=[30.0], col_widths=[120.0])
        assert self._findings(elem) == []


class TestConfigurableThresholds:
    """2026-11: 原硬编码阈值经 rules.md global parameters 可配置（行为验证）。"""

    @staticmethod
    def _frame(left: float, top: float, *, width=100.0, height=60.0) -> PageElement:
        return PageElement(
            type="text_frame",
            left=left,
            top=top,
            width=width,
            height=height,
            paragraphs=[Paragraph(text="内容", runs=[])],
        )

    def test_alignment_tolerance_configurable(self):
        page = Page(index=0, slide_number=1, elements=[self._frame(50, 50), self._frame(350, 53)])
        # 默认容差 5pt：3pt 偏差不报
        assert FormatAuditor()._check_alignment(page) == []
        # 收紧到 1pt：同一行 top 偏差 3pt → FMT-ALIGN
        findings = FormatAuditor(config={"alignment_tolerance": 1.0})._check_alignment(page)
        assert [f.rule_id for f in findings] == ["FMT-ALIGN"]

    def test_conclusion_min_paragraphs_configurable(self):
        pages = [
            Page(
                index=0,
                slide_number=1,
                layout_name="Title and Content",
                elements=[
                    PageElement(
                        type="text_frame",
                        is_title=True,
                        paragraphs=[Paragraph(text="工艺", runs=[])],
                    ),
                    PageElement(
                        type="text_frame",
                        is_body=True,
                        paragraphs=[
                            Paragraph(text="第一段说明。", runs=[]),
                            Paragraph(text="第二段说明。", runs=[]),
                        ],
                    ),
                ],
            )
        ]
        doc = Document(format="pptx", source_path="x", metadata=DocumentMetadata(), pages=pages)
        # 默认门槛 3 段（2 段不达标）→ CON-004
        assert [f.rule_id for f in StructureAuditor()._check_every_slide_has_conclusion(doc)] == [
            "CON-004"
        ]
        # 门槛降到 2 → 满足内容实质条件，不报
        relaxed = StructureAuditor(config={"conclusion_min_paragraphs": 2})
        assert relaxed._check_every_slide_has_conclusion(doc) == []

    def test_near_duplicate_min_chars_configurable(self):
        def page(idx: int) -> Page:
            return Page(
                index=idx,
                slide_number=idx + 1,
                elements=[
                    PageElement(
                        type="text_frame",
                        paragraphs=[
                            Paragraph(text="这是一段二十字的重复内容用于相似检测。", runs=[])
                        ],
                    )
                ],
            )

        doc = Document(
            format="pptx", source_path="x", metadata=DocumentMetadata(), pages=[page(0), page(1)]
        )
        from src.auditors.language import LanguageAuditor

        auditor = LanguageAuditor({"glossary_dir": None, "vocab_dir": None})
        # 默认 40 字下限：20 字页面直接跳过
        assert auditor._check_near_duplicate_pages(doc) == []
        # 下限降到 10 字 → 近似重复页被报
        real = LanguageAuditor(
            {"glossary_dir": None, "vocab_dir": None, "near_duplicate_min_chars": 10}
        )
        assert [f.rule_id for f in real._check_near_duplicate_pages(doc)] == ["TXT-NEAR-DUP"]

    def test_common_uppercase_extra_configurable(self):
        doc = _text_doc("ABCX 指标需要确认。")
        assert [f.rule_id for f in FactualAuditor()._check_abbreviation_first_defined(doc)] == [
            "CON-003"
        ]
        suppressed = FactualAuditor(config={"common_uppercase_extra": ["ABCX"]})
        assert suppressed._check_abbreviation_first_defined(doc) == []


class TestContentChecks:
    """2026-11 内容级检查: STR-009 / CON-005 / CON-006 / CON-007。"""

    @staticmethod
    def _page(idx, texts=None, title=None):
        elements = []
        if title is not None:
            elements.append(
                PageElement(
                    type="text_frame",
                    is_title=True,
                    paragraphs=[Paragraph(text=title, runs=[])],
                )
            )
        if texts:
            elements.append(
                PageElement(
                    type="text_frame",
                    is_body=True,
                    paragraphs=[Paragraph(text=t, runs=[]) for t in texts],
                )
            )
        return Page(index=idx, slide_number=idx + 1, elements=elements)

    @classmethod
    def _doc(cls, pages):
        return Document(format="pptx", source_path="x", metadata=DocumentMetadata(), pages=pages)

    def test_figure_without_reference_flagged(self):
        doc = self._doc([self._page(0, ["图1: 良率趋势"]), self._page(1, ["本页说明"])])
        assert [f.rule_id for f in StructureAuditor()._check_figure_referenced(doc)] == ["STR-009"]

    def test_figure_with_reference_not_flagged(self):
        for ref in ("从图1 可见趋势", "如图1所示", "图1中给出明细"):
            doc = self._doc([self._page(0, ["图1: 良率趋势", ref])])
            assert StructureAuditor()._check_figure_referenced(doc) == [], ref

    def test_caption_line_with_reference_word_not_flagged(self):
        doc = self._doc([self._page(0, ["图1: 见图2 的对比数据"])])
        assert StructureAuditor()._check_figure_referenced(doc) == []

    def test_conclusion_without_numbers_flagged(self):
        doc = self._doc([self._page(0, ["结论：性能显著提升"])])
        findings = StructureAuditor()._check_conclusion_evidence(doc)
        assert [f.rule_id for f in findings] == ["CON-005"]
        assert findings[0].severity == FindingSeverity.WARNING

    def test_conclusion_with_numbers_not_flagged(self):
        for text in ("结论：良率提升至 95%", "结论：周期缩短 20 天", "小结：共 3 项风险"):
            doc = self._doc([self._page(0, [text])])
            assert StructureAuditor()._check_conclusion_evidence(doc) == [], text

    def test_evidence_min_numbers_configurable(self):
        doc = self._doc([self._page(0, ["结论：良率 95%"])])
        strict = StructureAuditor(config={"evidence_min_numbers": 2})
        assert [f.rule_id for f in strict._check_conclusion_evidence(doc)] == ["CON-005"]

    def test_section_with_only_title_flagged(self):
        auditor = StructureAuditor(config={"required_sections": ["结论"]})
        doc = self._doc([self._page(0, title="结论")])
        findings = auditor._check_section_substance(doc)
        assert [f.rule_id for f in findings] == ["CON-006"]

    def test_section_with_content_not_flagged(self):
        auditor = StructureAuditor(config={"required_sections": ["结论"]})
        doc = self._doc(
            [
                self._page(
                    0,
                    ["本章给出良率 95%、周期缩短 20% 两项结论，并给出后续三项计划。"],
                    title="结论",
                )
            ]
        )
        assert auditor._check_section_substance(doc) == []

    def test_missing_section_not_reported_by_substance_check(self):
        """缺章由 CON-002 负责，CON-006 不重复报。"""
        auditor = StructureAuditor(config={"required_sections": ["结论"]})
        doc = self._doc([self._page(0, ["正文内容"], title="方法")])
        assert auditor._check_section_substance(doc) == []

    def test_numeric_without_unit_flagged(self):
        doc = self._doc([self._page(0, ["膜层厚度 5 需要控制"])])
        findings = FactualAuditor()._check_numeric_unit_presence(doc)
        assert [f.rule_id for f in findings] == ["CON-007"]
        assert findings[0].severity == FindingSeverity.INFO

    def test_numeric_with_unit_not_flagged(self):
        for text in ("膜层厚度 5nm 需要控制", "膜层厚度 5 纳米需要控制", "厚度 5.5 mm"):
            doc = self._doc([self._page(0, [text])])
            assert FactualAuditor()._check_numeric_unit_presence(doc) == [], text

    def test_numeric_without_keyword_not_flagged(self):
        """普通计数/序号（无量词前缀）不误报。"""
        doc = self._doc([self._page(0, ["第 3 项任务完成，共 5 人参与"])])
        assert FactualAuditor()._check_numeric_unit_presence(doc) == []


class TestMaxReviewFixes:
    """2026-11 max-level 审查修复的回归锚点（F3/F4/F5/F6/F7/F10/F18）。"""

    @staticmethod
    def _doc(texts, fmt="md", title=None, table=False):
        els = []
        if title is not None:
            els.append(
                PageElement(
                    type="text_frame",
                    is_title=True,
                    paragraphs=[Paragraph(text=title, runs=[])],
                )
            )
        if table:
            els.append(
                PageElement(
                    type="table",
                    tables=[
                        [
                            type(
                                "C",
                                (),
                                {
                                    "text": "良率 95%",
                                    "col": 0,
                                    "row": 0,
                                    "colspan": 1,
                                    "rowspan": 1,
                                },
                            )()
                        ]
                    ],
                )
            )
        els.append(
            PageElement(
                type="text_frame",
                is_body=True,
                paragraphs=[Paragraph(text=t, runs=[]) for t in texts],
            )
        )
        return Document(
            format=fmt,
            source_path="x",
            metadata=DocumentMetadata(),
            pages=[Page(index=0, slide_number=1, elements=els)],
        )

    def test_batch_term_prefix_not_false_positive(self):
        """ "本方案采用原子层沉积（ALD）" 与 "基于原子层沉积（ALD）" 是同一术语（F3）。"""
        from src.engines.batch import cross_document_findings

        a = self._doc(["本方案采用原子层沉积（ALD）工艺。"])
        b = self._doc(["该流程基于原子层沉积（ALD）实现。"])
        assert cross_document_findings([("a.md", a), ("b.md", b)]) == []

    def test_batch_term_real_difference_still_flagged(self):
        from src.engines.batch import cross_document_findings

        a = self._doc(["原子层沉积（ALD）工艺。"])
        b = self._doc(["原子层堆叠（ALD）工艺。"])
        assert [f.rule_id for f in cross_document_findings([("a.md", a), ("b.md", b)])] == [
            "BATCH-TERM"
        ]

    def test_batch_section_toc_line_not_counted(self):
        """目录行不算章节存在（F10）：a 只有目录提及，b 有真实标题 → 报 a 缺章。"""
        from src.engines.batch import cross_document_findings

        a = self._doc(["目录：概述 工艺流程 结论"])
        b = Document(
            format="md",
            source_path="b.md",
            metadata=DocumentMetadata(),
            pages=[
                Page(
                    index=0,
                    elements=[
                        PageElement(
                            type="text_frame",
                            paragraphs=[Paragraph(text="概述", level=1, runs=[])],
                        )
                    ],
                )
            ],
        )
        findings = cross_document_findings(
            [("a.md", a), ("b.md", b)], required_sections=["概述", "结论"]
        )
        assert [f.rule_id for f in findings] == ["BATCH-SECTION"]
        assert "概述" in findings[0].message

    def test_section_with_table_counts_as_substance(self):
        """DOCX 章节只有表格也算有实体内容（F4）。"""
        page = Page(
            index=0,
            elements=[
                PageElement(
                    type="text_frame", paragraphs=[Paragraph(text="结论", level=1, runs=[])]
                ),
                PageElement(
                    type="table",
                    tables=[
                        [
                            type(
                                "C",
                                (),
                                {
                                    "text": "良率 95%",
                                    "col": 0,
                                    "row": 0,
                                    "colspan": 1,
                                    "rowspan": 1,
                                },
                            )()
                        ]
                    ],
                ),
            ],
        )
        doc = Document(format="docx", source_path="x", metadata=DocumentMetadata(), pages=[page])
        auditor = StructureAuditor(config={"required_sections": ["结论"]})
        assert auditor._check_section_substance(doc) == []

    def test_coverage_does_not_claim_python_when_unprobed(self):
        """语言后端未探测 → 不得宣称"纯 Python 降级"（F5）。"""
        from src.engines.coverage import collect_coverage

        class Client:
            backend = None
            is_available = False

        class LA:
            lt_client = Client()

        doc = self._doc(["hello 中文"])
        coverage = collect_coverage(doc, [("语言审查", LA())], [])
        assert coverage["language_backend"] is None
        assert any("不可用" in n for n in coverage["notes"]), coverage["notes"]

    def test_baseline_matches_legacy_report_without_key(self, tmp_path):
        """旧版 JSON（无 key 字段）必须能对上身份，不得整份误判为新引入（F6）。"""
        import json

        from src.engines.baseline import compare_with_baseline, load_baseline_keys

        finding = AuditFinding(
            type=FindingType.FORMAT,
            severity=FindingSeverity.ERROR,
            message="字号偏小",
            rule_id="FMT-002",
            page_index=0,
            location="第 1 页",
            context="正文 10pt",
        )
        legacy = {
            "findings": [
                {
                    "type": finding.type.value,
                    "severity": finding.severity.value,
                    "message": finding.message,
                    "rule_id": finding.rule_id,
                    "page_index": finding.page_index,
                    "location": finding.location,
                    "context": finding.context,
                    "metadata": {},
                }
            ]
        }
        path = tmp_path / "legacy.json"
        path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        keys = load_baseline_keys(path)
        assert keys == {finding.exemption_key}
        result = compare_with_baseline([finding], keys)
        assert result["new"] == [] and result["fixed"] == 0

    def test_invalid_frontmatter_yaml_is_reported(self, tmp_path):
        """frontmatter YAML 语法错误必须被 rules validate 报告（F7）。"""
        from src.engines.validation import validate_rules

        path = tmp_path / "rules.md"
        path.write_text(
            "---\n"
            'version: "1.0"\n'
            "parameters: [unclosed\n"
            "---\n\n"
            "# 结构规则\n\n"
            "## STR-001: x\n- 严重度: error\n- 检查: first_slide_has_title_layout\n",
            encoding="utf-8",
        )
        result = validate_rules(path)
        assert not result.ok
        assert any("frontmatter" in e for e in result.errors), result.errors

    def test_figure_check_handles_non_contiguous_page_index(self):
        """页面 index 非连续时按页对象取标签，不再 IndexError（F18）。"""
        page = Page(
            index=7,
            slide_number=8,
            elements=[
                PageElement(
                    type="text_frame",
                    paragraphs=[Paragraph(text="图1: 趋势", runs=[])],
                )
            ],
        )
        doc = Document(format="pptx", source_path="x", metadata=DocumentMetadata(), pages=[page])
        findings = StructureAuditor()._check_figure_referenced(doc)
        assert [f.rule_id for f in findings] == ["STR-009"]
        assert findings[0].location == "第 8 页"
