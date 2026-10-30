"""审查覆盖与可信度声明 — 让报告能区分"没问题"和"没查"。

2026-11 新增（审查报告可信度）：

- 语言检查后端（Docker / Java / 纯 Python tier-3）决定语法检查能力边界；
- 检查是否因文档格式而不适用（PPTX-only 检查对 DOCX/PDF/MD 不执行）；
- 规则/审计器执行失败（SYS-ERROR）意味着"这个维度没查成"，不能当成通过；
- 估算类发现（溢出/表格 fit/DPI）不是精确测量，需人工复核。

所有信息都是运行时事实推导，不外发、不联网。
"""

from __future__ import annotations

from src.engines.check_registry import CHECK_REGISTRY
from src.models.document import Document
from src.models.finding import AuditFinding

_BACKEND_LABELS = {
    "docker": "Docker LanguageTool（完整语法/风格检查）",
    "java": "Java LanguageTool（完整语法/风格检查）",
    "python": "纯 Python 降级（仅拼写 + 中文正则，语法/风格覆盖有限）",
}
_FORMAT_LABELS = {
    "pptx": "PPTX（版面/几何信息可用）",
    "docx": "DOCX（语义分页，无版面坐标）",
    "pdf": "PDF（文本/标题级，视后端可能无表格与字体）",
    "md": "Markdown（纯文本，无格式/版面信息）",
}


def _language_backend(auditors) -> tuple[str | None, bool]:
    """返回 (后端名, 是否可用)；无语言审计器时 (None, False)。"""
    for name, auditor in auditors:
        if name != "语言审查":
            continue
        client = getattr(auditor, "lt_client", None)
        if client is None:
            return None, False
        # 未探测（backend=None）不得冒充 tier-3：只报告事实（2026-11 max 审查 F5）
        backend = getattr(client, "backend", None)
        return (str(backend) if backend else None), bool(getattr(client, "is_available", False))
    return None, False


def _has_language_auditor(auditors) -> bool:
    return any(name == "语言审查" for name, _auditor in auditors)


def _has_geometry(doc: Document) -> bool:
    for page in doc.pages:
        for elem in page.flattened_elements:
            if elem.left is not None or elem.top is not None:
                return True
    return False


def _has_font_metadata(doc: Document) -> bool:
    for page in doc.pages:
        for elem in page.flattened_elements:
            for para in elem.paragraphs:
                for run in para.runs:
                    if run.font_name or run.font_size:
                        return True
    return False


def collect_coverage(doc: Document, auditors, findings: list[AuditFinding]) -> dict:
    """汇总本次审查的执行范围与降级信息（供报告/CLI/Web UI 展示）。"""
    backend, available = _language_backend(auditors)
    format_key = doc.format

    not_applicable = sorted(
        check_type
        for check_type, spec in CHECK_REGISTRY.items()
        if spec.pptx_only and format_key != "pptx"
    )

    sys_errors = [f for f in findings if f.rule_id == "SYS-ERROR"]
    failed_auditors = [
        {
            "auditor": (f.metadata or {}).get("auditor", "?"),
            "error": (f.metadata or {}).get("error", ""),
        }
        for f in sys_errors
    ]

    estimated = [f for f in findings if (f.metadata or {}).get("estimated")]
    estimated_rule_ids = sorted({f.rule_id or "" for f in estimated if f.rule_id})

    notes: list[str] = []
    notes.append(f"文档格式: {_FORMAT_LABELS.get(format_key, format_key)}")
    if backend:
        notes.append(f"语言检查后端: {_BACKEND_LABELS.get(backend, backend)}")
    elif available:
        notes.append("语言检查后端: 尚未探测（本次没有可检查的文本段）")
    elif _has_language_auditor(auditors):
        notes.append("语言检查后端: 不可用（语法/风格检查未执行，仅中文内置规则生效）")
    else:
        notes.append("语言检查后端: 未执行（无语言审计器）")
    if not _has_geometry(doc):
        notes.append("无版面坐标：溢出/对齐/页脚/表格 fit 等版面类检查不适用")
    if not _has_font_metadata(doc):
        notes.append("无字体元数据：字体/字号检查不适用")
    if not_applicable:
        notes.append(f"PPTX 专属检查未执行: {', '.join(not_applicable)}")
    if failed_auditors:
        names = "、".join(sorted({item["auditor"] for item in failed_auditors}))
        notes.append(f"执行失败（结果不完整）: {names}")
    if estimated_rule_ids:
        notes.append(f"估算类发现需人工复核: {', '.join(estimated_rule_ids)}")
    if doc.format == "pdf":
        pdf_backend = (doc.metadata.custom_properties or {}).get("pdf_backend")
        if pdf_backend:
            notes.append(f"PDF 后端: {pdf_backend}")

    return {
        "format": format_key,
        "pages": len(doc.pages),
        "language_backend": backend,
        "language_available": available,
        "geometry": _has_geometry(doc),
        "font_metadata": _has_font_metadata(doc),
        "not_applicable_checks": not_applicable,
        "failed_auditors": failed_auditors,
        "estimated_findings": len(estimated),
        "estimated_rule_ids": estimated_rule_ids,
        "complete": not failed_auditors,
        "notes": notes,
    }


def format_coverage_lines(coverage: dict) -> list[str]:
    """把 coverage 渲染成 CLI 文本行（报告/CLI 共用同一来源）。"""
    lines = []
    status = "完整" if coverage.get("complete") else "不完整（有检查执行失败）"
    lines.append(
        f"审查范围: {_FORMAT_LABELS.get(coverage.get('format'), coverage.get('format'))}"
        f"，{coverage.get('pages', 0)} 页；执行状态: {status}"
    )
    for note in coverage.get("notes", []):
        lines.append(f"  - {note}")
    return lines
