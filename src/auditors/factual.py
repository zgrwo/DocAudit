"""事实审查器 — 文档内部一致性检查"""

import re
from collections import defaultdict
from typing import Any

from src.auditors.base import BaseAuditor
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity, FindingType

# 常见英语大写单词 (非技术缩写)，出现在文档中时不应标记为“未定义缩写”
_COMMON_UPPERCASE_WORDS = frozenset({
    # 2 字母常见词 (扩展匹配范围后需排除)
    "OK", "AM", "PM", "GO", "DO", "IS", "IT", "WE", "HE", "MY",
    "BY", "TO", "IF", "OR", "SO", "NO", "UP", "ON", "IN", "AT",
    "OF", "AS", "BE", "AN", "ME", "US",
    # 3 字母
    "THE", "AND", "FOR", "ALL", "BUT", "NOT", "CAN", "ARE", "WAS",
    "HAS", "HAD", "NEW", "SET", "END", "TOP", "ONE", "TWO", "VIA",
    "MAY", "ANY", "NOW", "OUR", "USE", "GET", "LET", "SEE", "WAY",
    # 4 字母
    "THAT", "THIS", "THAN", "THEN", "WITH", "WHEN", "FROM", "HAVE",
    "BEEN", "WILL", "ALSO", "USED", "EACH", "SOME", "MORE", "ONLY",
    "VERY", "JUST", "WHAT", "WHICH", "THEIR", "THESE", "WHERE",
    # 5+ 字母
    "WOULD", "COULD", "SHOULD", "THERE", "THEIR", "ABOUT", "WHICH",
})

# 数值提取正则 — 仅匹配数值+可选单位，上下文通过文本切片获取
# 避免上下文捕获组吞噬相邻数值
# 单位后加 (?![a-zA-Z]) 防止 "5 m" 误匹配 "5 minutes" 中的 m
_NUMERIC_VALUE_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:%|nm|μm|kV|°[CF]|cm|mm|mV|mA|kW|MHz|GHz|V|A|W|m)?)(?![a-zA-Z])"
)

# 数值提取后剥离非数字字符 — 比固定单位列表更通用，无需与 _NUMERIC_VALUE_RE 同步


