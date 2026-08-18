"""语言审查器 — 中英混合语法检查 + 术语一致性"""

import logging
import re

from src.auditors.base import BaseAuditor
from src.engines.languagetool import LanguageToolClient
from src.engines.terminology import TerminologyChecker
from src.engines.vocabulary import Vocabulary
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity, FindingType
from src.text_utils import (
    CJK_LATIN_BOUNDARY,
    CJK_RE,
    LATIN_CJK_BOUNDARY,
)
from src.text_utils import (
    LATIN_CHINESE_PUNCT as _LATIN_CHINESE_PUNCT,
)

logger = logging.getLogger(__name__)

# 英文字符检测
LATIN_RE = re.compile(r"[a-zA-Z]{2,}")


class LanguageAuditor(BaseAuditor):
    """语言与术语审查器

    功能：
    1. 中英混合文本智能分段 → 分别提交 LanguageTool
    2. 半导体术语一致性检查
    3. 中英文混排规范检查 (空格、标点)
    """

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.lt_client = LanguageToolClient(
            base_url=config.get("languagetool_url", "http://localhost:8010/v2")
            if config
            else "http://localhost:8010/v2"
        )
        glossary_dir = config.get("glossary_dir") if config else None
        self.terminology = TerminologyChecker(glossary_dir)

        vocab_dir = config.get("vocab_dir") if config else None
        self.vocabulary = Vocabulary(vocab_dir)

    def audit(self, doc: Document) -> list[AuditFinding]:
        findings: list[AuditFinding] = []

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

            # 4. 禁用词汇检查 (reject.txt)
            findings.extend(self._check_rejected_vocab(page_text, page.index, page_label))

            # 5. 演讲者备注也检查
            if page.notes:
                findings.extend(
                    self.terminology.check(page.notes, page.index, f"{page_label} (备注)")
                )

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

        # 中英文分段
        segments = self._segment_by_language(text)

        for seg_text, seg_lang in segments:
            # 英文段降低阈值以捕获短词拼写错误 (如 "teh", "recieve")
            min_len = 2 if seg_lang == "en" else 5
            if len(seg_text.strip()) < min_len:
                continue

            lang_code = "zh-CN" if seg_lang == "zh" else "en-US"
            matches = self.lt_client.check(seg_text, language=lang_code)

            for match in matches:
                rule = match.get("rule", {})
                msg = match.get("message", "语法问题")
                ctx = match.get("context")
                context_text = ctx.get("text", "") if isinstance(ctx, dict) else ""
                replacements = match.get("replacements", [])
                suggestion = None
                if replacements:
                    suggestion = "建议改为: " + " / ".join(
                        r.get("value", "") for r in replacements[:3]
                    )

                # 过滤掉一些噪音规则
                if rule.get("category", {}).get("id") in ("TYPOGRAPHY",):
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
        self, text: str, page_index: int, page_label: str
    ) -> list[AuditFinding]:
        """检查中英文混排格式。

        每种模式每页最多产生一条 consolidated finding（列出最多 5 个示例位置），
        避免对每个 CJK-Latin 边界产生独立 finding 导致报告泛滥。
        """
        findings: list[AuditFinding] = []

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
            for m in pattern.finditer(text):
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

    def reset(self):
        """重置语言检查器缓存状态，强制重新探测 LanguageTool 后端。

        适用于 LanguageTool 服务在审计运行中途启动的场景。
        """
        self._lt_unavailable_warned = False
        self.lt_client.reset()

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
