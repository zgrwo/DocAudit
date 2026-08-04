"""术语一致性检查引擎 — 基于 YAML 术语表的正则匹配"""

import re
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

import yaml

from src.models.finding import AuditFinding, FindingSeverity, FindingType

logger = logging.getLogger(__name__)

# Severity string → FindingSeverity 映射
_SEVERITY_MAP = {
    "error": FindingSeverity.ERROR,
    "warning": FindingSeverity.WARNING,
    "info": FindingSeverity.INFO,
}


@dataclass
class TermRule:
    """单个术语规则"""
    pattern: str                       # 正则表达式
    preferred: str                     # 推荐写法
    context: str = ""                  # 术语说明
    severity: str = "error"            # error | warning | info
    compiled: re.Pattern | None = None # 编译后的正则

    def __post_init__(self):
        try:
            self.compiled = re.compile(self.pattern, re.IGNORECASE)
        except re.error as e:
            logger.warning("术语规则编译失败: %s — %s", self.pattern, e)
            self.compiled = None


@dataclass
class TermGlossary:
    """术语表"""
    category: str
    version: str
    terms: list[TermRule] = field(default_factory=list)


def _already_preferred(
    text: str, match_start: int, match_end: int, preferred: str
) -> bool:
    """检查匹配位置附近是否已使用推荐的术语形式。

    策略：
    1. 提取 preferred 中的搜索词: 有括号则取缩写 (如 "TSV")，否则取全词
    2. 在匹配位置前后 60 字符的窗口内用单词边界匹配搜索
    3. 若搜索词存在 → 说明文档已使用推荐形式 → 应跳过
    """
    # 提取搜索词:
    # "TSV (Through Silicon Via)"  → "TSV" (取括号前)
    # "Through Silicon Via (TSV)"  → "TSV" (括号前太长则取括号内)
    # "use"                        → "use"
    search_term = preferred.split("(")[0].strip() if "(" in preferred else preferred.strip()
    # 如果 search_term 太长（多个词），尝试从括号内提取缩写
    if "(" in preferred and ")" in preferred and len(search_term.split()) > 2:
        inner = preferred.split("(")[1].split(")")[0].split(",")[0].strip()
        if inner and len(inner) >= 2:
            search_term = inner
    if not search_term or len(search_term) < 2:
        return False
    # 在匹配位置周围用单词边界搜索 (避免 "NA" 误匹配 "NANO")
    window_start = max(0, match_start - 60)
    window_end = min(len(text), match_end + 60)
    window = text[window_start:window_end]
    return bool(re.search(
        r"\b" + re.escape(search_term) + r"\b", window, re.IGNORECASE
    ))


class TerminologyChecker:
    """基于术语表的术语一致性检查器"""

    def __init__(self, glossary_dir: str | Path | None = None):
        self.glossaries: list[TermGlossary] = []
        if glossary_dir:
            self.load_glossaries(glossary_dir)

    def load_glossaries(self, glossary_dir: str | Path) -> None:
        """加载目录下的所有 YAML 术语表"""
        directory = Path(glossary_dir)
        for yaml_file in directory.glob("*.yaml"):
            try:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                glossary = self._parse_glossary(data)
                if glossary:
                    self.glossaries.append(glossary)
                    logger.info("加载术语表: %s (%d 条规则)",
                                glossary.category, len(glossary.terms))
            except Exception as e:
                logger.warning("术语表加载失败: %s — %s", yaml_file.name, e)

    def _parse_glossary(self, data: dict) -> TermGlossary | None:
        """解析 YAML 术语表"""
        if not data or "terms" not in data:
            return None

        rules: list[TermRule] = []
        for item in data.get("terms", []):
            if not isinstance(item, dict):
                continue
            pattern = item.get("pattern", "")
            if not pattern:
                continue

            rules.append(TermRule(
                pattern=pattern,
                preferred=item.get("preferred", ""),
                context=item.get("context", ""),
                severity=item.get("severity", "warning"),
            ))

        return TermGlossary(
            category=data.get("category", "未分类"),
            version=data.get("version", "1.0"),
            terms=rules,
        )

    def check(self, text: str, page_index: int = 0, page_label: str = "") -> list[AuditFinding]:
        """对文本执行术语一致性检查"""
        findings: list[AuditFinding] = []

        for glossary in self.glossaries:
            for rule in glossary.terms:
                if rule.compiled is None:
                    continue
                for match in rule.compiled.finditer(text):
                    matched_text = match.group(0)
                    # 跳过已被推荐写法覆盖的情况
                    # 策略: 从 preferred 中提取缩写 (如 "TSV"), 检查匹配位置
                    # 附近是否已使用该缩写 — 若已用完整推荐形式则跳过
                    if rule.preferred and _already_preferred(
                        text, match.start(), match.end(), rule.preferred
                    ):
                        continue

                    severity = _SEVERITY_MAP.get(rule.severity, FindingSeverity.INFO)

                    findings.append(AuditFinding(
                        type=FindingType.TERMINOLOGY,
                        severity=severity,
                        message=f"术语用法不规范: 「{matched_text}」",
                        rule_id=f"TERM-{glossary.category}",
                        page_index=page_index,
                        location=page_label or f"第 {page_index+1} 页",
                        context=matched_text[:150],
                        suggestion=rule.preferred or rule.context,
                        metadata={
                            "glossary": glossary.category,
                            "context_note": rule.context,
                        },
                    ))

        return findings
