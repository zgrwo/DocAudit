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
) -> dict:
    """生成 JSON 格式审查报告"""
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
        },
        "findings": [f.to_dict() for f in findings],
    }

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
