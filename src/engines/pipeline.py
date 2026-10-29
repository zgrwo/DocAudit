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
from src.engines.check_registry import CHECK_REGISTRY
from src.engines.rule_parser import extract_auditor_config, parse_rules_md
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity, FindingType

logger = logging.getLogger(__name__)

CONVERTERS = [PptxConverter(), DocxConverter(), PdfConverter(), MarkdownConverter()]

# 支持的文档扩展名 (app.py scan_folder 和 cli.py 批量扫描共用)
SUPPORTED_EXTENSIONS = {".pptx", ".ppt", ".docx", ".doc", ".pdf", ".md", ".markdown", ".txt"}

# _skip_checks 内部简写 → _DISPATCH check_type 映射。
# 唯一真相来源: src/engines/check_registry.py 的 CHECK_REGISTRY（仅导出"简写与
# check_type 不同名"的项，供 tests 守卫引用）。pipeline 不再手写跳过名单。
SKIP_TO_CHECK_TYPE = {
    (spec.skip_key or check_type): check_type
    for check_type, spec in CHECK_REGISTRY.items()
    if (spec.skip_key or check_type) != check_type
}


def find_converter(file_path: str) -> Any | None:
    """自动匹配文件对应的转换器，无匹配返回 None"""
    for cvt in CONVERTERS:
        if cvt.can_handle(file_path):
            return cvt
    return None


def build_auditors(
    rules_path: str, glossary_dir: str, vocab_dir: str | None = None
) -> list[tuple[str, BaseAuditor]]:
    """从 rules.md 构建配置好的审计器列表。

    Returns: list of (name, auditor) tuples.
    """
    rules = parse_rules_md(rules_path)
    config = extract_auditor_config(rules)
    # rules.md 是格式规则启用状态的唯一入口: FMT-001/002/004 无 check_type,
    # 必须显式告知 FormatAuditor 哪些规则仍存在 (2026-10-28 修复删除规则仍执行)。
    enabled_rule_ids = {rule.rule_id for rule in rules}
    if vocab_dir is None:
        # vocab/ is sibling to glossary/ in the project directory
        glossary_path = Path(glossary_dir).resolve()
        derived = glossary_path.parent / "vocab"
        if not derived.exists():
            logger.debug("vocab 目录不存在，跳过词汇表检查: %s", derived)
        vocab_dir = str(derived)

    # 构建各审计器实例 (使用 .get() 防御，避免 extract_auditor_config 未来重构时 KeyError)
    structure_auditor = StructureAuditor(
        config={
            "required_sections": config.get("required_sections", []),
            "required_sections_severity": config.get("required_sections_severity", "error"),
            "conclusion_keywords": config.get(
                "conclusion_keywords",
                [
                    "结论",
                    "小结",
                    "总结",
                    "要点",
                    "关键",
                    "建议",
                    "展望",
                    "Summary",
                    "Conclusion",
                    "Key",
                    "Takeaway",
                    "Recommend",
                ],
            ),
            # 修复 (2026-08 审查 L10): 未声明时传 None (而非 []), 否则空列表
            # 覆盖 StructureAuditor 内置默认豁免版式
            "exempt_layouts": config.get("exempt_layouts"),
            "max_english_words": config.get("max_english_words", 10),
            "max_chinese_chars_title": config.get("max_chinese_chars_title", 40),
            "min_title_font_size": config.get("min_title_font_size", 28),
            # 跳过已由 CustomRulesAuditor dispatch 的检查，避免双重执行
            # (由 CHECK_REGISTRY 派生: 注册即跳过，漏注册不可能发生)
            "_skip_checks": CustomRulesAuditor.skip_checks_for("sa"),
        }
    )
    format_auditor = FormatAuditor(
        config={
            "allowed_fonts": config.get(
                "allowed_fonts", ["微软雅黑", "Arial", "Calibri", "Noto Sans SC"]
            ),
            "title_size_range": config.get("title_size_range", (28, 44)),
            "body_size_range": config.get("body_size_range", (12, 32)),
            "max_chinese_chars": config.get("max_chinese_chars", 150),
            "max_english_chars": config.get("max_english_chars", 300),
            "max_explicit_newlines": config.get("max_explicit_newlines", 3),
            "max_chars_per_page": config.get("max_chars_per_page", 200),
            "min_contrast": config.get("min_contrast", 4.5),
            "large_text_min_contrast": config.get("large_text_min_contrast", 3.0),
            "large_text_threshold": config.get("large_text_threshold", 18),
            # 无 check_type 的 format 规则 (FMT-001/002/004) 严重度以 rules.md 为准
            # (2026-09-06 审查 C-1); dispatch 型规则仍由 custom_rules 覆盖, 不经此处
            "rule_severities": config.get("rule_severities", {}),
            "enabled_rule_ids": enabled_rule_ids,
            "_skip_checks": CustomRulesAuditor.skip_checks_for("fa"),
        }
    )
    # languagetool_url 可选注入: rules.md 声明时传入, 未声明时由
    # LanguageAuditor 使用内置默认 (http://localhost:8010/v2)。显式传 None
    # 会覆盖默认值, 故仅在该键存在时注入。
    _language_cfg: dict[str, Any] = {
        "glossary_dir": glossary_dir,
        "vocab_dir": vocab_dir,
    }
    if "languagetool_url" in config:
        _language_cfg["languagetool_url"] = config["languagetool_url"]
    language_auditor = LanguageAuditor(config=_language_cfg)
    factual_auditor = FactualAuditor(
        config={
            "vocab_dir": vocab_dir,
            "_skip_checks": CustomRulesAuditor.skip_checks_for("fca"),
        }
    )
    custom_rules_auditor = CustomRulesAuditor(
        config={"rules_path": rules_path, "vocab_dir": vocab_dir}
    )

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
            all_findings.append(
                AuditFinding(
                    type=FindingType.SYSTEM,
                    severity=FindingSeverity.ERROR,
                    message=f"审计器 '{name}' 执行失败: {e}",
                    rule_id="SYS-ERROR",
                    location="系统",
                    context=str(e)[:120],  # 错误摘要进 dedup_key, 多条失败不折叠
                    suggestion="请检查相关依赖是否正常（如 LanguageTool 服务、Java 环境等）",
                    metadata={"auditor": name, "error": str(e)},
                )
            )
    # 全部完成回调
    if on_progress:
        on_progress("完成", total, total)
    return AuditFinding.deduplicate(all_findings)
