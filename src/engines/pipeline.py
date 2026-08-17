"""共享审计流水线 — app.py 和 cli.py 的单一真相来源"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.auditors import (
    CustomRulesAuditor,
    FactualAuditor,
    FormatAuditor,
    LanguageAuditor,
    StructureAuditor,
)
from src.auditors.base import BaseAuditor
from src.converters import DocxConverter, MarkdownConverter, PdfConverter, PptxConverter
from src.engines.rule_parser import extract_auditor_config, parse_rules_md
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity, FindingType

logger = logging.getLogger(__name__)

CONVERTERS = [PptxConverter(), DocxConverter(), PdfConverter(), MarkdownConverter()]

# 支持的文档扩展名 (app.py scan_folder 和 cli.py 批量扫描共用)
SUPPORTED_EXTENSIONS = {".pptx", ".ppt", ".docx", ".doc", ".pdf", ".md", ".markdown", ".txt"}

# _skip_checks 内部简写 → _DISPATCH check_type 映射 (单一真相来源，供 tests 守卫引用)
# StructureAuditor: title_slide→first_slide_has_title_layout,
#   heading_levels→heading_level_sequential, figure_numbering→figure_numbering_sequential,
#   every_slide_conclusion→every_slide_has_conclusion
# FactualAuditor: numeric_consistency→numeric_cross_reference
# 其余键名与 _DISPATCH check_type 一致
SKIP_TO_CHECK_TYPE = {
    "title_slide": "first_slide_has_title_layout",
    "heading_levels": "heading_level_sequential",
    "figure_numbering": "figure_numbering_sequential",
    "every_slide_conclusion": "every_slide_has_conclusion",
    "numeric_consistency": "numeric_cross_reference",
}


def find_converter(file_path: str) -> Any | None:
    """自动匹配文件对应的转换器，无匹配返回 None"""
    for cvt in CONVERTERS:
        if cvt.can_handle(file_path):
            return cvt
    return None


def build_auditors(rules_path: str, glossary_dir: str, vocab_dir: str | None = None) -> list[tuple[str, BaseAuditor]]:
    """从 rules.md 构建配置好的审计器列表。

    Returns: list of (name, auditor) tuples.
    """
    rules = parse_rules_md(rules_path)
    config = extract_auditor_config(rules)
    if vocab_dir is None:
        # vocab/ is sibling to glossary/ in the project directory
        glossary_path = Path(glossary_dir).resolve()
        derived = glossary_path.parent / "vocab"
        if not derived.exists():
            logger.debug("vocab 目录不存在，跳过词汇表检查: %s", derived)
        vocab_dir = str(derived)

    # 构建各审计器实例 (使用 .get() 防御，避免 extract_auditor_config 未来重构时 KeyError)
    structure_auditor = StructureAuditor(config={
        "required_sections": config.get("required_sections", []),
        "conclusion_keywords": config.get("conclusion_keywords", [
            "结论", "小结", "总结", "要点", "关键", "建议", "展望",
            "Summary", "Conclusion", "Key", "Takeaway", "Recommend",
        ]),
        "exempt_layouts": config.get("exempt_layouts", []),
        "max_english_words": config.get("max_english_words", 10),
        "max_chinese_chars_title": config.get("max_chinese_chars_title", 40),
        "min_title_font_size": config.get("min_title_font_size", 28),
        # 跳过已由 CustomRulesAuditor dispatch 的检查，避免双重执行
        "_skip_checks": [
            "title_slide",
            "heading_levels",
            "figure_numbering",
            "every_slide_conclusion",
            "duplicate_title",
            "title_trailing_punctuation",
            "figure_caption_format",
            "slide_structure_consistency",
            "title_length",
        ],
    })
    format_auditor = FormatAuditor(config={
        "allowed_fonts": config.get("allowed_fonts", ["微软雅黑", "Arial", "Calibri", "Noto Sans SC"]),
        "title_size_range": config.get("title_size_range", (28, 40)),
        "body_size_range": config.get("body_size_range", (12, 22)),
        "max_chinese_chars": config.get("max_chinese_chars", 150),
        "max_english_chars": config.get("max_english_chars", 300),
        "max_explicit_newlines": config.get("max_explicit_newlines", 3),
        "max_chars_per_page": config.get("max_chars_per_page", 200),
        "min_contrast": config.get("min_contrast", 4.5),
        "large_text_min_contrast": config.get("large_text_min_contrast", 3.0),
        "large_text_threshold": config.get("large_text_threshold", 18),
        "_skip_checks": ["element_overflow", "per_page_char_limit", "empty_placeholder", "bullet_consistency", "table_contrast"],
    })
    language_auditor = LanguageAuditor(config={
        "glossary_dir": glossary_dir,
        "vocab_dir": vocab_dir,
    })
    factual_auditor = FactualAuditor(config={
        "_skip_checks": ["numeric_consistency", "abbreviation_first_defined",
                         "abbreviation_defined_never_used", "abbreviation_multiply_defined",
                         "abbreviation_used_before_defined"],
    })
    custom_rules_auditor = CustomRulesAuditor(config={"rules_path": rules_path})

    # 将主流水线审计器注入 CustomRulesAuditor，消除重复创建和重复执行
    custom_rules_auditor.set_delegate_auditors(
        structure_auditor=structure_auditor,
        format_auditor=format_auditor,
        factual_auditor=factual_auditor,
    )

    return [
        ("结构审查", structure_auditor),
        ("格式审查", format_auditor),
        ("语言审查", language_auditor),
        ("事实审查", factual_auditor),
        ("自定义规则", custom_rules_auditor),
    ]


def run_auditors(
    doc: Document,
    auditors: list[tuple[str, BaseAuditor]],
    on_progress: Callable[[str, int, int], None] | None = None,
) -> list[AuditFinding]:
    """顺序执行所有审计器，返回去重后的发现列表。

    Args:
        doc: 统一文档模型
        auditors: build_auditors() 返回的 list of (name, auditor)
        on_progress: optional callback(name, index, total) — 在审计器执行前调用
    """
    all_findings: list[AuditFinding] = []
    total = len(auditors)
    for i, (name, auditor) in enumerate(auditors):
        # 执行前回调 — 告知 UI 当前正在运行哪个审计器
        if on_progress:
            on_progress(name, i, total)
        try:
            findings = auditor.audit(doc)
            all_findings.extend(findings)
        except Exception as e:
            logger.warning("%s 执行失败: %s", name, e, exc_info=True)
            # 生成 error-level AuditFinding 确保 UI 层可见
            all_findings.append(AuditFinding(
                type=FindingType.CUSTOM,
                severity=FindingSeverity.ERROR,
                message=f"审计器 '{name}' 执行失败: {e}",
                rule_id="SYS-ERROR",
                location="系统",
                suggestion="请检查相关依赖是否正常（如 LanguageTool 服务、Java 环境等）",
                metadata={"auditor": name, "error": str(e)},
            ))
    # 全部完成回调
    if on_progress:
        on_progress("完成", total, total)
    return AuditFinding.deduplicate(all_findings)
