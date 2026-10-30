"""事实审查器 — 文档内部一致性检查"""

import re
import weakref
from collections import defaultdict
from typing import Any

from src.auditors.base import BaseAuditor
from src.engines.vocabulary import Vocabulary
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity, FindingType
from src.text_utils import mask_prose_noise

# 常见英语大写单词 (非技术缩写)，出现在文档中时不应标记为“未定义缩写”
_COMMON_UPPERCASE_WORDS = frozenset(
    {
        # 2 字母常见词 (扩展匹配范围后需排除)
        "OK",
        "AM",
        "PM",
        "GO",
        "DO",
        "IS",
        "IT",
        "WE",
        "HE",
        "MY",
        "BY",
        "TO",
        "IF",
        "OR",
        "SO",
        "NO",
        "UP",
        "ON",
        "IN",
        "AT",
        "OF",
        "AS",
        "BE",
        "AN",
        "ME",
        "US",
        # 3 字母
        "THE",
        "AND",
        "FOR",
        "ALL",
        "BUT",
        "NOT",
        "CAN",
        "ARE",
        "WAS",
        "HAS",
        "HAD",
        "NEW",
        "SET",
        "END",
        "TOP",
        "ONE",
        "TWO",
        "VIA",
        "MAY",
        "ANY",
        "NOW",
        "OUR",
        "USE",
        "GET",
        "LET",
        "SEE",
        "WAY",
        # 4 字母
        "THAT",
        "THIS",
        "THAN",
        "THEN",
        "WITH",
        "WHEN",
        "FROM",
        "HAVE",
        "BEEN",
        "WILL",
        "ALSO",
        "USED",
        "EACH",
        "SOME",
        "MORE",
        "ONLY",
        "VERY",
        "JUST",
        "WHAT",
        "WHICH",
        "THEIR",
        "THESE",
        "WHERE",
        # 5+ 字母
        "WOULD",
        "COULD",
        "SHOULD",
        "THERE",
        "ABOUT",
    }
)

# 数值提取正则 — 仅匹配数值+可选单位，上下文通过文本切片获取
# 避免上下文捕获组吞噬相邻数值
# 单位后加 (?![a-zA-Z]) 防止 "5 m" 误匹配 "5 minutes" 中的 m
# 单位表扩充 (2026-09-06 审查 D-3): 表外单位会使 (\d+) 在 (?![a-zA-Z]) 守卫下
# 回溯截断 ("28pt"→"2"、"500g"→"50"), 导致 CON-001 漏报与数值失真 —
# 补齐 pt/kg/g/km/dB/Hz/ms 等常见工程单位 (长前缀在前防误配);
# 表外残余场景由 _extract_numeric_values 的截断防护兜底 (宁跳过不出错值)。
_NUMERIC_VALUE_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:%|°[CF]|nm|μm|um|mm|cm|km|dB|kg|pt|ms|μs|us"
    r"|mV|mA|kV|kW|kHz|MHz|GHz|Hz|GB|MB|KB|TB|ppm|mL|ml|V|A|W|g|m|L|s)?)(?![a-zA-Z])"
)

# CON-001 限定词识别: 年份/季度/工艺节点是"指标限定词"，不是待比较的指标值。
# 2026-10-28 修复: 旧 key 把所有数字替换为 N，导致 2025 vs 2026、Q1 vs Q2、
# 5nm vs 7nm 被误判为同一指标数值不一致。
_YEAR_TOKEN_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_QUARTER_TOKEN_RE = re.compile(r"(?i)(?:Q[1-4]|第[1-4一二三四]季度)")
_NODE_TOKEN_RE = re.compile(r"(?i)\d+(?:\.\d+)?\s*(?:nm|μm|um|mm|cm)(?![a-zA-Z])")
_LENGTH_UNITS = frozenset({"nm", "μm", "um", "mm", "cm", "m"})

# 数值提取后剥离非数字字符 — 比固定单位列表更通用，无需与 _NUMERIC_VALUE_RE 同步

# 技术缩写提取正则 (模块级预编译 — 修复 2026-08 审查 L5: 曾每次扫描重复编译)
_ABBR_RE = re.compile(r"\b([A-Z]{2,8})\b")

