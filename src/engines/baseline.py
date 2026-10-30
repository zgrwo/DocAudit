"""版本对比（baseline）— 与上一版报告比较"已修复 / 新引入 / 仍存在"。

用法：``docaudit report.pptx -o r.json`` 生成基线；下一版审查看
``docaudit report.pptx --baseline r.json``，输出差异并可用 ``--fail-on-new``
把"新引入的 error"变成 CI 阻断项。

身份键使用 ``exemptions.exemption_key``（与豁免文件同一套稳定哈希，含来源文件），
因此跨版本行号漂移不会把同一问题误判为"新引入"。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.models.finding import AuditFinding

logger = logging.getLogger(__name__)


def load_baseline_keys(path: str | Path) -> set[str]:
    """从 JSON 报告读取发现键集合；文件缺失/损坏返回空集合（fail-open）。"""
    baseline = Path(path)
    if not baseline.exists():
        logger.warning("baseline 文件不存在: %s", path)
        return set()
    try:
        data = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("baseline 文件无法解析: %s — %s", path, e)
        return set()

    keys: set[str] = set()
    findings = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(findings, list):
        return keys
    for item in findings:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if key:
            keys.add(str(key))
            continue
        # 兼容手工构造的 JSON（无 key 字段）：按同一 exemption_key 规则重算
        finding = AuditFinding(
            type=_type_of(item.get("type")),
            severity=_severity_of(item.get("severity")),
            message=str(item.get("message") or ""),
            rule_id=str(item.get("rule_id", "")),
            page_index=item.get("page_index"),
            location=str(item.get("location") or ""),
            # dedup_key 含 context 前 120 字哈希：旧版 JSON 无 key 时必须一并还原，
            # 否则 recompute 的键永远对不上，整份报告会被误判为"新引入"（F6）
            context=str(item.get("context") or ""),
            metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
        )
        keys.add(finding.exemption_key)
    return keys


def _type_of(value: Any):
    from src.models.finding import FindingType

    try:
        return FindingType(str(value))
    except ValueError:
        return FindingType.CUSTOM


def _severity_of(value: Any):
    from src.models.finding import FindingSeverity

    try:
        return FindingSeverity(str(value))
    except ValueError:
        return FindingSeverity.INFO


def compare_with_baseline(findings: list[AuditFinding], baseline_keys: set[str]) -> dict:
    """比较当前发现与基线键集合。

    Returns:
        ``{"fixed": int, "new": list[AuditFinding], "remaining": list[AuditFinding]}``
        （``fixed`` 只有数量：基线里已不在当前报告的条目没有 finding 可展示）
    """
    current: dict[str, AuditFinding] = {}
    for finding in findings:
        current.setdefault(finding.exemption_key, finding)

    new_keys = set(current) - baseline_keys
    remaining_keys = set(current) & baseline_keys
    return {
        "fixed": len(baseline_keys - set(current)),
        "new": [current[key] for key in sorted(new_keys)],
        "remaining": [current[key] for key in sorted(remaining_keys)],
    }


def format_baseline_summary(result: dict) -> str:
    """一行文本摘要：已修复/新引入/仍存在（含新引入的 error/warning 数）。"""
    new = result.get("new") or []
    new_errors = sum(1 for f in new if f.severity.value == "error")
    new_warnings = sum(1 for f in new if f.severity.value == "warning")
    return (
        f"已修复 {result.get('fixed', 0)} · 新引入 {len(new)}"
        f"（error {new_errors} / warning {new_warnings}） · 仍存在 {len(result.get('remaining', []))}"
    )
