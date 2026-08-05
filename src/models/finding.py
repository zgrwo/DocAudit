"""审查发现 (Finding) 数据模型"""

import hashlib
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FindingSeverity(str, Enum):
    """审查发现严重度"""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class FindingType(str, Enum):
    """审查发现类型"""
    STRUCTURE = "structure"      # 结构问题
    FORMAT = "format"            # 格式问题
    LANGUAGE = "language"        # 语言问题
    TERMINOLOGY = "terminology"  # 术语问题
    FACTUAL = "factual"          # 事实精准问题
    CUSTOM = "custom"            # 自定义规则


@dataclass
class AuditFinding:
    """审查发现 — 单个审查问题的完整描述"""

    type: FindingType
    severity: FindingSeverity
    message: str
    rule_id: str | None = None            # 规则 ID (如 "STR-001")
    page_index: int | None = None         # 所在页/幻灯片 (0-indexed)
    element_index: int | None = None      # 所在页内元素索引
    context: str | None = None            # 相关原文摘录
    suggestion: str | None = None         # 修改建议
    location: str | None = None           # 人类可读位置描述 (如 "Slide 3, 文本框 2")
    metadata: dict[str, Any] = field(default_factory=dict)

    # 内部唯一标识
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "severity": self.severity.value,
            "message": self.message,
            "rule_id": self.rule_id,
            "page_index": self.page_index,
            "element_index": self.element_index,
            "context": self.context,
            "suggestion": self.suggestion,
            "location": self.location,
            "metadata": self.metadata,
        }

    @property
    def dedup_key(self) -> str:
        """去重键：相同检查+相同位置+相同类型+相同上下文前缀 → 视为重复。

        包含 context 前 120 字符的哈希，区分同页同规则但不同实体的发现。
        """
        page_key = self.page_index if self.page_index is not None else -1
        ctx_hash = int.from_bytes(
            hashlib.md5((self.context or "")[:120].encode()).digest()[:4], "little"
        )
        return f"{self.type.value}|{self.rule_id or ''}|{page_key}|{ctx_hash:08x}"

    @staticmethod
    def deduplicate(findings: list["AuditFinding"]) -> list["AuditFinding"]:
        """移除重复发现（保留严重度更高的版本）"""
        seen: dict[str, AuditFinding] = {}
        sev_rank = {FindingSeverity.ERROR: 3, FindingSeverity.WARNING: 2, FindingSeverity.INFO: 1}
        for f in findings:
            key = f.dedup_key
            # sev_rank missing key → -1 确保未知严重度不会被错误保留
            if key not in seen or sev_rank.get(f.severity, -1) > sev_rank.get(seen[key].severity, -1):
                seen[key] = f
        return list(seen.values())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditFinding":
        if "type" not in data or "severity" not in data or not data.get("message"):
            raise ValueError(
                f"Missing required keys in finding data: "
                f"type={'present' if 'type' in data else 'MISSING'}, "
                f"severity={'present' if 'severity' in data else 'MISSING'}, "
                f"message={'present' if data.get('message') else 'MISSING'}"
            )
        return cls(
            id=data.get("id", uuid.uuid4().hex[:12]),
            type=FindingType(data["type"]),
            severity=FindingSeverity(data["severity"]),
            message=data["message"],
            rule_id=data.get("rule_id"),
            page_index=data.get("page_index"),
            element_index=data.get("element_index"),
            context=data.get("context"),
            suggestion=data.get("suggestion"),
            location=data.get("location"),
            metadata=data.get("metadata", {}),
        )
