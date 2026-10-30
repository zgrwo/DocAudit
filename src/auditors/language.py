"""语言审查器 — 中英混合语法检查 + 术语一致性"""

import logging
import re
from itertools import combinations

from src.auditors.base import BaseAuditor
from src.engines.languagetool import LanguageToolClient, check_chinese_patterns
from src.engines.terminology import TerminologyChecker
from src.engines.vocabulary import Vocabulary
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity, FindingType
from src.text_utils import (
    CJK_LATIN_BOUNDARY,
    CJK_RE,
    LATIN_CJK_BOUNDARY,
    LETTERED_BULLET_RE,
    NUMBERED_BULLET_RE,
    SYMBOL_BULLET_RE,
    mask_prose_noise,
)
from src.text_utils import (
    LATIN_CHINESE_PUNCT as _LATIN_CHINESE_PUNCT,
)

logger = logging.getLogger(__name__)


# ── 标点/冗余检查 (2026-10-28) ────────────────────────────────
# 说明: 这些检查必须与 LanguageTool 后端无关，始终执行；旧实现把中文模式
# 只放在 Tier-3 Python 降级里，Docker/Java 可用时反而检查更少。

_PUNCT_REPEAT_RE = re.compile(r"([；：！？])\1+")
_PUNCT_ADJACENT_RE = re.compile(r"([，。、；：])\s*([，。、；：])")
_CJK_ASCII_PUNCT_RE = re.compile(rf"({CJK_RE.pattern})([,.;:!?])")
_FULLWIDTH_ALNUM_RE = re.compile(r"[Ａ-Ｚａ-ｚ０-９]+")
_ELLIPSIS_RE = re.compile(r"\.{3,}")
_DOUBLE_HYPHEN_RE = re.compile(r"(?<!—)--(?!—)")

_PUNCT_PAIRS = {
    "（": "）",
    "(": ")",
    "【": "】",
    "[": "]",
    "《": "》",
    "“": "”",
    "‘": "’",
}

# 高精度中文冗余表达；约/大约/大概/超过/至少...左右/以上 已由
# LanguageTool 中文基础模式覆盖，此处不重复，避免同一句两条 finding。
_REDUNDANT_PATTERNS = [
    (
        re.compile(r"原因[^，。；\n]{0,20}造成"),
        "语义重复: '原因是……造成的'",
        "改为“原因是……”或“……造成的”",
    ),
    (
        re.compile(r"通过[^，。；\n]{0,20}使得"),
        "句式冗余: '通过……使得……'",
        "改为“通过……实现……”或“……使得……”",
    ),
    (
        re.compile(r"进行了?[^，。；\n]{0,10}工作"),
        "冗余表达: '进行了……工作'",
        "直接使用具体动词，如“完成了……”“开展了……”",
    ),
    (
        re.compile(r"再次重申"),
        "语义重复: '再次重申'",
        "改为“重申”或“再次说明”",
    ),
    (
        re.compile(r"目前现状"),
        "语义重复: '目前现状'",
        "改为“目前情况”或“现状”",
    ),
    (
        re.compile(r"共同一起"),
        "语义重复: '共同一起'",
        "改为“共同”或“一起”",
    ),
    (
        re.compile(r"互相彼此"),
        "语义重复: '互相彼此'",
        "改为“互相”或“彼此”",
    ),
    (
        re.compile(r"更加越来越"),
        "语义重复: '更加越来越'",
        "改为“越来越”或“更加”",
    ),
    (
        re.compile(r"唯一一个"),
        "语义重复: '唯一一个'",
        "改为“唯一”",
    ),
]

# ── 文档级格式一致性 (2026-10-29 补全) ──────────────────────
# 说明: 都是 INFO/WARNING 级提示，供人工确认；阈值偏保守以避免噪声。

# 常见日期格式 (顺序即示例优先级)
_DATE_FORMAT_PATTERNS = (
    ("中文", re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")),
    # 用 (?<!\d)/(?!\d) 而非 \b：汉字属于 \w，\b 在「自2026-10-29起」处不成立
    ("ISO", re.compile(r"(?<!\d)\d{4}-\d{1,2}-\d{1,2}(?!\d)")),
    ("斜杠", re.compile(r"(?<!\d)\d{4}/\d{1,2}/\d{1,2}(?!\d)")),
)
_ISO_DATE_RE = re.compile(r"(?<!\d)\d{4}-\d{1,2}-\d{1,2}(?!\d)")
# 数值范围连接符: 半角连字符 / 长短破折号 / 波浪号 / 中文"至/到"
_RANGE_SEPARATOR_RE = re.compile(r"(?<=\d)\s*([-–—~～]|至|到)\s*(?=\d)")
_RANGE_CLASS = {
    "-": "半角连字符",
    "–": "短破折号",
    "—": "长破折号",
    "~": "半角波浪号",
    "～": "全角波浪号",
    "至": "中文“至”",
    "到": "中文“到”",
}
# 数值+单位 (长的单位排前面，避免 "kg" 被 "g" 抢先匹配)
_UNIT_RE = re.compile(
    # 左边界排除数字/ASCII 字母/点，但允许汉字（厚度为10mm 必须能匹配）
    r"(?<![0-9A-Za-z_.])(\d+(?:\.\d+)?)\s?"
    r"(GHz|MHz|kHz|Hz|kg|mg|g|km|cm|mm|μm|um|nm|ms|min|mL|ml|L|dB|kV|V|mA|A|kW|W|GB|MB|TB|KB|pt|℃|°C|%)"
    r"(?![A-Za-z])"
)
_TERMINAL_PUNCT = ("。", "；", "，", "、", "！", "？", ".", ";", ",", "!", "?")
_BULLET_MARKER_RE = re.compile(r"^\s*(?:[•◦▪▸◆\-*]|\d+[\.\)]|\(\d+\)|[a-zA-Z][\.\)])\s+")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?\n]+|\.\s+")


