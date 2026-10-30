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
import os
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from src.models.finding import AuditFinding

logger = logging.getLogger(__name__)

DEFAULT_EXEMPTION_FILE = ".docauditignore"
_FORMAT_VERSION = 1


def _read_text_with_fallback(path: Path) -> str:
    """utf-8-sig → gbk → replace（与 rules/glossary/vocab 加载器一致）。

    2026-10-29 深度审查修复：豁免文件原只按 utf-8 读取，中文 Windows 记事本/
    PowerShell 保存的 GBK 文件会抛未捕获 UnicodeDecodeError（CLI 零报告退出、
    Web UI 启动失败）；带 BOM 则 json 解析失败被当损坏、豁免全部静默失效。
    """
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def load_exemptions(path: str | Path = DEFAULT_EXEMPTION_FILE) -> set[str]:
    """读取**未过期**的豁免键集合。缺失/损坏文件返回空集合（fail-open 到"多报"）。

    2026-11: 条目可带 ``expires``（YYYY-MM-DD）。过期条目不再生效，使"临时豁免"
    不会永久掩盖已修复/应复查的问题；过期条目由 :func:`exemption_stats` 统计。
    """
    return {entry["key"] for entry in load_exemption_entries(path) if not _is_expired(entry)}


def load_exemption_entries(path: str | Path = DEFAULT_EXEMPTION_FILE) -> list[dict]:
    """读取全部豁免条目（不做过期过滤；每项至少含 key）。"""
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(_read_text_with_fallback(p))
    except (OSError, ValueError) as e:  # UnicodeDecodeError 是 ValueError 子类
        logger.warning("豁免文件读取失败，忽略其内容: %s — %s", p, e)
        return []
    return _extract_entries(data)


def _is_expired(entry: dict, today: str | None = None) -> bool:
    """``expires`` 早于今天即过期；缺失/非法值视为不过期（fail-open 到保持豁免）。"""
    expires = str(entry.get("expires") or "").strip()
    if not expires:
        return False
    today = today or datetime.now().strftime("%Y-%m-%d")
    return expires < today


def exemption_stats(path: str | Path = DEFAULT_EXEMPTION_FILE) -> dict:
    """豁免条目统计：总数 / 生效 / 已过期（CLI/UI 提示"是否该复查"）。"""
    entries = load_exemption_entries(path)
    expired = sum(1 for entry in entries if _is_expired(entry))
    return {
        "total": len(entries),
        "active": len(entries) - expired,
        "expired": expired,
        "path": str(path),
    }


def save_exemptions(
    path: str | Path,
    keys: Iterable[str],
    findings: list[AuditFinding] | None = None,
    *,
    reviewer: str | None = None,
    expires: str | None = None,
) -> bool:
    """把豁免键写入文件 (附带 finding 元数据便于人工评审)。

    Args:
        path: 输出路径
        keys: 要保留的 exemption_key 集合
        findings: 可选，用于补齐 rule_id/location/message 元数据
        reviewer: 可选，豁免评审人（写入 ``reviewer``，供审计）
        expires: 可选，过期日期 ``YYYY-MM-DD``（过期后豁免自动失效）

    Returns:
        True = 写入成功；False = 写入失败（调用方必须提示用户，不能显示「已保存」）
    """
    key_set = {str(k) for k in keys}
    by_key = {f.exemption_key: f for f in (findings or [])}
    today = datetime.now().strftime("%Y-%m-%d")
    entries = []
    for key in sorted(key_set):
        f = by_key.get(key)
        entry = {"key": key, "created": today}
        if f is not None:
            entry["rule_id"] = f.rule_id
            entry["location"] = f.location
            entry["message"] = (f.message or "")[:200]
            if f.page_index is not None:
                entry["page"] = f.page_index + 1
        if reviewer:
            entry["reviewer"] = reviewer
        if expires:
            entry["expires"] = expires
        entries.append(entry)

    payload = {
        "version": _FORMAT_VERSION,
        "tool": "DocAudit",
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "exemptions": entries,
    }
    p = Path(path)
    # 原子写 (2026-10-29): 先写临时文件再 os.replace，避免中断时留下半截 JSON
    tmp = p.with_name(p.name + ".tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, p)
        return True
    except OSError as e:
        logger.warning("豁免文件写入失败: %s — %s", p, e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass  # bare-handler-ok — 清理临时文件失败不影响主流程
        return False


def apply_exemptions(
    findings: list[AuditFinding], keys: set[str]
) -> tuple[list[AuditFinding], int]:
    """过滤掉已豁免 finding，返回 (保留列表, 豁免条数)。"""
    if not keys:
        return findings, 0
    kept = [f for f in findings if f.exemption_key not in keys]
    return kept, len(findings) - len(kept)


def _extract_entries(data) -> list[dict]:
    """兼容多种形态，统一成 ``[{"key": ..., 其余元数据}]``（保序）。"""
    entries = data.get("exemptions", []) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return []
    result: list[dict] = []
    for entry in entries:
        if isinstance(entry, str) and entry:
            result.append({"key": entry})
        elif isinstance(entry, dict) and entry.get("key"):
            normalized = dict(entry)
            normalized["key"] = str(entry["key"])
            result.append(normalized)
    return result
