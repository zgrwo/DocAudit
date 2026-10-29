"""豁免持久化 (.docauditignore) — 跨会话 / 跨机器复用误报豁免。

格式 (JSON，版本化，可入库与评审):

```json
{
  "version": 1,
  "tool": "DocAudit",
  "exemptions": [
    {
      "key": "9f2c…",            // 稳定 exemption_key (唯一真相)
      "rule_id": "FMT-001",
      "page": 3,                  // 1-based，仅辅助阅读
      "location": "第 3 页",
      "message": "…",
      "reason": ""
    }
  ]
}
```

读取时只信任 `key` 字段；元数据仅供人工审阅。文件缺失 → 空集合；
文件损坏 → 记 warning 并返回空集合（宁可多报问题，不可静默漏报）。
"""

import json
import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from src.models.finding import AuditFinding

logger = logging.getLogger(__name__)

DEFAULT_EXEMPTION_FILE = ".docauditignore"
_FORMAT_VERSION = 1


def load_exemptions(path: str | Path = DEFAULT_EXEMPTION_FILE) -> set[str]:
    """读取豁免键集合。缺失/损坏文件返回空集合（fail-open 到"多报"）。"""
    p = Path(path)
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("豁免文件读取失败，忽略其内容: %s — %s", p, e)
        return set()
    return _extract_keys(data)


def save_exemptions(
    path: str | Path,
    keys: Iterable[str],
    findings: list[AuditFinding] | None = None,
) -> None:
    """把豁免键写入文件 (附带 finding 元数据便于人工评审)。

    Args:
        path: 输出路径
        keys: 要保留的 exemption_key 集合
        findings: 可选，用于补齐 rule_id/location/message 元数据
    """
    key_set = {str(k) for k in keys}
    by_key = {f.exemption_key: f for f in (findings or [])}
    entries = []
    for key in sorted(key_set):
        f = by_key.get(key)
        entry = {"key": key}
        if f is not None:
            entry["rule_id"] = f.rule_id
            entry["location"] = f.location
            entry["message"] = (f.message or "")[:200]
            if f.page_index is not None:
                entry["page"] = f.page_index + 1
        entries.append(entry)

    payload = {
        "version": _FORMAT_VERSION,
        "tool": "DocAudit",
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "exemptions": entries,
    }
    p = Path(path)
    try:
        p.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("豁免文件写入失败: %s — %s", p, e)


def apply_exemptions(
    findings: list[AuditFinding], keys: set[str]
) -> tuple[list[AuditFinding], int]:
    """过滤掉已豁免 finding，返回 (保留列表, 豁免条数)。"""
    if not keys:
        return findings, 0
    kept = [f for f in findings if f.exemption_key not in keys]
    return kept, len(findings) - len(kept)


def _extract_keys(data) -> set[str]:
    """兼容多种形态: {"exemptions": [...]} / 裸列表；元素可为 str 或 {"key": …}。"""
    entries = data.get("exemptions", []) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return set()
    keys: set[str] = set()
    for entry in entries:
        if isinstance(entry, str) and entry:
            keys.add(entry)
        elif isinstance(entry, dict) and entry.get("key"):
            keys.add(str(entry["key"]))
    return keys
