"""CSV 报告生成器 — 供 Excel / 数据透视表二次分析。

安全说明：单元格文本来自被审查文档（不可信输入）。Excel/WPS 会把以
`= + - @` 开头的单元格当公式执行（CSV 注入），这里统一加单引号前缀。
"""

import csv
import io
import logging
from pathlib import Path

from src.models.finding import AuditFinding
from src.reporters.ordering import _sort_findings

logger = logging.getLogger(__name__)

CSV_FIELDS = [
    "rule_id",
    "severity",
    "type",
    "page",
    "location",
    "message",
    "context",
    "suggestion",
    "source_file",
    "exemption_key",
]

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value) -> str:
    """防 CSV 公式注入：危险前缀加单引号，其余原样。"""
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def generate_csv_report(
    findings: list[AuditFinding],
    output_path: str | Path | None = None,
) -> str:
    """生成 CSV 报告 (UTF-8 BOM，便于 Excel 识别中文)。

    Args:
        findings: 审查发现列表
        output_path: 可选输出文件路径
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(CSV_FIELDS)
    for f in _sort_findings(findings):
        writer.writerow(
            [
                _csv_safe(f.rule_id or ""),
                _csv_safe(f.severity.value),
                _csv_safe(f.type.value),
                "" if f.page_index is None else f.page_index + 1,
                _csv_safe(f.location),
                _csv_safe(f.message),
                _csv_safe(f.context),
                _csv_safe(f.suggestion),
                _csv_safe((f.metadata or {}).get("source_file")),
                _csv_safe(f.exemption_key),
            ]
        )
    text = buffer.getvalue()

    if output_path:
        output_path = Path(output_path)
        try:
            # utf-8-sig: 带 BOM，Excel 直接打开不乱码
            output_path.write_text(text, encoding="utf-8-sig")
        except OSError as e:
            logger.warning("CSV 报告写入失败: %s — %s", output_path, e)
    return text
