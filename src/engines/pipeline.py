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
from src.engines.auditor_config import build_auditor_configs
from src.engines.check_registry import CHECK_REGISTRY
from src.engines.rule_parser import extract_auditor_config, parse_rules_globals, parse_rules_md
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
    globals_ = parse_rules_globals(rules_path)
    config = extract_auditor_config(rules, globals_)
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

    # 配置装配唯一真相来源 (src/engines/auditor_config.py): 与 CustomRulesAuditor
    # 回退路径共用同一份键集，避免"两份手工 dict 漂移"(特检 #4)。
    configs = build_auditor_configs(
        config,
        enabled_rule_ids=enabled_rule_ids,
        skip_checks={
            "sa": CustomRulesAuditor.skip_checks_for("sa"),
            "fa": CustomRulesAuditor.skip_checks_for("fa"),
            "fca": CustomRulesAuditor.skip_checks_for("fca"),
        },
        glossary_dir=glossary_dir,
        vocab_dir=vocab_dir,
    )

    structure_auditor = StructureAuditor(config=configs["sa"])
    format_auditor = FormatAuditor(config=configs["fa"])
    language_auditor = LanguageAuditor(config=configs["la"])
    factual_auditor = FactualAuditor(config=configs["fca"])
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


def build_report_context(
    doc: Document,
    auditors: list[tuple[str, BaseAuditor]],
    findings: list[AuditFinding],
) -> dict:
    """汇总报告所需的派生信息：质量分 + 覆盖/降级声明（2026-11）。

    唯一真相来源：CLI / Web UI / HTML / JSON 报告都从这里取，避免各自计算
    导致"报告分数与摘要不一致"。
    """
    from src.engines.coverage import collect_coverage
    from src.engines.scoring import compute_score

    return {
        "score": compute_score(findings, len(doc.pages)),
        "coverage": collect_coverage(doc, auditors, findings),
    }
