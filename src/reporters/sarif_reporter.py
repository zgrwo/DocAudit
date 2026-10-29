"""SARIF 2.1.0 报告生成器 — 对接 GitHub Code Scanning / VS Code SARIF Viewer。

完全离线：只做本地格式转换，不发任何网络请求。
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from src import __version__
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity
from src.reporters.ordering import _sort_findings

logger = logging.getLogger(__name__)

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"

# SARIF level 词表: error | warning | note | none
_LEVEL_BY_SEVERITY = {
    FindingSeverity.ERROR: "error",
    FindingSeverity.WARNING: "warning",
    FindingSeverity.INFO: "note",
}


@lru_cache(maxsize=256)
def _artifact_uri(path: str | None, base: str | Path | None = None) -> str:
    """将文件路径转为 SARIF artifactLocation.uri。

    传入 base (如仓库根) 时优先输出**相对路径**——GitHub Code Scanning 需要
    仓库相对 URI 才能把结果关联到文件；不在 base 下的路径回退 file:// URI
    （本地 SARIF Viewer 可直接打开）。相对路径/异常路径原样返回 posix 形式。
    """
    if not path:
        return "unknown"
    p = Path(path)
    if base is not None:
        try:
            rel = p.resolve().relative_to(Path(base).resolve()).as_posix()
            # 相对 URI 同样必须编码：空格/中文/`#`/`%` 否则非法或错指文件
            return quote(rel, safe="/")
        except (OSError, ValueError):
            pass  # 不在基准目录下或路径无效 → 回退 file URI
    try:
        return p.resolve().as_uri()
    except (OSError, ValueError):
        return p.as_posix()


def generate_sarif_report(
    doc: Document,
    findings: list[AuditFinding],
    output_path: str | Path | None = None,
    uri_base: str | Path | None = None,
) -> str:
    """生成 SARIF v2.1.0 报告 (JSON 文本)。

    Args:
        doc: 统一文档模型 (提供默认 artifact 路径与工具元数据)
        findings: 审查发现列表；批量 finding 优先用 metadata["source_file"]
        output_path: 可选输出文件路径
        uri_base: 可选 artifact 路径基准目录；提供时输出相对路径
            （CI 传仓库根，如 "."），用于 GitHub Code Scanning 关联文件
    """
    ordered = _sort_findings(findings)

    # 规则去重并稳定排序；defaultConfiguration.level 取该规则出现过的最高严重度
    rule_levels: dict[str, str] = {}
    for f in ordered:
        rid = f.rule_id or "GENERAL"
        level = _LEVEL_BY_SEVERITY.get(f.severity, "note")
        _update_worst_level(rule_levels, rid, level)
    rule_ids = sorted(rule_levels)
    rule_index = {rid: idx for idx, rid in enumerate(rule_ids)}

    rules = [
        {
            "id": rid,
            "name": rid,
            "shortDescription": {"text": f"DocAudit 规则 {rid}"},
            "defaultConfiguration": {"level": rule_levels[rid]},
        }
        for rid in rule_ids
    ]

    results = []
    for f in ordered:
        rid = f.rule_id or "GENERAL"
        message = f.message or ""
        if f.context:
            message = f"{message} — {f.context}"
        result: dict = {
            "ruleId": rid,
            "ruleIndex": rule_index[rid],
            "level": _LEVEL_BY_SEVERITY.get(f.severity, "note"),
            "message": {"text": message},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": _artifact_uri(
                                (f.metadata or {}).get("source_file") or doc.source_path,
                                uri_base,
                            )
                        }
                    }
                }
            ],
            "partialFingerprints": {"docAuditFinding/v1": f.exemption_key},
            "properties": {
                "findingType": f.type.value,
                "severity": f.severity.value,
            },
        }
        if f.page_index is not None:
            result["properties"]["page"] = f.page_index + 1
        if f.location:
            result["properties"]["humanLocation"] = f.location
        if f.suggestion:
            result["properties"]["suggestion"] = f.suggestion
        results.append(result)

    report = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "DocAudit",
                        "informationUri": "https://github.com/zgrwo/DocAudit",
                        "version": __version__,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if output_path:
        output_path = Path(output_path)
        try:
            output_path.write_text(text, encoding="utf-8")
        except OSError as e:
            logger.warning("SARIF 报告写入失败: %s — %s", output_path, e)
    return text


def _update_worst_level(levels: dict[str, str], rule_id: str, level: str) -> None:
    """保留最高严重度 (error > warning > note)。"""
    rank = {"error": 0, "warning": 1, "note": 2}
    current = levels.get(rule_id)
    if current is None or rank.get(level, 9) < rank.get(current, 9):
        levels[rule_id] = level
