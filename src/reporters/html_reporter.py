"""HTML 报告生成器"""

import logging
from datetime import datetime
from html import escape
from pathlib import Path

from src import __version__
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity
from src.reporters.ordering import _group_by_source, _sort_findings

logger = logging.getLogger(__name__)

# 缩略图上限 (防止超大文档报告膨胀)
_MAX_THUMBNAIL_PAGES = 80
_MAX_RECTS_PER_PAGE = 200
_MAX_RECTS_TOTAL = 3000
_THUMBNAIL_TYPES = ("text_frame", "table", "image", "chart")


def generate_html_report(
    doc: Document,
    findings: list[AuditFinding],
    title: str = "文档审查报告",
    output_path: str | Path | None = None,
    file_label: str | None = None,
    page_count: int | None = None,
    show_thumbnails: bool = True,
) -> str:
    """生成独立 HTML 审查报告。

    Args:
        doc: 统一文档模型
        findings: 审查发现列表
        title: 报告标题
        output_path: 可选输出文件路径 (与 JSON reporter API 对称)
        file_label: 可选文件来源标签 (批量模式传 "批量 N 个文件"，
                    避免头部只显示第一个文件的路径误导)
        page_count: 可选总页数覆盖 (批量模式传聚合页数 sum(len(d.pages))；
                    None 时保持现状取 len(doc.pages)，向后兼容)
        show_thumbnails: 是否渲染页面 SVG 线框缩略图 (批量聚合报告应传 False，
                    否则只反映首个文件的页面几何)
    """

    # 按严重度统计
    error_count = sum(1 for f in findings if f.severity == FindingSeverity.ERROR)
    warning_count = sum(1 for f in findings if f.severity == FindingSeverity.WARNING)
    info_count = sum(1 for f in findings if f.severity == FindingSeverity.INFO)

    # 按类型统计
    type_counts = {}
    for f in findings:
        type_name = f.type.value
        type_counts[type_name] = type_counts.get(type_name, 0) + 1

    findings_html = _render_findings(findings)
    thumbnails_html = _render_thumbnails(doc) if show_thumbnails else ""

    # P6: page_count 覆盖总页数 (批量模式传聚合页数)，None 时保持现状取 len(doc.pages)
    total_pages = len(doc.pages) if page_count is None else page_count

    # 按类型分布（2026-10-29）: 让用户一眼看出问题集中在结构/格式/语言/术语
    _type_labels = {
        "structure": "结构",
        "format": "格式",
        "language": "语言",
        "terminology": "术语",
        "factual": "事实",
        "custom": "自定义",
        "system": "系统",
    }
    type_stats = " · ".join(
        f"{_type_labels.get(name, name)} {count}"
        for name, count in sorted(type_counts.items(), key=lambda kv: -kv[1])
    )
    type_stats_html = (
        f'<p class="type-stats">按类型: {escape(type_stats)}</p>' if type_stats else ""
    )

    thumbnails_section = (
        f"""
    <h2 style="margin-bottom:8px">页面缩略图</h2>
    <p style="color:#888;font-size:12px;margin-bottom:12px">
        🔵 文本框 · 🟢 表格 · 🟠 图片 · 🟣 图表（线框示意，非渲染效果）
    </p>
    {thumbnails_html}
"""
        if thumbnails_html
        else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(title)} — {escape(doc.metadata.title or doc.source_path)}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; color: #333; background: #f5f5f5; }}
    .container {{ max-width: 960px; margin: 0 auto; padding: 24px; }}
    .header {{ background: #1e3a5f; color: white; padding: 32px 24px; border-radius: 8px; margin-bottom: 24px; }}
    .header h1 {{ font-size: 24px; margin-bottom: 8px; }}
    .header p {{ opacity: 0.85; font-size: 14px; }}
    .stats {{ display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }}
    .stat-card {{ background: white; padding: 16px 24px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); flex: 1; min-width: 120px; text-align: center; }}
    .stat-card .num {{ font-size: 28px; font-weight: bold; }}
    .stat-card .label {{ font-size: 13px; color: #888; margin-top: 4px; }}
    .stat-card.error .num {{ color: #d32f2f; }}
    .stat-card.warning .num {{ color: #f57c00; }}
    .stat-card.info .num {{ color: #1976d2; }}
    .finding {{ background: white; padding: 16px; border-radius: 8px; margin-bottom: 12px; border-left: 4px solid #ccc; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
    .finding.error {{ border-left-color: #d32f2f; }}
    .finding.warning {{ border-left-color: #f57c00; }}
    .finding.info {{ border-left-color: #1976d2; }}
    .finding-header {{ display: flex; justify-content: space-between; align-items: start; margin-bottom: 8px; }}
    .finding-severity {{ font-size: 12px; padding: 2px 8px; border-radius: 4px; color: white; font-weight: 500; }}
    .finding-severity.error {{ background: #d32f2f; }}
    .finding-severity.warning {{ background: #f57c00; }}
    .finding-severity.info {{ background: #1976d2; }}
    .finding-message {{ font-size: 15px; margin-bottom: 8px; }}
    .finding-location {{ font-size: 12px; color: #888; margin-bottom: 4px; }}
    .finding-context {{ background: #f5f5f5; padding: 8px 12px; border-radius: 4px; font-family: monospace; font-size: 13px; margin-bottom: 4px; white-space: pre-wrap; }}
    .finding-suggestion {{ color: #2e7d32; font-size: 13px; }}
    .rule-id {{ font-size: 11px; color: #aaa; }}
    .file-group {{ margin: 24px 0 12px; font-size: 16px; }}
    .file-group .count {{ font-weight: normal; color: #888; font-size: 13px; }}
    .type-stats {{ color: #666; font-size: 13px; margin: -12px 0 24px; }}
    .thumbs {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }}
    .thumb {{ margin: 0; }}
    .thumb svg {{ width: 170px; height: auto; background: #fff; border: 1px solid #e0e0e0; border-radius: 4px; }}
    .thumb figcaption {{ font-size: 11px; color: #888; text-align: center; margin-top: 4px; }}
    .thumb .page {{ fill: #fff; stroke: #ddd; }}
    .thumb .el-text_frame {{ fill: #cfe3ff; stroke: #1976d2; stroke-width: 1; }}
    .thumb .el-table {{ fill: #d9f2d9; stroke: #2e7d32; stroke-width: 1; }}
    .thumb .el-image {{ fill: #ffe0b2; stroke: #f57c00; stroke-width: 1; }}
    .thumb .el-chart {{ fill: #e1bee7; stroke: #7b1fa2; stroke-width: 1; }}
    .footer {{ text-align: center; padding: 32px; color: #aaa; font-size: 12px; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📄 {escape(title)}</h1>
        <p>文件: {escape(file_label or doc.source_path)} | 格式: {escape(doc.format.upper())} | 共 {total_pages} 页</p>
        <p>审查时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
    </div>

    <div class="stats">
        <div class="stat-card error">
            <div class="num">{error_count}</div>
            <div class="label">🔴 严重问题</div>
        </div>
        <div class="stat-card warning">
            <div class="num">{warning_count}</div>
            <div class="label">🟡 警告</div>
        </div>
        <div class="stat-card info">
            <div class="num">{info_count}</div>
            <div class="label">🔵 提示</div>
        </div>
        <div class="stat-card">
            <div class="num">{len(findings)}</div>
            <div class="label">📋 总计</div>
        </div>
    </div>
{type_stats_html}
{thumbnails_section}
    <h2 style="margin-bottom:16px">审查发现</h2>
    {findings_html if findings_html else '<p style="color:#888">🎉 未发现任何问题！</p>'}
</div>
<div class="footer">DocAudit v{__version__} · 本地离线审查 · {datetime.now().year}</div>
</body>
</html>"""

    # 可选写入文件 (与 JSON reporter API 对称)
    if output_path:
        output_path = Path(output_path)
        try:
            output_path.write_text(html, encoding="utf-8")
        except OSError as e:
            logger.warning("HTML 报告写入失败: %s — %s", output_path, e)

    return html


def _render_findings(findings: list[AuditFinding]) -> str:
    """将 findings 渲染为 HTML 片段。

    排序: severity → 页码 → rule_id → message (与 CSV/SARIF 共用 SSOT)。
    批量模式 (finding 带 metadata["source_file"]) 按文件分组，组内保持同一排序。
    """
    if not findings:
        return ""

    ordered = _sort_findings(findings)
    groups = _group_by_source(ordered)
    named = [source for source in groups if source]
    if len(named) <= 1:
        return "\n".join(_render_finding(f) for f in ordered)

    parts: list[str] = []
    for source in sorted(groups):
        items = groups[source]
        errors = sum(1 for f in items if f.severity == FindingSeverity.ERROR)
        warnings = sum(1 for f in items if f.severity == FindingSeverity.WARNING)
        infos = sum(1 for f in items if f.severity == FindingSeverity.INFO)
        label = source or "（未标注来源）"
        parts.append(
            f'<h3 class="file-group">📁 {escape(label)} '
            f'<span class="count">({len(items)} 条 · 🔴{errors} 🟡{warnings} 🔵{infos})</span></h3>'
        )
        parts.extend(_render_finding(f) for f in items)
    return "\n".join(parts)


def _render_finding(f: AuditFinding) -> str:
    """单个 finding 的 HTML 片段 (所有用户文本均已 html.escape)。"""
    sev_class = f.severity.value
    sev_label = {"error": "严重", "warning": "警告", "info": "提示"}.get(sev_class, sev_class)

    return f"""
<div class="finding {sev_class}">
    <div class="finding-header">
        <span class="finding-severity {sev_class}">{sev_label}</span>
        <span class="rule-id">{escape(f.rule_id or "")}</span>
    </div>
    <div class="finding-message">{escape(f.message or "")}</div>
    {f'<div class="finding-location">📍 {escape(f.location)}</div>' if f.location else ""}
    {f'<div class="finding-context">{escape(f.context)}</div>' if f.context else ""}
    {f'<div class="finding-suggestion">💡 {escape(f.suggestion)}</div>' if f.suggestion else ""}
</div>"""


def _render_thumbnails(doc: Document) -> str:
    """为有几何信息的页面渲染内联 SVG 线框缩略图。

    仅示意元素位置与类型 (非渲染效果)；页数/单页元素数/总元素数均有上限，
    避免超大文档把报告撑到数十 MB。
    """
    props = (doc.metadata.custom_properties or {}) if doc.metadata else {}
    try:
        page_w = float(props.get("slide_width") or 960)
        page_h = float(props.get("slide_height") or 540)
    except (TypeError, ValueError):
        page_w, page_h = 960.0, 540.0
    if page_w <= 0 or page_h <= 0:
        page_w, page_h = 960.0, 540.0

    figures: list[str] = []
    total_rects = 0
    for page in doc.pages[:_MAX_THUMBNAIL_PAGES]:
        rects: list[str] = []
        for elem in page.flattened_elements:
            if len(rects) >= _MAX_RECTS_PER_PAGE:
                break
            if elem.type not in _THUMBNAIL_TYPES:
                continue
            if elem.left is None or elem.top is None or not elem.width or not elem.height:
                continue
            x = max(0.0, min(float(elem.left), page_w))
            y = max(0.0, min(float(elem.top), page_h))
            w = min(float(elem.width), page_w - x)
            h = min(float(elem.height), page_h - y)
            if w <= 0 or h <= 0:
                continue
            label = escape(str(elem.shape_name or elem.type))
            rects.append(
                f'<rect class="el-{elem.type}" x="{x:.1f}" y="{y:.1f}" '
                f'width="{w:.1f}" height="{h:.1f}"><title>{label}</title></rect>'
            )
        if not rects:
            continue
        total_rects += len(rects)
        page_no = page.slide_number or page.index + 1
        figures.append(
            f'<figure class="thumb">'
            f'<svg viewBox="0 0 {page_w:.0f} {page_h:.0f}" role="img" '
            f'aria-label="第 {page_no} 页线框">'
            f'<rect class="page" x="0" y="0" width="{page_w:.0f}" height="{page_h:.0f}"/>'
            f"{''.join(rects)}</svg>"
            f"<figcaption>第 {page_no} 页</figcaption></figure>"
        )
        if total_rects >= _MAX_RECTS_TOTAL:
            break

    if not figures:
        return ""
    return '<div class="thumbs">' + "".join(figures) + "</div>"