# 跨页固定出现的版式文本，不参与「重复句/近似重复页」比较
_AUXILIARY_PLACEHOLDERS = frozenset({"header", "footer", "slide_number", "date"})


def _body_text(page) -> str:
    """正文文本：排除页眉/页脚/页码/日期占位符（2026-10-29 审查）。

    页面 all_text 含页脚等版式文本；固定页脚逐页重复，旧实现会把
    「页脚一句免责声明」报成 TXT-DUP-SENTENCE，也会抬高 TXT-NEAR-DUP 相似度。
    """
    chunks: list[str] = []
    for elem in page.flattened_elements:
        if (elem.placeholder_type or "") in _AUXILIARY_PLACEHOLDERS:
            continue
        for para in elem.paragraphs:
            if para.text and para.text.strip():
                chunks.append(para.text)
        for row in elem.tables:
            for cell in row:
                if cell.text and cell.text.strip():
                    chunks.append(cell.text)
    return "\n".join(chunks)


def _mask_dates(text: str) -> str:
    """掩码 ISO 日期，避免 "2026-10" 被当成数值范围。"""
    return _ISO_DATE_RE.sub(lambda m: " " * len(m.group(0)), text)


def _normalize_sentence(sentence: str) -> str:
    """句级去重归一化: 去掉空白与句末/句中常见标点，大小写不敏感。"""
    norm = re.sub(r"\s+", "", sentence)
    norm = norm.strip("，,、；;：:。.！!？?")
    return norm.lower()


def _bigrams(text: str) -> set[str]:
    """字符二元组集合（用于页面相似度 Jaccard）。"""
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _mask_prose_noise(text: str) -> str:
    """用等长空格掩码 URL/邮箱/代码，避免把其中的 . , : 当标点错误。

    实现已收敛到 src/text_utils.mask_prose_noise（拼写/混排检查共用同一份掩码）。
    """
    return mask_prose_noise(text)


def _latin_word_before(text: str, pos: int) -> bool:
    """pos 前紧邻的拉丁串是否为「≥2 个纯字母」组成的英文词。

    FMT-MIXED-003（英文后不应使用中文标点）要判定的是"英文词 + 中文标点"；
    单字母标签（"方案 A："）、版本号（"v1.0："）、数字单位（"5nm："）在中文里
    是正常写法，旧实现按单字符匹配 → 每处都误报（2026-11 审查：README 实测 7 条）。
    """
    start = pos
    while start > 0 and text[start - 1].isascii() and text[start - 1].isalnum():
        start -= 1
    run = text[start:pos]
    return len(run) >= 2 and run.isalpha()


def _unmatched_pairs(text: str) -> list[str]:
    """返回未配对的括号/引号字符列表（栈式配对）。"""
    stack: list[str] = []
    unmatched: list[str] = []
    for ch in text:
        if ch in _PUNCT_PAIRS:
            stack.append(ch)
        elif ch in _PUNCT_PAIRS.values():
            if not stack:
                unmatched.append(ch)
                continue
            opener = stack.pop()
            if _PUNCT_PAIRS.get(opener) != ch:
                unmatched.append(opener)
                unmatched.append(ch)
    unmatched.extend(stack)
    return unmatched


