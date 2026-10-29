"""报告共用排序 (SSOT)：error → warning → info → 页码 → rule_id → message。

HTML / CSV / SARIF 三种报告共用同一顺序，避免同一批发现因报告格式不同
而顺序漂移（也保证批量报告按文件分组时组内顺序稳定）。
"""

from src.models.finding import AuditFinding

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _sort_findings(findings: list[AuditFinding]) -> list[AuditFinding]:
    """返回按报告展示顺序排序的新列表 (不修改入参)。"""
    return sorted(
        findings,
        key=lambda f: (
            _SEVERITY_ORDER.get(f.severity.value, 3),
            f.page_index if f.page_index is not None else -1,
            f.rule_id or "",
            f.message or "",
        ),
    )


def _group_by_source(findings: list[AuditFinding]) -> dict[str, list[AuditFinding]]:
    """按 metadata["source_file"] 分组 (批量模式)；无来源的文件归入空串键。"""
    groups: dict[str, list[AuditFinding]] = {}
    for f in findings:
        source = (f.metadata or {}).get("source_file") or ""
        groups.setdefault(source, []).append(f)
    return groups
