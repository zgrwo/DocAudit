"""Auditor 配置装配 — pipeline 与 CustomRulesAuditor 回退路径的单一真相来源。

历史上 `pipeline.build_auditors` 与 `custom_rules._create_auditor` 各写一份配置
dict，靠注释约定"键集必须一致"（特检 #4 的"回退路径键漂移"风险）。现统一到本
模块：两处只负责实例化，配置键只在 `build_auditor_configs` 定义一次。

本模块是 Engine 层纯数据装配，不 import 任何 Auditor（避免 Engine→Auditor 反向
依赖，也避免与 custom_rules 循环导入）；需要 `_skip_checks` 时由调用方传入。
"""

from __future__ import annotations

from typing import Any

# 统一默认值（与 rules.md 全局参数默认值保持一致，见 rule_parser.GLOBAL_PARAM_SPECS）
_DEFAULTS: dict[str, Any] = {
    "required_sections": [],
    "required_sections_severity": "error",
    "conclusion_keywords": [
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
    "max_english_words": 10,
    "max_chinese_chars_title": 40,
    "min_title_font_size": 28,
    "conclusion_min_paragraphs": 3,
    "evidence_min_numbers": 1,
    "section_min_paragraphs": 1,
    "section_min_chars": 20,
    "allowed_fonts": ["微软雅黑", "Arial", "Calibri", "Noto Sans SC"],
    "title_size_range": (28, 44),
    "body_size_range": (12, 32),
    "max_chinese_chars": 150,
    "max_english_chars": 300,
    "max_explicit_newlines": 3,
    "max_chars_per_page": 200,
    "min_contrast": 4.5,
    "large_text_min_contrast": 3.0,
    "large_text_threshold": 18,
    # 全局阈值（rules.md frontmatter `parameters:`；未声明时即下列历史值）
    "alignment_tolerance": 5.0,
    "max_font_types": 3,
    "near_duplicate_similarity": 0.90,
    "near_duplicate_min_chars": 40,
    "table_fit_height_ratio": 1.15,
    "table_fit_min_excess_pt": 6.0,
    "table_fit_col_ratio": 1.05,
    "table_fit_col_min_excess_pt": 2.0,
    "table_margin_pt_pptx": 7.2,
    "table_margin_pt_docx": 5.4,
    "text_overflow_height_ratio": 1.15,
    "text_overflow_min_excess_pt": 8.0,
    "image_min_dpi": 150.0,
    "numeric_length_units": ["nm", "μm", "um", "mm", "cm", "m"],
    "common_uppercase_extra": [],
}

_SA_KEYS = (
    "required_sections",
    "required_sections_severity",
    "conclusion_keywords",
    "exempt_layouts",
    "max_english_words",
    "max_chinese_chars_title",
    "min_title_font_size",
    "conclusion_min_paragraphs",
    "evidence_min_numbers",
    "section_min_paragraphs",
    "section_min_chars",
)
_FA_KEYS = (
    "allowed_fonts",
    "title_size_range",
    "body_size_range",
    "max_chinese_chars",
    "max_english_chars",
    "max_explicit_newlines",
    "max_chars_per_page",
    "min_contrast",
    "large_text_min_contrast",
    "large_text_threshold",
    "rule_severities",
    "exempt_layouts",
    "enabled_rule_ids",
    "alignment_tolerance",
    "max_font_types",
    "table_fit_height_ratio",
    "table_fit_min_excess_pt",
    "table_fit_col_ratio",
    "table_fit_col_min_excess_pt",
    "table_margin_pt_pptx",
    "table_margin_pt_docx",
    "text_overflow_height_ratio",
    "text_overflow_min_excess_pt",
    "image_min_dpi",
)
_LA_KEYS = (
    "near_duplicate_similarity",
    "near_duplicate_min_chars",
)
_FCA_KEYS = (
    "numeric_length_units",
    "common_uppercase_extra",
    "unit_keywords",
)


def build_auditor_configs(
    config: dict[str, Any],
    *,
    enabled_rule_ids: set[str] | None = None,
    skip_checks: dict[str, list[str]] | None = None,
    glossary_dir: str | None = None,
    vocab_dir: str | None = None,
) -> dict[str, dict[str, Any]]:
    """把 ``extract_auditor_config()`` 的扁平配置拆成各 Auditor 的构造参数。

    Args:
        config: ``extract_auditor_config()`` 结果。
        enabled_rule_ids: rules.md 中声明的规则 ID（FormatAuditor 的
            `enabled_rule_ids` 门禁用；None 表示不做启用门禁）。
        skip_checks: ``{"sa": [...], "fa": [...], "fca": [...]}`` —
            pipeline 模式跳过已 dispatch 的检查；独立使用时不传（不注入该键）。
        glossary_dir / vocab_dir: LanguageAuditor / FactualAuditor 的配置目录。

    Returns:
        ``{"sa": {...}, "fa": {...}, "la": {...}, "fca": {...}}``
    """
    merged = dict(_DEFAULTS)
    merged.update({k: v for k, v in config.items() if v is not None})
    # 注意: exempt_layouts / rule_severities 允许显式 None（未声明 → 审计器用内置默认）
    if "exempt_layouts" in config:
        merged["exempt_layouts"] = config["exempt_layouts"]
    if "rule_severities" in config:
        merged["rule_severities"] = config["rule_severities"]

    skip = skip_checks or {}

    sa = {key: merged.get(key) for key in _SA_KEYS}
    if "sa" in skip:
        sa["_skip_checks"] = list(skip["sa"])

    fa = {key: merged.get(key) for key in _FA_KEYS}
    fa["rule_severities"] = merged.get("rule_severities") or {}
    if enabled_rule_ids is not None:
        fa["enabled_rule_ids"] = set(enabled_rule_ids)
    if "fa" in skip:
        fa["_skip_checks"] = list(skip["fa"])

    la: dict[str, Any] = {"glossary_dir": glossary_dir, "vocab_dir": vocab_dir}
    la.update({key: merged.get(key) for key in _LA_KEYS})
    if "languagetool_url" in config:
        la["languagetool_url"] = config["languagetool_url"]

    fca: dict[str, Any] = {"vocab_dir": vocab_dir}
    fca.update({key: merged.get(key) for key in _FCA_KEYS})
    if "fca" in skip:
        fca["_skip_checks"] = list(skip["fca"])

    return {"sa": sa, "fa": fa, "la": la, "fca": fca}