class LanguageAuditor(BaseAuditor):
    """语言与术语审查器

    功能：
    1. 中英混合文本智能分段 → 分别提交 LanguageTool
    2. 半导体术语一致性检查
    3. 中英文混排规范检查 (空格、标点)
    """

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        # languagetool_url: rules.md 可注入 (见 rule_parser.extract_auditor_config);
        # 用 or 而非 .get(key, default) — 显式 None 键不得覆盖内置默认。
        self.lt_client = LanguageToolClient(
            base_url=(config.get("languagetool_url") or "http://localhost:8010/v2")
            if config
            else "http://localhost:8010/v2"
        )
        glossary_dir = config.get("glossary_dir") if config else None
        self.terminology = TerminologyChecker(glossary_dir)

        vocab_dir = config.get("vocab_dir") if config else None
        self.vocabulary = Vocabulary(vocab_dir)
        # 近似重复页阈值 (rules.md frontmatter parameters.near_duplicate_*)
        try:
            self.near_duplicate_similarity = float(
                (config or {}).get("near_duplicate_similarity", 0.90)
            )
        except (TypeError, ValueError):
            self.near_duplicate_similarity = 0.90
        try:
            self.near_duplicate_min_chars = max(
                1, int((config or {}).get("near_duplicate_min_chars", 40))
            )
        except (TypeError, ValueError):
            self.near_duplicate_min_chars = 40
        # 段级去重缓存（文档作用域：audit() 开始时重置，见 audit 内注释）
        self._lt_segment_cache: set[tuple[str, str]] = set()

    def audit(self, doc: Document) -> list[AuditFinding]:
        findings: list[AuditFinding] = []

        # 段级缓存按"文档"作用域：Web UI 用 @st.cache_resource 复用本审计器实例，
        # 旧实现把缓存留在实例上 → 第二份文档里与第一份相同的英文段不再提交，
        # LanguageTool 结果被静默吞掉（2026-11 审查实测：同文本第二份 0 请求）。
        self._lt_segment_cache = set()

        # 按页处理
        for page in doc.pages:
            page_text = page.all_text
            if not page_text.strip():
                continue

            page_label = f"第 {page.slide_number or page.index + 1} 页"

            # 0. 预处理: 收集并过滤白名单术语 (便于调试 + 确认 accept.txt 功能生效)
            page_terms = set(w.lower() for w in re.findall(r"[a-zA-Z]{3,}", page_text))
            if page_terms:
                accepted_on_page = self.vocabulary.filter_accepted(page_terms)
                if accepted_on_page:
                    logger.debug(
                        "第 %d 页白名单术语: %s",
                        page.index,
                        ", ".join(sorted(accepted_on_page)[:10]),
                    )

            # 1. 中英混合分段检查 (LanguageTool)
            findings.extend(self._check_text(page_text, page.index, page_label))

            # 2. 术语一致性
            findings.extend(self.terminology.check(page_text, page.index, page_label))

            # 3. 中英文混排规范
            findings.extend(self._check_mixed_formatting(page_text, page.index, page_label))

            # 3b. 中文基础语法/标点：始终执行，不依赖 LanguageTool 后端
            findings.extend(self._check_builtin_chinese_patterns(page_text, page.index, page_label))

            # 3c. 标点冗余/冲突/配对 + 高精度冗余表达
            findings.extend(self._check_punctuation(page_text, page.index, page_label))
            findings.extend(self._check_redundancy(page_text, page.index, page_label))

            # 3d. 项目符号末尾标点一致性 (页内)
            findings.extend(self._check_bullet_trailing_punctuation(page))

            # 4. 禁用词汇检查 (reject.txt)
            findings.extend(self._check_rejected_vocab(page_text, page.index, page_label))

            # 5. 演讲者备注也检查
            if page.notes:
                findings.extend(
                    self.terminology.check(page.notes, page.index, f"{page_label} (备注)")
                )

        # 6. 页眉/页脚/脚注 (DOCX): 只做语言/术语类检查（无独立版面几何）
        findings.extend(self._audit_auxiliary(doc))

        # 7. 文档级格式一致性 (2026-10-29): 日期/范围/单位写法、重复句、近似重复页
        findings.extend(self._check_date_format_consistency(doc))
        findings.extend(self._check_range_separator_consistency(doc))
        findings.extend(self._check_unit_spacing_consistency(doc))
        findings.extend(self._check_duplicate_sentences(doc))
        findings.extend(self._check_near_duplicate_pages(doc))

        return findings

    def _audit_auxiliary(self, doc: Document) -> list[AuditFinding]:
        """审查正文之外的辅助文本：页眉 / 页脚 / 脚注 (2026-10-29)。

        这些内容没有独立页面几何，只做与位置无关的语言/术语类检查。
        page_index=None 表示「非正文页」（2026-10-29 审查：原用 -1 哨兵，
        导出到 CSV/SARIF/HTML 会显示成 page 0 / 第 0 页）。
        """
        findings: list[AuditFinding] = []
        labels = {"header": "页眉", "footer": "页脚", "footnote": "脚注"}
        for elem in doc.auxiliary_elements:
            text = "\n".join(p.text for p in elem.paragraphs if p.text and p.text.strip())
            if not text.strip():
                continue
            label = labels.get(elem.placeholder_type or "", "正文外内容")
            findings.extend(self._check_mixed_formatting(text, None, label))
            findings.extend(self._check_builtin_chinese_patterns(text, None, label))
            findings.extend(self._check_punctuation(text, None, label))
            findings.extend(self._check_redundancy(text, None, label))
            findings.extend(self._check_rejected_vocab(text, None, label))
            findings.extend(self.terminology.check(text, None, label))
        return findings

    def _check_text(self, text: str, page_index: int, page_label: str) -> list[AuditFinding]:
        """提交 LanguageTool 检查"""
        findings: list[AuditFinding] = []

        if not self.lt_client.is_available:
            # LanguageTool 不可用时跳过 (仅警告一次)
            if not getattr(self, "_lt_unavailable_warned", False):
                logger.warning(
                    "LanguageTool 不可用，语言检查已跳过。"
                    "安装 pyspellchecker 可启用基础检查，或启动 Docker/Java 服务获得完整功能。"
                )
                self._lt_unavailable_warned = True
            return findings

        # 中英文分段 (先掩码代码/URL: 其中的标识符与 `--flag` 不是自然语言，
        # 不应送 LanguageTool/拼写检查 — 2026-11 审查)
        segments = self._segment_by_language(_mask_prose_noise(text))

        # 段级去重 + 同语言合批（2026-10-29 深度审查 P1）：
        # 旧实现逐段同步 HTTP（技术页实测 17 段 → 17 次请求/页，100 页 ≈1700 次），
        # 开 LanguageTool 后审查从亚秒级劣化到秒级。合并后每页每种语言最多 1 次
        # 请求；重复段（MES/DOE/模板句）跨页复用，不再重复提交。
        cache = self._lt_segment_cache
        grouped: dict[str, list[str]] = {}
        for seg_text, seg_lang in segments:
            # 英文段降低阈值以捕获短词拼写错误 (如 "teh", "recieve")
            min_len = 2 if seg_lang == "en" else 5
            stripped = seg_text.strip()
            if len(stripped) < min_len:
                continue
            key = (seg_lang, stripped)
            if key in cache:
                continue
            cache.add(key)
            grouped.setdefault(seg_lang, []).append(stripped)

        for seg_lang, texts in grouped.items():
            lang_code = "zh-CN" if seg_lang == "zh" else "en-US"
            matches = self.lt_client.check("\n\n".join(texts), language=lang_code)
            findings.extend(self._matches_to_findings(matches, seg_lang, page_index, page_label))

        return findings

    def _matches_to_findings(
        self, matches, seg_lang: str, page_index: int, page_label: str
    ) -> list[AuditFinding]:
        """LanguageTool matches → findings（含噪音规则与白名单过滤）。"""
        findings: list[AuditFinding] = []
        for match in matches:
            rule = match.get("rule", {})
            msg = match.get("message", "语法问题")
            ctx = match.get("context")
            context_text = ctx.get("text", "") if isinstance(ctx, dict) else ""
            replacements = match.get("replacements", [])
            suggestion = None
            if replacements:
                suggestion = "建议改为: " + " / ".join(r.get("value", "") for r in replacements[:3])

            # 过滤掉一些噪音规则
            if rule.get("category", {}).get("id") in ("TYPOGRAPHY",):
                continue
            # 中文基础模式已由 _check_builtin_chinese_patterns 始终执行；
            # Python 降级后端也会返回同一批 PY-ZH-GRAMMAR，跳过避免重复。
            if rule.get("id") == "PY-ZH-GRAMMAR":
                continue

            # 过滤 accept.txt 白名单术语 (如 FinFET, TSV 等半导体专业术语)
            if isinstance(ctx, dict):
                ctx_text = ctx.get("text", "")
                ctx_offset = ctx.get("offset", 0)
                ctx_length = ctx.get("length", 0)
                if ctx_length > 0 and 0 <= ctx_offset < len(ctx_text):
                    matched_word = ctx_text[ctx_offset : ctx_offset + ctx_length]
                    if matched_word and self.vocabulary.is_accepted(matched_word):
                        continue

            findings.append(
                AuditFinding(
                    type=FindingType.LANGUAGE,
                    severity=self._map_severity(rule.get("issueType", "")),
                    message=msg,
                    rule_id=rule.get("id", ""),
                    page_index=page_index,
                    location=page_label,
                    context=context_text[:120] if context_text else None,
                    suggestion=suggestion,
                    metadata={
                        "language": seg_lang,
                        "category": rule.get("category", {}).get("id", ""),
                    },
                )
            )
        return findings

    def _segment_by_language(self, text: str) -> list[tuple[str, str]]:
        """将混合文本按语言分为 (文本段, 语言) 列表"""
        segments: list[tuple[str, str]] = []
        current_text = ""
        current_lang = None

        i = 0
        while i < len(text):
            ch = text[i]
            is_cjk = bool(CJK_RE.match(ch))
            # 仅字母字符视为拉丁文本，数字/标点/空格等中性字符保持当前语言不切换
            is_latin = ch.isascii() and ch.isalpha() and not is_cjk

            if is_cjk:
                detected = "zh"
            elif is_latin:
                detected = "en"
            else:
                # 数字、标点、空格等中性字符 — 保持当前语言不变
                detected = current_lang or "zh"

            if current_lang is None:
                current_lang = detected

            if detected != current_lang:
                if current_text.strip():
                    segments.append((current_text, current_lang))
                current_text = ch
                current_lang = detected
            else:
                current_text += ch

            i += 1

        if current_text.strip():
            segments.append((current_text, current_lang or "zh"))

        # 合并过短的连续同语言段
        def _append_or_merge(
            buf_text: str, buf_lang: str | None, target: list[tuple[str, str]]
        ) -> None:
            """短段 (len < 10) 尝试与前段合并，否则直接追加。仅同语言时合并。"""
            if len(buf_text) < 10 and target and target[-1][1] == buf_lang:
                target[-1] = (target[-1][0] + buf_text, target[-1][1])
            else:
                target.append((buf_text, buf_lang))

        merged: list[tuple[str, str]] = []
        buffer_text = ""
        buffer_lang = None

        for seg_text, seg_lang in segments:
            if buffer_lang == seg_lang or buffer_lang is None:
                buffer_text += seg_text
                buffer_lang = seg_lang
            else:
                _append_or_merge(buffer_text, buffer_lang, merged)
                buffer_text = seg_text
                buffer_lang = seg_lang

        if buffer_text:
            _append_or_merge(buffer_text, buffer_lang, merged)

        return merged

    def _check_mixed_formatting(
        self, text: str, page_index: int | None, page_label: str
    ) -> list[AuditFinding]:
        """检查中英文混排格式。

        每种模式每页最多产生一条 consolidated finding（列出最多 5 个示例位置），
        避免对每个 CJK-Latin 边界产生独立 finding 导致报告泛滥。
        """
        findings: list[AuditFinding] = []

        # 掩码代码/URL 后再判定混排: 位置不变，因此 context 仍从原文切片
        masked = _mask_prose_noise(text)

        # 使用共享的预编译正则 (来自 text_utils)，避免重复编译
        checks = [
            (
                LATIN_CJK_BOUNDARY,
                "英文和中文之间建议加空格",
                "FMT-MIXED-001",
                FindingSeverity.INFO,
                lambda m: f"「{m.group(1) + m.group(2)}」→ 「{m.group(1)} {m.group(2)}」",
                10,
            ),
            (
                CJK_LATIN_BOUNDARY,
                "中文和英文之间建议加空格",
                "FMT-MIXED-002",
                FindingSeverity.INFO,
                lambda m: f"「{m.group(1) + m.group(2)}」→ 「{m.group(1)} {m.group(2)}」",
                10,
            ),
            (
                _LATIN_CHINESE_PUNCT,
                "英文后不应使用中文标点符号",
                "FMT-MIXED-003",
                FindingSeverity.WARNING,
                lambda m: f"将「{m.group(2)}」改为对应的英文标点",
                5,
            ),
        ]

        for pattern, msg, rule_id, severity, suggest_fn, ctx_radius in checks:
            # 一次性遍历：计数 + 捕获前 5 个匹配，避免 list(finditer) 全部物化
            MAX_EXAMPLES = 5
            total = 0
            examples: list = []
            for m in pattern.finditer(masked):
                # 英文后中文标点: 仅当标点紧跟一个英文词 (≥2 纯字母) 才报
                if rule_id == "FMT-MIXED-003" and not _latin_word_before(masked, m.start()):
                    continue
                total += 1
                if len(examples) < MAX_EXAMPLES:
                    examples.append(m)
            if total == 0:
                continue

            ctx_parts = [
                text[max(0, m.start() - ctx_radius) : m.end() + ctx_radius] for m in examples
            ]
            suggestions = list(dict.fromkeys(suggest_fn(m) for m in examples))  # dedup
            context_text = " | ".join(ctx_parts)

            findings.append(
                AuditFinding(
                    type=FindingType.FORMAT,
                    severity=severity,
                    message=f"{msg} ({total} 处)",
                    rule_id=rule_id,
                    page_index=page_index,
                    location=page_label,
                    context=context_text[:150],
                    suggestion="; ".join(suggestions[:3]),
                    metadata={"match_count": total, "rule": rule_id},
                )
            )

        return findings

    def _check_builtin_chinese_patterns(
        self, text: str, page_index: int, page_label: str
    ) -> list[AuditFinding]:
        """始终执行的中文基础语法/标点模式 (不依赖 LanguageTool 后端)。"""
        findings: list[AuditFinding] = []
        # 掩码代码/URL 后再匹配 (等长替换, offset 语义不变)
        for match in check_chinese_patterns(_mask_prose_noise(text)):
            ctx = match.get("context") or {}
            context_text = ctx.get("text", "") if isinstance(ctx, dict) else ""
            findings.append(
                AuditFinding(
                    type=FindingType.LANGUAGE,
                    severity=FindingSeverity.WARNING,
                    message=match.get("message", "中文语法/标点问题"),
                    rule_id="PY-ZH-GRAMMAR",
                    page_index=page_index,
                    location=page_label,
                    context=context_text[:120] if context_text else None,
                    suggestion="请根据提示检查该处中文表达或标点",
                    metadata={"offset": match.get("offset", 0)},
                )
            )
        return findings

    @staticmethod
    def _consolidated(
        findings: list[AuditFinding],
        *,
        rule_id: str,
        message: str,
        severity: FindingSeverity,
        matches: list,
        text: str,
        page_index: int,
        page_label: str,
        suggestion: str,
    ) -> None:
        """把同类标点问题聚合成一条 finding，避免逐字符刷屏。"""
        if not matches:
            return
        examples = []
        for m in matches[:3]:
            examples.append(text[max(0, m.start() - 10) : m.end() + 10].replace("\n", " "))
        findings.append(
            AuditFinding(
                type=FindingType.LANGUAGE,
                severity=severity,
                message=f"{message} ({len(matches)} 处)",
                rule_id=rule_id,
                page_index=page_index,
                location=page_label,
                context=" | ".join(examples)[:150],
                suggestion=suggestion,
                metadata={"match_count": len(matches), "rule": rule_id},
            )
        )

    # ── 文档级格式一致性 (2026-10-29) ────────────────────────

    def _check_date_format_consistency(self, doc: Document) -> list[AuditFinding]:
        """检测全文日期格式混用 (中文/ISO/斜杠)。"""
        found: dict[str, str] = {}
        for page in doc.pages:
            text = page.all_text
            for label, regex in _DATE_FORMAT_PATTERNS:
                if label in found:
                    continue
                m = regex.search(text)
                if m:
                    found[label] = m.group(0)
        if len(found) < 2:
            return []
        examples = "、".join(f"{label}「{ex}」" for label, ex in found.items())
        return [
            AuditFinding(
                type=FindingType.LANGUAGE,
                severity=FindingSeverity.INFO,
                message="日期格式混用（同一文档存在多种写法）",
                rule_id="PUNCT-008",
                page_index=None,
                location="全文",
                context=examples[:150],
                suggestion="统一为一种日期格式（推荐 ISO 8601，如 2026-10-29）",
                metadata={"formats": sorted(found)},
            )
        ]

    def _check_range_separator_consistency(self, doc: Document) -> list[AuditFinding]:
        """检测数值范围连接符混用 (3-5 / 3—5 / 3~5 / 3至5)。"""
        found: dict[str, str] = {}
        for page in doc.pages:
            text = _mask_dates(page.all_text)
            for m in _RANGE_SEPARATOR_RE.finditer(text):
                sep = m.group(1)
                label = _RANGE_CLASS.get(sep)
                if label and label not in found:
                    found[label] = m.group(0).strip()
        if len(found) < 2:
            return []
        examples = "、".join(f"{label}「{ex}」" for label, ex in found.items())
        return [
            AuditFinding(
                type=FindingType.LANGUAGE,
                severity=FindingSeverity.INFO,
                message="数值范围连接符混用",
                rule_id="PUNCT-009",
                page_index=None,
                location="全文",
                context=examples[:150],
                suggestion="全文统一范围写法（推荐半角连字符，如 3-5）",
                metadata={"separators": sorted(found)},
            )
        ]

    def _check_unit_spacing_consistency(self, doc: Document) -> list[AuditFinding]:
        """检测同一单位既有紧贴又有空格的混用 (10kg / 10 kg)。"""
        variants: dict[str, dict[str, str]] = {}
        for page in doc.pages:
            text = page.all_text
            for m in _UNIT_RE.finditer(text):
                number, unit = m.group(1), m.group(2)
                gap = text[m.start(1) + len(number) : m.start(2)]
                kind = "spaced" if gap else "tight"
                variants.setdefault(unit, {}).setdefault(kind, m.group(0))
        mixed = {unit: v for unit, v in variants.items() if len(v) == 2}
        if not mixed:
            return []
        examples = "、".join(
            f"{unit}: {v['tight']} / {v['spaced']}" for unit, v in sorted(mixed.items())[:5]
        )
        return [
            AuditFinding(
                type=FindingType.LANGUAGE,
                severity=FindingSeverity.INFO,
                message="数值与单位的空格用法不一致",
                rule_id="PUNCT-010",
                page_index=None,
                location="全文",
                context=examples[:150],
                suggestion="同一文档内统一写法（推荐数字与单位间加空格，如 10 kg）",
                metadata={"units": sorted(mixed)},
            )
        ]

    def _check_bullet_trailing_punctuation(self, page) -> list[AuditFinding]:
        """页内项目符号末尾标点不一致（部分有句号、部分没有）。"""
        bullet_texts: list[str] = []
        for elem in page.flattened_elements:
            for para in elem.paragraphs:
                text = (para.text or "").strip()
                if not text:
                    continue
                is_bullet = (
                    para.bullet_type in ("char", "number")
                    or SYMBOL_BULLET_RE.match(text)
                    or NUMBERED_BULLET_RE.match(text)
                    or LETTERED_BULLET_RE.match(text)
                )
                if is_bullet:
                    bullet_texts.append(_BULLET_MARKER_RE.sub("", text).strip())
        if len(bullet_texts) < 3:
            return []
        with_punct = [t for t in bullet_texts if t.endswith(_TERMINAL_PUNCT)]
        without_punct = [t for t in bullet_texts if not t.endswith(_TERMINAL_PUNCT)]
        if not with_punct or not without_punct:
            return []
        page_label = f"第 {page.slide_number or page.index + 1} 页"
        return [
            AuditFinding(
                type=FindingType.LANGUAGE,
                severity=FindingSeverity.INFO,
                message="项目符号末尾标点不一致",
                rule_id="TXT-BULLET-PUNCT",
                page_index=page.index,
                location=page_label,
                context=(
                    f"{len(with_punct)} 条以标点结尾，{len(without_punct)} 条没有；"
                    f"例: 「{with_punct[0][:40]}」/「{without_punct[0][:40]}」"
                )[:150],
                suggestion="同一层级项目符号统一：要么都加句号，要么都不加",
                metadata={"with_punct": len(with_punct), "without_punct": len(without_punct)},
            )
        ]

    def _check_duplicate_sentences(self, doc: Document) -> list[AuditFinding]:
        """跨页重复句子检测（归一化后完全相同的长句）。"""
        first_seen: dict[str, tuple[int, str]] = {}
        findings: list[AuditFinding] = []
        for page in doc.pages:
            for raw in _SENTENCE_SPLIT_RE.split(_body_text(page)):
                sentence = raw.strip()
                if len(sentence) < 12:
                    continue
                if not re.search(r"[\u4e00-\u9fffA-Za-z]", sentence):
                    continue
                norm = _normalize_sentence(sentence)
                if len(norm) < 8:
                    continue
                prev = first_seen.get(norm)
                if prev is None:
                    first_seen[norm] = (page.index, sentence)
                elif prev[0] != page.index and len(findings) < 10:
                    findings.append(
                        AuditFinding(
                            type=FindingType.LANGUAGE,
                            severity=FindingSeverity.INFO,
                            message=f"重复句子（与第 {prev[0] + 1} 页相同）",
                            rule_id="TXT-DUP-SENTENCE",
                            page_index=page.index,
                            location=f"第 {page.index + 1} 页",
                            context=sentence[:150],
                            suggestion="确认是否为有意重复；若为复制遗留请删除或改写",
                            metadata={"first_page": prev[0] + 1},
                        )
                    )
        return findings

    def _check_near_duplicate_pages(self, doc: Document) -> list[AuditFinding]:
        """近似重复页检测（字符二元组 Jaccard ≥ near_duplicate_similarity，至少 N 字）。"""
        entries: list[tuple[int, set[str]]] = []
        for page in doc.pages:
            norm = re.sub(r"\s+", "", _body_text(page))
            if len(norm) < self.near_duplicate_min_chars:
                continue
            entries.append((page.index, _bigrams(norm)))
        pairs: list[tuple[int, int, float]] = []
        for (i, si), (j, sj) in combinations(entries, 2):
            if not si or not sj:
                continue
            union = len(si | sj)
            if not union:
                continue
            similarity = len(si & sj) / union
            if similarity >= self.near_duplicate_similarity:
                pairs.append((i, j, similarity))
        pairs.sort(key=lambda p: -p[2])
        findings: list[AuditFinding] = []
        for i, j, similarity in pairs[:3]:
            findings.append(
                AuditFinding(
                    type=FindingType.LANGUAGE,
                    severity=FindingSeverity.WARNING,
                    message=(
                        f"第 {i + 1} 页与第 {j + 1} 页内容高度相似（相似度 {similarity:.0%}）"
                    ),
                    rule_id="TXT-NEAR-DUP",
                    page_index=j,
                    location=f"第 {j + 1} 页",
                    context=f"与第 {i + 1} 页重复度 {similarity:.0%}",
                    suggestion="确认是否为误复制页；确需保留可在报告中豁免",
                    metadata={"similar_to": i + 1, "similarity": round(similarity, 3)},
                )
            )
        return findings

    def _check_punctuation(
        self, text: str, page_index: int | None, page_label: str
    ) -> list[AuditFinding]:
        """标点冗余/冲突/全半角/配对检查 (2026-10-28)。

        - 重复 ; : ! ?（，，/。。/、、 已由 PY-ZH-GRAMMAR 覆盖）
        - 相邻冲突标点（，。 / 。， / 、， 等）
        - 中文后使用英文标点
        - 全角字母/数字
        - 括号/引号不配对
        - 中文语境下的 ... / -- 格式
        """
        findings: list[AuditFinding] = []
        masked = _mask_prose_noise(text)

        repeat_matches = list(_PUNCT_REPEAT_RE.finditer(masked))
        self._consolidated(
            findings,
            rule_id="PUNCT-001",
            message="检测到重复标点",
            severity=FindingSeverity.WARNING,
            matches=repeat_matches,
            text=text,
            page_index=page_index,
            page_label=page_label,
            suggestion="删除多余的重复标点",
        )

        adjacent = [m for m in _PUNCT_ADJACENT_RE.finditer(masked) if m.group(1) != m.group(2)]
        self._consolidated(
            findings,
            rule_id="PUNCT-002",
            message="检测到相邻冲突标点",
            severity=FindingSeverity.WARNING,
            matches=adjacent,
            text=text,
            page_index=page_index,
            page_label=page_label,
            suggestion="保留一个符合语义的标点，删除其余冲突标点",
        )

        cjk_ascii = list(_CJK_ASCII_PUNCT_RE.finditer(masked))
        self._consolidated(
            findings,
            rule_id="PUNCT-003",
            message="中文后使用了英文标点",
            severity=FindingSeverity.WARNING,
            matches=cjk_ascii,
            text=text,
            page_index=page_index,
            page_label=page_label,
            suggestion="中文语句请使用全角标点（，。；：！？）",
        )

        fullwidth = list(_FULLWIDTH_ALNUM_RE.finditer(masked))
        self._consolidated(
            findings,
            rule_id="PUNCT-004",
            message="检测到全角字母/数字",
            severity=FindingSeverity.INFO,
            matches=fullwidth,
            text=text,
            page_index=page_index,
            page_label=page_label,
            suggestion="技术文档中的英文/数字建议使用半角字符",
        )

        unmatched = _unmatched_pairs(masked)
        if unmatched:
            findings.append(
                AuditFinding(
                    type=FindingType.LANGUAGE,
                    severity=FindingSeverity.WARNING,
                    message=f"括号/引号不配对 ({len(unmatched)} 个)",
                    rule_id="PUNCT-005",
                    page_index=page_index,
                    location=page_label,
                    context="".join(unmatched)[:120],
                    suggestion="检查中文括号/引号是否成对出现",
                    metadata={"unmatched": unmatched[:20]},
                )
            )

        if CJK_RE.search(text):
            ellipsis = list(_ELLIPSIS_RE.finditer(masked))
            self._consolidated(
                findings,
                rule_id="PUNCT-006",
                message="中文语境使用了英文省略号",
                severity=FindingSeverity.INFO,
                matches=ellipsis,
                text=text,
                page_index=page_index,
                page_label=page_label,
                suggestion="中文省略号建议使用“……”",
            )
            double_hyphen = list(_DOUBLE_HYPHEN_RE.finditer(masked))
            self._consolidated(
                findings,
                rule_id="PUNCT-007",
                message="中文语境使用了英文双连字符破折号",
                severity=FindingSeverity.INFO,
                matches=double_hyphen,
                text=text,
                page_index=page_index,
                page_label=page_label,
                suggestion="中文破折号建议使用“——”",
            )

        return findings

    def _check_redundancy(
        self, text: str, page_index: int | None, page_label: str
    ) -> list[AuditFinding]:
        """高精度中文冗余表达检查 (2026-10-28)。"""
        findings: list[AuditFinding] = []
        masked = _mask_prose_noise(text)
        for pattern, message, suggestion in _REDUNDANT_PATTERNS:
            matches = list(pattern.finditer(masked))
            self._consolidated(
                findings,
                rule_id="TXT-REDUNDANT",
                message=message,
                severity=FindingSeverity.INFO,
                matches=matches,
                text=text,
                page_index=page_index,
                page_label=page_label,
                suggestion=suggestion,
            )
        return findings

    def _check_rejected_vocab(
        self, text: str, page_index: int, page_label: str
    ) -> list[AuditFinding]:
        """检查禁用词汇 (reject.txt)"""
        findings: list[AuditFinding] = []
        hits = self.vocabulary.should_reject(text)
        for word, reason in hits:
            findings.append(
                AuditFinding(
                    type=FindingType.LANGUAGE,
                    severity=FindingSeverity.WARNING,
                    message=f"使用了应避免的词汇: 「{word}」— {reason}",
                    rule_id="VOCAB-REJECT",
                    page_index=page_index,
                    location=page_label,
                    context=word[:150],
                    suggestion="请使用更正式或更准确的表达",
                )
            )
        return findings

    @staticmethod
    def _map_severity(issue_type: str) -> FindingSeverity:
        """LanguageTool issueType → FindingSeverity"""
        mapping = {
            "misspelling": FindingSeverity.ERROR,
            "grammar": FindingSeverity.ERROR,
            "duplication": FindingSeverity.WARNING,
            "style": FindingSeverity.WARNING,
            "hint": FindingSeverity.INFO,
            "typographical": FindingSeverity.INFO,
        }
        return mapping.get(issue_type, FindingSeverity.WARNING)