class FactualAuditor(BaseAuditor):
    """检查文档内部的一致性和逻辑性

    包括：
    1. 数值交叉验证 — 同一指标在不同位置数值是否一致
    2. 缩写首次定义检查 — 技术缩写首次出现时是否给出全称

    待实现:
    - 名称/缩写一致性 — 同一实体是否用统一的名称
    - 日期逻辑检查 — 日期序列是否合理
    """

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        cfg = config or {}
        # 流水线模式: 跳过已由 CustomRulesAuditor dispatch 的检查
        self._skip_checks: set[str] = set(cfg.get("_skip_checks", []))
        # 缩写扫描缓存 — 每次 audit() 调用时重置；独立模式 (dispatch 直调) 下
        # 以 (id(doc), result) 绑定文档身份，防止跨文档串档
        self._abbr_scan_cache: tuple | None = None

    def audit(self, doc: Document) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        skip = self._skip_checks
        self._abbr_scan_cache = None  # 每次审查重置缓存

        if "numeric_consistency" not in skip:
            findings.extend(self._check_numeric_consistency(doc))
        if "abbreviation_first_defined" not in skip:
            findings.extend(self._check_abbreviation_first_defined(doc))
        if "abbreviation_defined_never_used" not in skip:
            findings.extend(self._check_abbreviation_defined_never_used(doc))
        if "abbreviation_multiply_defined" not in skip:
            findings.extend(self._check_abbreviation_multiply_defined(doc))
        if "abbreviation_used_before_defined" not in skip:
            findings.extend(self._check_abbreviation_used_before_defined(doc))

        return findings

    # ── 数值一致性 ───────────────────────────────────────────

    def _check_numeric_consistency(self, doc: Document) -> list[AuditFinding]:
        """检查相同数值型指标在不同位置是否一致"""
        findings: list[AuditFinding] = []

        # 提取所有带上下文的数值
        numeric_entries: list[dict] = self._extract_numeric_values(doc)

        # 按相似上下文聚类
        context_groups: dict[str, list[dict]] = defaultdict(list)
        for entry in numeric_entries:
            # 用上下文窗口作为聚类 key
            key = entry["context"].lower().strip()
            # 归一化: 去掉数字
            normalized = re.sub(r"\d+", "N", key)
            context_groups[normalized].append(entry)

        for norm_key, entries in context_groups.items():
            if len(entries) < 2:
                continue

            # 检查数值是否一致
            values = set(e["value"] for e in entries)
            if len(values) > 1:
                # 发现不一致
                entries_sorted = sorted(entries, key=lambda e: e["page_index"])
                occurrences = "\n".join(
                    f"  - 第 {e['page_number']} 页: {e['match_text']}"
                    for e in entries_sorted
                )
                findings.append(AuditFinding(
                    type=FindingType.FACTUAL,
                    severity=FindingSeverity.ERROR,
                    message="数值不一致: 相同指标在不同位置出现不同的数值",
                    rule_id="CON-001",
                    page_index=entries_sorted[0]["page_index"],
                    location=f"第 {entries_sorted[0]['page_number']} 页等多处",
                    context=entries_sorted[0]["context"][:100],
                    suggestion=f"请确认正确的数值并统一修改:\n{occurrences}",
                    metadata={
                        "values": list(values),
                        "occurrences": [
                            {"page": e["page_number"], "value": e["value"]}
                            for e in entries_sorted
                        ],
                    },
                ))

        return findings

    def _extract_numeric_values(self, doc: Document) -> list[dict]:
        """提取文档中所有数值及其上下文 (过滤页码/图表编号等模板数字)"""
        entries: list[dict] = []

        for page in doc.pages:
            text = page.all_text
            for m in _NUMERIC_VALUE_RE.finditer(text):
                value_str = m.group(1).strip()
                start = m.start()
                end = m.end()

                # 提取上下文 (前后各 30 字符，避免跨越其他数值)
                prefix = text[max(0, start - 30):start].strip()
                suffix = text[end:end + 30].strip()
                context = f"{prefix} {value_str} {suffix}"

                # 页码/图表编号跳过检测: 紧邻前缀 (10 字符) + 值为纯整数
                # 旧逻辑依赖 re.sub(r"\d+", "N", prefix) 在 prefix 中找占位符 N，
                # 但 _NUMERIC_VALUE_RE 只匹配数值本身，前缀从不含数字，
                # 导致 N 永不存在 → 页码不过滤 + 远处 "Page N" 污染后续值前缀。
                # 新逻辑: 紧邻前缀含页码/图表关键词 + 值为无单位的纯整数 → 跳过。
                _narrow_prefix = text[max(0, start - 10):start].lower().strip()
                if re.match(r"^\d+$", value_str) and re.search(
                    r"(?:page|slide|fig|figure|table|tab|图|表|第)\s*\.?\s*$",
                    _narrow_prefix,
                    re.IGNORECASE,
                ):
                    continue

                try:
                    # 剥离单位/后缀后解析数值 (去除非数字字符，通用性优于固定单位列表)
                    numeric_part = re.sub(r"[^\d.]", "", value_str).strip()
                    value_float = float(numeric_part)
                except ValueError:
                    continue

                entries.append({
                    "page_index": page.index,
                    "page_number": page.slide_number or page.index + 1,
                    "context": context.strip(),
                    "value": value_float,
                    "match_text": value_str,
                })

        return entries

    # ── 缩写全生命周期扫描 (共享数据，避免多次扫描) ──────────

    def _scan_abbreviations(self, doc: Document) -> dict[str, Any]:
        """扫描文档中所有技术缩写及其每次出现。

        Returns:
            dict: {abbreviation: {
                "occurrences": [{page_index, page_number, position, context, is_definition}, ...],
                "total_count": int,
                "definition_count": int,
                "first_page": int,
                "first_page_number": int,
                "first_is_definition": bool,
            }}
        结果缓存在 self._abbr_scan_cache 中，同一次 audit 调用内复用
        (绑定 id(doc)，独立模式跨文档不串档)。
        """
        if self._abbr_scan_cache is not None and self._abbr_scan_cache[0] == id(doc):
            return self._abbr_scan_cache[1]

        abbr_pattern = re.compile(r"\b([A-Z]{2,8})\b")
        scan_result: dict = {}

        for page in doc.pages:
            text = page.all_text
            for m in abbr_pattern.finditer(text):
                abbr = m.group(1)

                # 跳过常见英语单词
                if abbr in _COMMON_UPPERCASE_WORDS:
                    continue

                pos = m.start()
                abbr_end = m.end()

                # 检测是否为定义位置
                before_short = text[max(0, pos - 4):pos].strip()
                is_def_before = before_short.startswith("(")

                after_window = text[abbr_end:abbr_end + 80]
                is_def_after = bool(re.match(
                    r"[\s]*\([^)]+\)", after_window
                ))

                before_window = text[max(0, pos - 120):pos]
                is_full_before = bool(re.search(
                    r"\([^)]*" + re.escape(abbr) + r"[^)]*\)",
                    before_window
                ))

                is_defined = is_def_before or is_def_after or is_full_before

                occurrence = {
                    "page_index": page.index,
                    "page_number": page.slide_number or page.index + 1,
                    "position": pos,
                    "context": text[max(0, pos - 20):abbr_end + 20],
                    "is_definition": is_defined,
                }

                if abbr not in scan_result:
                    scan_result[abbr] = {
                        "occurrences": [],
                        "total_count": 0,
                        "definition_count": 0,
                        "first_page": page.index,
                        "first_page_number": page.slide_number or page.index + 1,
                    }
                scan_result[abbr]["occurrences"].append(occurrence)
                scan_result[abbr]["total_count"] += 1
                if is_defined:
                    scan_result[abbr]["definition_count"] += 1

        # 按出现顺序排序并标记 first_is_definition
        for abbr, data in scan_result.items():
            data["occurrences"].sort(key=lambda o: (o["page_index"], o["position"]))
            data["first_is_definition"] = (
                data["occurrences"][0]["is_definition"]
                if data["occurrences"]
                else False
            )

        self._abbr_scan_cache = (id(doc), scan_result)
        return scan_result

    # ── 缩写首次定义 ─────────────────────────────────────────

    def _check_abbreviation_first_defined(self, doc: Document) -> list[AuditFinding]:
        """检查技术缩写首次出现时是否给出全称"""
        findings: list[AuditFinding] = []
        scan = self._scan_abbreviations(doc)

        for abbr, data in scan.items():
            if not data["first_is_definition"]:
                first_occ = data["occurrences"][0]
                findings.append(AuditFinding(
                    type=FindingType.FACTUAL,
                    severity=FindingSeverity.WARNING,
                    message=f"缩写「{abbr}」首次出现时未给出全称",
                    rule_id="CON-003",
                    page_index=first_occ["page_index"],
                    location=f"第 {first_occ['page_number']} 页",
                    context=first_occ["context"][:120],
                    suggestion=f"建议首次出现时写为「{abbr} (全称)」格式",
                    metadata={"total_occurrences": data["total_count"]},
                ))

        return findings

    # ── 缩写生命周期子检查 ───────────────────────────────────

    def _check_abbreviation_defined_never_used(self, doc: Document) -> list[AuditFinding]:
        """检查已定义但未再次使用的缩写 (CON-003-A, inspired by PerfectIt)。

        如果缩写在定义后未在文档中再次出现，则该定义可能是多余的。
        """
        findings: list[AuditFinding] = []
        scan = self._scan_abbreviations(doc)

        for abbr, data in scan.items():
            # 必须已定义
            if not data["first_is_definition"] and data["definition_count"] == 0:
                continue
            # 总出现次数 <= 定义次数 → 定义后未再使用
            if data["total_count"] <= data["definition_count"]:
                first_occ = data["occurrences"][0]
                findings.append(AuditFinding(
                    type=FindingType.FACTUAL,
                    severity=FindingSeverity.INFO,
                    message=f"缩写「{abbr}」已定义但未再次使用，定义可能是多余的",
                    rule_id="CON-003-A",
                    page_index=first_occ["page_index"],
                    location=f"第 {first_occ['page_number']} 页",
                    context=first_occ["context"][:120],
                    suggestion="如果该缩写不再出现，可考虑移除其定义；或检查是否有遗漏的使用场景",
                    metadata={"total_occurrences": data["total_count"],
                              "definition_count": data["definition_count"]},
                ))

        return findings

    def _check_abbreviation_multiply_defined(self, doc: Document) -> list[AuditFinding]:
        """检查同一缩写被重复定义 (CON-003-B, inspired by PerfectIt)。

        技术缩写在文档中应只在首次出现时定义一次。
        """
        findings: list[AuditFinding] = []
        scan = self._scan_abbreviations(doc)

        for abbr, data in scan.items():
            if data["definition_count"] >= 2:
                # 找到所有定义位置
                def_sites = [occ for occ in data["occurrences"] if occ["is_definition"]]
                pages_str = "、".join(
                    f"第 {occ['page_number']} 页" for occ in def_sites
                )
                findings.append(AuditFinding(
                    type=FindingType.FACTUAL,
                    severity=FindingSeverity.WARNING,
                    message=f"缩写「{abbr}」被重复定义了 {data['definition_count']} 次",
                    rule_id="CON-003-B",
                    page_index=def_sites[0]["page_index"],
                    location=pages_str,
                    context=def_sites[0]["context"][:120],
                    suggestion="建议仅保留首次定义，后续出现时直接使用缩写",
                    metadata={"definition_count": data["definition_count"],
                              "definition_pages": [occ["page_number"] for occ in def_sites]},
                ))

        return findings

    def _check_abbreviation_used_before_defined(self, doc: Document) -> list[AuditFinding]:
        """检查缩写在定义前就被使用 (CON-003-C, inspired by PerfectIt)。

        技术缩写应在首次出现时就给出全称定义，不应在后续才定义。
        """
        findings: list[AuditFinding] = []
        scan = self._scan_abbreviations(doc)

        for abbr, data in scan.items():
            # 必须至少有一次定义
            if data["definition_count"] == 0:
                continue
            # 首次出现不是定义 → 先使用后定义
            if not data["first_is_definition"]:
                first_occ = data["occurrences"][0]
                # 找到第一个定义位置
                def_occ = next(
                    (occ for occ in data["occurrences"] if occ["is_definition"]),
                    None,
                )
                def_page = def_occ["page_number"] if def_occ else "?"
                findings.append(AuditFinding(
                    type=FindingType.FACTUAL,
                    severity=FindingSeverity.WARNING,
                    message=f"缩写「{abbr}」在第 {first_occ['page_number']} 页使用，但在第 {def_page} 页才给出定义",
                    rule_id="CON-003-C",
                    page_index=first_occ["page_index"],
                    location=f"第 {first_occ['page_number']} 页 (使用) → 第 {def_page} 页 (定义)",
                    context=first_occ["context"][:120],
                    suggestion="建议将缩写定义移至首次出现处，写为「全称 (ABBR)」格式",
                    metadata={"first_use_page": first_occ["page_number"],
                              "definition_page": def_page},
                ))

        return findings
