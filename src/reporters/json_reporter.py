"""JSON 报告导出器"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src import __version__
from src.models.document import Document
from src.models.finding import AuditFinding

logger = logging.getLogger(__name__)


def generate_json_report(
    doc: Document,
    findings: list[AuditFinding],
    output_path: str | Path | None = None,
    *,
    score: dict | None = None,
    coverage: dict | None = None,
) -> dict:
    """生成 JSON 格式审查报告。

    Args:
        doc: 统一文档模型。
        findings: 发现列表。
        output_path: 可选输出路径。
        score: ``compute_score()`` 结果（质量分）；None 时不输出该键（向后兼容）。
        coverage: ``collect_coverage()`` 结果（审查范围/降级声明）。
    """
    report = {
        "meta": {
            "tool": "DocAudit",
            "version": __version__,
            "timestamp": datetime.now().isoformat(),
            "source_file": doc.source_path,
            "format": doc.format,
        },
        "document": {
            "title": doc.metadata.title,
            "author": doc.metadata.author,
            "page_count": len(doc.pages),
            "slide_count": doc.metadata.slide_count,
            "word_count": doc.metadata.word_count,
        },
        "summary": {
            "total_findings": len(findings),
            "errors": sum(1 for f in findings if f.severity.value == "error"),
            "warnings": sum(1 for f in findings if f.severity.value == "warning"),
            "info": sum(1 for f in findings if f.severity.value == "info"),
            "by_type": {},
            # 质量分（0-100 + 等级）— 2026-11 新增
            "score": score["score"] if score else None,
            "grade": score["grade"] if score else None,
        },
        # key = 稳定 exemption_key（跨版本/跨文件唯一），供 --baseline 对比
        "findings": [dict(f.to_dict(), key=f.exemption_key) for f in findings],
    }
    if score:
        report["score"] = score
    if coverage:
        report["coverage"] = coverage

    # 按类型统计
    for f in findings:
        t = f.type.value
        report["summary"]["by_type"][t] = report["summary"]["by_type"].get(t, 0) + 1

    # 写入文件
    if output_path:
        output_path = Path(output_path)
        try:
            output_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("JSON 报告写入失败: %s — %s", output_path, e)

    return report
