"""HTML 报告生成器"""

import logging
from datetime import datetime
from html import escape
from pathlib import Path

from src import __version__
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity

logger = logging.getLogger(__name__)


def generate_html_report(
    doc: Document,
    findings: list[AuditFinding],
    title: str = "文档审查报告",
    output_path: str | Path | None = None,
    file_label: str | None = None,
) -> str:
    """生成独立 HTML 审查报告。

    Args:
        doc: 统一文档模型
        findings: 审查发现列表
        title: 报告标题
        output_path: 可选输出文件路径 (与 JSON reporter API 对称)
        file_label: 可选文件来源标签 (批量模式传 "批量 N 个文件"，
                    避免头部只显示第一个文件的路径误导)
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

    findings_html = _render_findings(findings, doc)

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
    .footer {{ text-align: center; padding: 32px; color: #aaa; font-size: 12px; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📄 {escape(title)}</h1>
        <p>文件: {escape(file_label or doc.source_path)} | 格式: {escape(doc.format.upper())} | 共 {len(doc.pages)} 页</p>
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


def _render_findings(findings: list[AuditFinding], doc: Document) -> str:
    """将 findings 渲染为 HTML 片段"""
    if not findings:
        return ""

    parts: list[str] = []
    for f in findings:
        sev_class = f.severity.value
        sev_label = {"error": "严重", "warning": "警告", "info": "提示"}.get(sev_class, sev_class)

        parts.append(f"""
<div class="finding {sev_class}">
    <div class="finding-header">
        <span class="finding-severity {sev_class}">{sev_label}</span>
        <span class="rule-id">{escape(f.rule_id or "")}</span>
    </div>
    <div class="finding-message">{escape(f.message or "")}</div>
    {f'<div class="finding-location">📍 {escape(f.location)}</div>' if f.location else ""}
    {f'<div class="finding-context">{escape(f.context)}</div>' if f.context else ""}
    {f'<div class="finding-suggestion">💡 {escape(f.suggestion)}</div>' if f.suggestion else ""}
</div>""")

    return "\n".join(parts)