# 中英文括号开合字符 (与 custom_rules.py TERM-003 排除括号内配对逻辑一致)
_OPEN_PARENS_RE = re.compile(r"[（(]")
_CLOSE_PARENS_RE = re.compile(r"[）)]")


def _compute_paren_ranges(text: str) -> list[tuple[int, int]]:
    """计算括号组区间 [(open_pos, close_pos), ...]。

    配对逻辑与 custom_rules.py 的 TERM-003 排除括号内一致:
    每个开括号与它之后最近的闭括号配对 (不成对的开括号忽略)。
    用于 "全称 (ABBR)" 定义格式的缩写定位 (缩写位于括号组内 → 定义位置)。
    """
    opens = [m.start() for m in _OPEN_PARENS_RE.finditer(text)]
    closes = [m.start() for m in _CLOSE_PARENS_RE.finditer(text)]
    ranges: list[tuple[int, int]] = []
    ci = 0
    for op in opens:
        while ci < len(closes) and closes[ci] <= op:
            ci += 1
        if ci < len(closes):
            ranges.append((op, closes[ci]))
            ci += 1
    return ranges


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
        # 领域白名单: vocab/accept.txt 中认可的缩写 (WLP/FOWLP/RDL/TSV...)
        # 不参与 CON-003 未定义检查 — 否则半导体文档会被大量误报。
        vocab_dir = cfg.get("vocab_dir")
        self._vocabulary = Vocabulary(vocab_dir) if vocab_dir else None
        # 缩写扫描缓存 — 每次 audit() 调用时重置；独立模式 (dispatch 直调) 下
        # 以 (id(doc), result) 绑定文档身份，防止跨文档串档
        self._abbr_scan_cache: tuple | None = None
        # 全局参数 (rules.md frontmatter parameters.*)
        units = cfg.get("numeric_length_units")
        self._length_units = frozenset(str(u) for u in units) if units else _LENGTH_UNITS
        keywords = cfg.get("unit_keywords")
        self.unit_keywords = (
            [str(k) for k in keywords]
            if keywords
            else [
                "厚度",
                "宽度",
                "深度",
                "直径",
                "间距",
                "线宽",
                "高度",
                "长度",
                "温度",
                "电压",
                "电流",
                "功率",
                "速度",
                "尺寸",
                "距离",
                "容量",
                "重量",
                "压力",
                "频率",
                "密度",
                "角度",
            ]
        )
        extra = cfg.get("common_uppercase_extra") or []
        self._common_uppercase_words = frozenset(_COMMON_UPPERCASE_WORDS) | frozenset(
            str(w).upper() for w in extra
        )

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

        # 提取所有带上下文的数值；年份/季度/节点等限定词不参与指标一致性比较。
        numeric_entries: list[dict] = [
            entry
            for entry in self._extract_numeric_values(doc)
            if not self._is_qualifier_numeric_entry(entry, self._length_units)
        ]

        # 按相似上下文聚类。key 保留年份/季度/节点等限定词，
        # 避免把"2025 年 vs 2026 年"、"Q1 vs Q2"、"5nm vs 7nm"当成同一指标。
        context_groups: dict[str, list[dict]] = defaultdict(list)
        for entry in numeric_entries:
            context_groups[self._numeric_context_key(entry)].append(entry)

        for norm_key, entries in context_groups.items():
            if len(entries) < 2:
                continue

            # 检查数值是否一致（浮点容差，避免 95.30 与 95.3 误报）
            values = {round(e["value"], 9) for e in entries}
            if len(values) > 1:
                # 发现不一致
                entries_sorted = sorted(entries, key=lambda e: e["page_index"])
                occurrences = "\n".join(
                    f"  - 第 {e['page_number']} 页: {e['match_text']}" for e in entries_sorted
                )
                findings.append(
                    AuditFinding(
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
                    )
                )

        return findings

    @staticmethod
    def _numeric_qualifiers(*texts: str) -> set[str]:
        """提取上下文中的年份/季度/工艺节点限定词（小写、去重）。"""
        qualifiers: set[str] = set()
        for text in texts:
            if not text:
                continue
            for regex in (_YEAR_TOKEN_RE, _QUARTER_TOKEN_RE, _NODE_TOKEN_RE):
                qualifiers.update(m.group(0).lower().replace(" ", "") for m in regex.finditer(text))
        return qualifiers

    def _numeric_context_key(self, entry: dict) -> str:
        """构造数值聚类 key：上下文数字归一化为 N，但保留限定词。"""
        context = entry.get("context", "").lower().strip()
        normalized = re.sub(r"\d+(?:\.\d+)?", "N", context)
        qualifiers = self._numeric_qualifiers(
            entry.get("prefix", ""),
            entry.get("suffix", ""),
            entry.get("match_text", ""),
        )
        return normalized + "|" + ",".join(sorted(qualifiers))

    @staticmethod
    def _is_qualifier_numeric_entry(entry: dict, length_units: frozenset = _LENGTH_UNITS) -> bool:
        """判断数值是否只是年份/季度/工艺节点等限定词，而非指标值。

        例：
        - 2025年良率 95% → 2025 是年份，不参与比较；95% 参与。
        - 第1季度良率 95% → 1 是季度序号，不参与比较；95% 参与。
        - 5nm 节点良率 95% → 5nm 是工艺节点，不参与比较；95% 参与。
        """
        unit = str(entry.get("unit", "")).lower()
        if unit in length_units:
            return True

        prefix = str(entry.get("prefix", ""))
        suffix = str(entry.get("suffix", ""))
        nearby = prefix + suffix
        value = entry.get("value")

        # 4 位年份 + 年/年度/财年/日期语境
        if (
            isinstance(value, (int, float))
            and 1900 <= value <= 2100
            and (re.search(r"(?:年|年度|财年|月|日)", nearby) or _QUARTER_TOKEN_RE.search(nearby))
        ):
            return True

        # "第 1 季度" / "Q1" 中的序号
        if re.search(r"(?i)(?:Q|第)\s*$", prefix) and re.match(r"(?i)\s*(?:季度|季)", suffix):
            return True

        return False

    def _extract_numeric_values(self, doc: Document) -> list[dict]:
        """提取文档中所有数值及其上下文 (过滤页码/图表编号等模板数字)"""
        entries: list[dict] = []

        for page in doc.pages:
            # 代码块/URL 内的数值不是待比较的指标值；掩码等长替换、字符位置不变
            text = mask_prose_noise(page.all_text)
            for m in _NUMERIC_VALUE_RE.finditer(text):
                value_str = m.group(1).strip()
                start = m.start()
                end = m.end()

                # 截断防护 (2026-09-06 审查 D-3): (?![a-zA-Z]) 守卫触发回溯截断时
                # （表外单位 "28xyz" 被截为 "2"、"3.3Vs" 被截为 "3"、"1,000" 被截为 "1"），
                # 该值不可信 — 宁可跳过也不产出错误数值参与一致性比较。
                # 判定: 匹配后紧跟数字 (单位表内完整匹配如 "28pt" 已到单位末尾, 必非数字),
                # 或紧跟 "."/"," 且再后一位是数字 (截断的小数/千分位延续)。
                # 或匹配起始紧前是数字 (长数串的尾部残余), 或其前是 ","/"." 且更前是
                # 数字 (千分位/小数延续, 如 "1,000" 的尾 "000"、"5,5" 欧式小数)。
                # 注意: 版本号 "2.5.1" 截取 "2.5" 属残缺值, 一并跳过 (宁缺毋滥)。
                if end < len(text) and (
                    text[end].isdigit()
                    or (text[end] in ".," and end + 1 < len(text) and text[end + 1].isdigit())
                ):
                    continue
                if start > 0 and text[start - 1].isdigit():
                    continue
                if start > 1 and text[start - 1] in ".," and text[start - 2].isdigit():
                    continue

                # 提取上下文 (前后各 30 字符，避免跨越其他数值)
                prefix = text[max(0, start - 30) : start].strip()
                suffix = text[end : end + 30].strip()
                context = f"{prefix} {value_str} {suffix}"

                # 页码/图表编号跳过检测: 紧邻前缀 (10 字符) + 值为纯整数
                # (点分隔章节式如 "Fig. 2.1" 为小数形态, 一并跳过 — 图号语义非指标数值)。
                # 旧逻辑依赖 re.sub(r"\d+", "N", prefix) 在 prefix 中找占位符 N，
                # 但 _NUMERIC_VALUE_RE 只匹配数值本身，前缀从不含数字，
                # 导致 N 永不存在 → 页码不过滤 + 远处 "Page N" 污染后续值前缀。
                # 新逻辑: 紧邻前缀含页码/图表关键词 + 值为无单位的纯整数 → 跳过。
                # 第二分支 (2026-09-06 审查 N-1): 章节式图表编号的子号 "图2-1"/"Fig. 2.1"
                # 中的 "1" 紧邻前缀是 "图2-"/"fig. 2." (以连字符/点结尾), 原关键词后缀
                # 分支不匹配 → 子号漏过滤 → 同句式跨页引用不同子号时误报 CON-001。
                # 关键词与分隔符间允许 ≤8 非数字字符 (兼容 "to fig. 2-" 等较长前缀)。
                _narrow_prefix = text[max(0, start - 10) : start].lower().strip()
                if re.match(r"^\d+(?:\.\d+)?$", value_str) and re.search(
                    r"(?:(?:fig|figure|table|tab|图|表|第)[^\d]{0,8}\d+\s*[-–—.]|"
                    r"(?:page|slide|fig|figure|table|tab|图|表|第)\s*\.?\s*)$",
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

                entries.append(
                    {
                        "page_index": page.index,
                        "page_number": page.slide_number or page.index + 1,
                        "context": context.strip(),
                        "prefix": prefix,
                        "suffix": suffix,
                        "value": value_float,
                        "match_text": value_str,
                        "unit": re.sub(r"[\d.\s]", "", value_str).strip(),
                    }
                )

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
        (以 weakref.ref(doc) 绑定文档身份 — 修复 2026-08 审查 L3:
        曾用 id(doc)，对象回收后地址可被新对象复用导致跨文档串档)。
        """
        if self._abbr_scan_cache is not None:
            cached_ref, cached_result = self._abbr_scan_cache
            if cached_ref() is doc:
                return cached_result

        scan_result: dict = {}

        for page in doc.pages:
            # 代码块/URL 内的缩写不是正文用法；掩码等长替换、字符位置不变
            text = mask_prose_noise(page.all_text)
            # 括号组区间 (每页一次) — 定义站点判定依赖
            paren_ranges = _compute_paren_ranges(text)

            for m in _ABBR_RE.finditer(text):
                abbr = m.group(1)

                # 跳过常见英语单词
                if abbr in self._common_uppercase_words:
                    continue

                # 跳过项目白名单中的领域缩写 (WLP/FOWLP/RDL/TSV/IC...)。
                if self._vocabulary is not None and self._vocabulary.is_accepted(abbr):
                    continue

                pos = m.start()
                abbr_end = m.end()

                # 文件名/路径片段不是待定义的技术缩写 (2026-11 审查:
                # README 的 "AGENTS.md" / "MANIFEST.in" 曾被当缩写报 CON-003)。
                if re.match(r"\.[A-Za-z]{1,5}(?![A-Za-z])", text[abbr_end:]):
                    continue
                if pos > 0 and text[pos - 1] in "/\\":
                    continue

                # 定义站点判定 (修复 2026-08 审查 L14: 曾用 120 字符窗口
                # is_full_before 把"定义后的再次使用"误计为定义 → CON-003-B 假阳性;
                # 改为紧邻判定 — 定义站点 = 括号组 open 位置):
                # 1. is_def_after: 缩写后紧跟括号组 "ABBR (全称)" (仅允许空白)
                # 2. in_paren: 缩写位于括号组内且是括号内容最后一个 token
                #    "全称 (ABBR)"；"（核心依赖 + PDF + 开发工具）" 这类顺带提及
                #    不是定义 (2026-11 审查: README 实测 19 处"定义"里 5 处是误判)
                def_site: int | None = None
                after_window = text[abbr_end : abbr_end + 80]
                # 半角/全角括号都识别: 中文文档常用 "TSV（硅通孔）"，旧实现只认
                # 半角 "("，全角写法靠 in_paren 兜底才算定义（收窄 in_paren 后必须补上）
                m_after = re.match(r"[\s]*[(（][^)）]+[)）]", after_window)
                if m_after:
                    paren_start = abbr_end + re.search(r"[(（]", m_after.group(0)).start()
                    def_site = paren_start
                else:
                    for op, cl in paren_ranges:
                        if op < pos < cl:
                            tail = text[abbr_end:cl].strip(" \t\r\n，,。.；;：:、")
                            if not tail:
                                def_site = op
                            break

                occurrence = {
                    "page_index": page.index,
                    "page_number": page.slide_number or page.index + 1,
                    "position": pos,
                    "context": text[max(0, pos - 20) : abbr_end + 20],
                    "is_definition": def_site is not None,
                    "def_site": def_site,
                }

                if abbr not in scan_result:
                    scan_result[abbr] = {
                        "occurrences": [],
                        "total_count": 0,
                        "first_page": page.index,
                        "first_page_number": page.slide_number or page.index + 1,
                    }
                scan_result[abbr]["occurrences"].append(occurrence)
                scan_result[abbr]["total_count"] += 1

        # 按出现顺序排序并标记 first_is_definition / definition_count
        # definition_count = 不同定义站点数 (同一括号组 "TSV (硅通孔 TSV)" 中
        # 括号内出现不再重复计入, 修复 CON-003-B 假阳性)。
        # 定义站点必须用 (页码, 页内位置) 二元组：def_site 是页内字符偏移，
        # 两页在同一偏移各定义一次时会被误判为"同一定义站点"→ CON-003-B 漏报
        # (2026-11 审查: 两页模板句 "TSV (Through Silicon Via)" 实测漏报)。
        for abbr, data in scan_result.items():
            data["occurrences"].sort(key=lambda o: (o["page_index"], o["position"]))
            data["first_is_definition"] = (
                data["occurrences"][0]["is_definition"] if data["occurrences"] else False
            )
            data["definition_count"] = len(
                {
                    (o["page_index"], o["def_site"])
                    for o in data["occurrences"]
                    if o["def_site"] is not None
                }
            )

        self._abbr_scan_cache = (weakref.ref(doc), scan_result)
        return scan_result

    # ── 缩写首次定义 ─────────────────────────────────────────

    def _check_abbreviation_first_defined(self, doc: Document) -> list[AuditFinding]:
        """检查技术缩写首次出现时是否给出全称"""
        findings: list[AuditFinding] = []
        scan = self._scan_abbreviations(doc)

        for abbr, data in scan.items():
            if not data["first_is_definition"]:
                first_occ = data["occurrences"][0]
                findings.append(
                    AuditFinding(
                        type=FindingType.FACTUAL,
                        severity=FindingSeverity.ERROR,
                        message=f"缩写「{abbr}」首次出现时未给出全称",
                        rule_id="CON-003",
                        page_index=first_occ["page_index"],
                        location=f"第 {first_occ['page_number']} 页",
                        context=first_occ["context"][:120],
                        suggestion=f"建议首次出现时写为「{abbr} (全称)」格式",
                        metadata={"total_occurrences": data["total_count"]},
                    )
                )

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
            # 定义之外的"实际使用"次数 = 总出现次数 - 定义站点内的出现次数。
            # 旧实现拿 total_count 直接比 definition_count(去重站点)：定义括号内
            # 再次写出缩写时（"TSV (硅通孔 TSV)" total=2 > def=1）永不报 ⇒ 定义后
            # 从未使用却漏报 CON-003-A（2026-11 审查）。
            definition_occurrences = sum(
                1 for occ in data["occurrences"] if occ["def_site"] is not None
            )
            usage_count = data["total_count"] - definition_occurrences
            if usage_count <= 0:
                first_occ = data["occurrences"][0]
                findings.append(
                    AuditFinding(
                        type=FindingType.FACTUAL,
                        severity=FindingSeverity.INFO,
                        message=f"缩写「{abbr}」已定义但未再次使用，定义可能是多余的",
                        rule_id="CON-003-A",
                        page_index=first_occ["page_index"],
                        location=f"第 {first_occ['page_number']} 页",
                        context=first_occ["context"][:120],
                        suggestion="如果该缩写不再出现，可考虑移除其定义；或检查是否有遗漏的使用场景",
                        metadata={
                            "total_occurrences": data["total_count"],
                            "definition_count": data["definition_count"],
                            "usage_count": usage_count,
                        },
                    )
                )

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
                pages_str = "、".join(f"第 {occ['page_number']} 页" for occ in def_sites)
                findings.append(
                    AuditFinding(
                        type=FindingType.FACTUAL,
                        severity=FindingSeverity.WARNING,
                        message=f"缩写「{abbr}」被重复定义了 {data['definition_count']} 次",
                        rule_id="CON-003-B",
                        page_index=def_sites[0]["page_index"],
                        location=pages_str,
                        context=def_sites[0]["context"][:120],
                        suggestion="建议仅保留首次定义，后续出现时直接使用缩写",
                        metadata={
                            "definition_count": data["definition_count"],
                            "definition_pages": [occ["page_number"] for occ in def_sites],
                        },
                    )
                )

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
                # 同一页内"先用后定义"时旧文案会输出"在第 N 页使用，但在第 N 页才给出
                # 定义"(自相矛盾, 2026-11 审查 README 实测), 改为明示同页后文定义。
                if def_occ is not None and def_page == first_occ["page_number"]:
                    message = f"缩写「{abbr}」在第 {first_occ['page_number']} 页首次使用，同页后文才给出定义"
                    location = f"第 {first_occ['page_number']} 页（定义位于后文）"
                else:
                    message = (
                        f"缩写「{abbr}」在第 {first_occ['page_number']} 页使用，"
                        f"但在第 {def_page} 页才给出定义"
                    )
                    location = f"第 {first_occ['page_number']} 页 (使用) → 第 {def_page} 页 (定义)"
                findings.append(
                    AuditFinding(
                        type=FindingType.FACTUAL,
                        severity=FindingSeverity.WARNING,
                        message=message,
                        rule_id="CON-003-C",
                        page_index=first_occ["page_index"],
                        location=location,
                        context=first_occ["context"][:120],
                        suggestion="建议将缩写定义移至首次出现处，写为「全称 (ABBR)」格式",
                        metadata={
                            "first_use_page": first_occ["page_number"],
                            "definition_page": def_page,
                        },
                    )
                )

        return findings

    # ── 数值单位完整性（2026-11 新增 CON-007）─────────────────

    def _check_numeric_unit_presence(self, doc: Document) -> list[AuditFinding]:
        """量词语境下的数值缺少单位（如「厚度 5」而非「厚度 5nm」）。

        保守判定，避免与普通计数/序号误报：
        - 只检查前面 8 字符内出现配置量词（厚度/宽度/电压…）的数值；
        - 数值自身带单位（nm/mm/%/V…）或后接中文单位（纳米/毫米/伏…）则跳过；
        - 每页最多 3 条，避免刷屏。
        """
        if not self.unit_keywords:
            return []
        keyword_re = re.compile(
            "|".join(re.escape(k) for k in sorted(self.unit_keywords, key=len, reverse=True))
        )
        findings: list[AuditFinding] = []
        for page in doc.pages:
            label = f"第 {page.slide_number or page.index + 1} 页"
            text = mask_prose_noise(page.all_text)
            page_hits: list[tuple[str, str]] = []
            for m in _NUMERIC_VALUE_RE.finditer(text):
                token = m.group(0)
                if re.search(r"[A-Za-z%％°]", token):
                    continue  # 自带单位/百分比/角度
                prefix = text[max(0, m.start() - 10) : m.start()]
                if not keyword_re.search(prefix[-8:]):
                    continue
                if _CN_UNIT_RE.match(text, m.end()):
                    continue  # 后接中文单位
                context = (prefix[-8:] + token).strip()
                page_hits.append((token, context))
            for _token, context in page_hits[:3]:
                findings.append(
                    AuditFinding(
                        type=FindingType.FACTUAL,
                        severity=FindingSeverity.INFO,
                        message="数值缺少单位",
                        rule_id="CON-007",
                        page_index=page.index,
                        location=label,
                        context=context[:80],
                        suggestion="为量值补充单位（如 nm / μm / V / %），避免歧义",
                    )
                )
        return findings


# 中文单位词（数值后紧邻出现即视为已有单位）
_CN_UNIT_RE = re.compile(
    r"(?:纳米|微米|毫米|厘米|米|伏特|伏|毫伏|千伏|安培|安|毫安|瓦特|瓦|千瓦|赫兹|赫|千赫|兆赫|"
    r"秒|毫秒|微秒|分钟|小时|度|摄氏度|克|千克|公斤|吨|升|毫升|帕|兆帕|牛|牛顿|焦耳|欧姆|欧)"
)
