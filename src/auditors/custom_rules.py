"""自定义规则审查器 — 基于 rules.md 的规则引擎"""

import logging
import re
from pathlib import Path
from typing import Any

from src.auditors.base import BaseAuditor
from src.engines.rule_parser import AuditRule, parse_rules_md
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity, FindingType

logger = logging.getLogger(__name__)


class CustomRulesAuditor(BaseAuditor):
    """执行 rules.md 中定义的自定义审查规则

    规则类型：
    - regex: 正则模式匹配
    - check: 检查类型标识 (如 first_slide_has_title_layout 等)
    - 参数: 通过 params 传递 (如 allowed_fonts, required_sections)
    """

    # ── Check type dispatch: check_type → (auditor_key, method_name, per_page, pptx_only) ──
    # auditor_key: "sa"=structure, "fa"=format, "fca"=factual
    # NOTE: "la" (LanguageAuditor) 故意排除 — 语言检查依赖 lt_client/vocabulary/terminology
    # 有状态实例，始终直接运行，不走 dispatch 委托机制。
    _DISPATCH = {
        "first_slide_has_title_layout":     ("sa",  "_check_title_slide",               False, True),
        "figure_numbering_sequential":      ("sa",  "_check_figure_numbering",          False, False),
        "heading_level_sequential":         ("sa",  "_check_heading_levels",            False, False),
        "numeric_cross_reference":          ("fca", "_check_numeric_consistency",       False, False),
        "abbreviation_first_defined":       ("fca", "_check_abbreviation_first_defined",False, False),
        "abbreviation_defined_never_used":  ("fca", "_check_abbreviation_defined_never_used", False, False),
        "abbreviation_multiply_defined":    ("fca", "_check_abbreviation_multiply_defined", False, False),
        "abbreviation_used_before_defined": ("fca", "_check_abbreviation_used_before_defined", False, False),
        "every_slide_has_conclusion":       ("sa",  "_check_every_slide_has_conclusion",False, False),
        "duplicate_title":                  ("sa",  "_check_duplicate_title",           False, False),
        "title_trailing_punctuation":       ("sa",  "_check_title_trailing_punctuation", True, False),
        "figure_caption_format":            ("sa",  "_check_figure_caption_format",      False, False),
        "element_overflow":                 ("fa",  "_check_element_overflow",           True, False),
        "empty_placeholder":                ("fa",  "_check_empty_placeholders",        True, True),
        "bullet_consistency":               ("fa",  "_check_bullet_consistency",         True, False),
        "per_page_char_limit":              ("fa",  "_check_per_page_char_limit",        True, False),
        "table_contrast":                   ("fa",  "_check_table_contrast",             True, False),
        "slide_structure_consistency":      ("sa",  "_check_slide_structure_consistency", False, True),
        "title_length":                     ("sa",  "_check_title_length",               False, False),
    }

    # ── Severity mapping ───────────────────────────────────────
    _SEVERITY_MAP = {
        "error": FindingSeverity.ERROR,
        "warning": FindingSeverity.WARNING,
        "info": FindingSeverity.INFO,
    }

    @classmethod
    def validate_dispatch(cls) -> list[str]:
        """验证 _DISPATCH 表中所有方法存在于对应审计器类上。

        应在测试中调用此方法，确保重构时 dispatch 不会静默断裂。

        Returns:
            错误信息列表，空列表表示验证通过。
        """
        from src.auditors.factual import FactualAuditor
        from src.auditors.format import FormatAuditor
        from src.auditors.structure import StructureAuditor

        AUDITOR_CLS_MAP = {
            "sa": StructureAuditor,
            "fa": FormatAuditor,
            "fca": FactualAuditor,
        }
        errors: list[str] = []
        for check_type, (key, method_name, _per_page, _pptx_only) in cls._DISPATCH.items():
            auditor_cls = AUDITOR_CLS_MAP.get(key)
            if auditor_cls is None:
                errors.append(
                    f"_DISPATCH['{check_type}']: unknown auditor key '{key}'"
                )
                continue
            if not hasattr(auditor_cls, method_name):
                errors.append(
                    f"_DISPATCH['{check_type}']: {auditor_cls.__name__}"
                    f".{method_name}() not found"
                )
        return errors

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.rules_path = config.get("rules_path", "rules.md") if config else "rules.md"
        self.rules: list[AuditRule] = []
        self._loaded = False
        # 委托审计器实例 — 由 pipeline 注入，避免重复创建
        self._structure_auditor = None
        self._format_auditor = None
        self._factual_auditor = None
        # 实例级缓存
        self._auditor_cache: dict[str, BaseAuditor] = {}
        self._auditor_cfg_cache: dict[str, Any] | None = None

    def load_rules(self, rules_path: str | Path | None = None) -> None:
        """加载 rules.md"""
        path = rules_path or self.rules_path
        self.rules = parse_rules_md(path)
        self._loaded = True
        logger.info("已加载 %d 条自定义规则", len(self.rules))

    def set_delegate_auditors(
        self,
        structure_auditor: BaseAuditor | None = None,
        format_auditor: BaseAuditor | None = None,
        factual_auditor: BaseAuditor | None = None,
    ) -> None:
        """注入主流水线中的审计器实例，消除重复创建和重复执行。

        pipeline.build_auditors() 在构建 CustomRulesAuditor 后调用此方法，
        传入已配置好的 StructureAuditor / FormatAuditor / FactualAuditor 引用。
        CustomRulesAuditor 的 check 类型规则将直接调用这些实例的方法，
        而非创建新的审计器。
        """
        if structure_auditor is not None:
            self._structure_auditor = structure_auditor
        if format_auditor is not None:
            self._format_auditor = format_auditor
        if factual_auditor is not None:
            self._factual_auditor = factual_auditor

    def audit(self, doc: Document) -> list[AuditFinding]:
        if not self._loaded:
            self.load_rules()

        findings: list[AuditFinding] = []

        for rule in self.rules:
            try:
                findings.extend(self._execute_rule(rule, doc))
            except Exception as e:
                # 规则执行失败不静默吞掉 — 生成 SYS-ERROR finding 保证 UI 可见
                # (2026-08 全量审查: 曾仅 logger.warning, 报告"正常"完成但规则静默缺失)
                logger.warning("规则 %s 执行失败: %s", rule.rule_id, e, exc_info=True)
                # context 带错误摘要: 防止多条失败被 dedup_key 折叠为一条
                # (dedup_key = type|rule_id|page|context 哈希, SYS-ERROR 固定
                #  rule_id/page, 若 context 为 None 则全部碰撞)
                findings.append(AuditFinding(
                    type=FindingType.CUSTOM,
                    severity=FindingSeverity.ERROR,
                    message=f"规则 '{rule.rule_id}' 执行失败: {e}",
                    rule_id="SYS-ERROR",
                    location="系统",
                    context=str(e)[:120],
                    suggestion="请检查文档内容或规则配置",
                    metadata={"rule_id": rule.rule_id, "error": str(e)},
                ))

        return findings

    def _execute_rule(self, rule: AuditRule, doc: Document) -> list[AuditFinding]:
        """执行单条规则"""
        findings: list[AuditFinding] = []

        severity = self._SEVERITY_MAP.get(rule.severity, FindingSeverity.INFO)

        # ── regex 类型 ───────────────────────────────────────
        if rule.category == "terminology" and "pattern" in rule.params:
            findings.extend(self._execute_regex_rule(rule, doc, severity))

        # ── check 类型 (elif 确保与 regex 互斥，避免 "regex" 触发未知 check_type 警告) ──
        elif rule.check_type:
            findings.extend(self._execute_check_rule(rule, doc, severity))

        return findings

    def _execute_regex_rule(
        self, rule: AuditRule, doc: Document, severity: FindingSeverity
    ) -> list[AuditFinding]:
        """执行正则表达式规则"""
        findings: list[AuditFinding] = []
        pattern_str = rule.params.get("pattern", "")
        if not pattern_str:
            return findings

        try:
            # 大小写敏感规则 (如 TERM-003 仅匹配术语特征) 不传 IGNORECASE
            if str(rule.params.get("大小写敏感", "")).lower() in ("true", "1", "yes"):
                compiled = re.compile(pattern_str)
            else:
                compiled = re.compile(pattern_str, re.IGNORECASE)
        except re.error as e:
            logger.warning("规则 %s 的正则无效: %s", rule.rule_id, e)
            return findings

        for page in doc.pages:
            text = page.all_text
            # 仅中文页面: 页面无 CJK 字符时跳过 (如 TERM-003 中英混排规则对纯英文页无意义)
            # 布尔解析统一: "false"/"0" 等字符串不得误判为真
            if str(rule.params.get("仅中文页面", "")).lower() in ("true", "1", "yes") and not any(
                "\u4e00" <= ch <= "\u9fff" for ch in text
            ):
                continue
            # 排除括号内匹配: 预计算 [（(]...[）)] 区间, 跳过区间内的命中
            # (如 TERM-003 不应标记 'TSV (Through Silicon Via)' 中括号内的全称词)
            paren_ranges: list[tuple[int, int]] = []
            if str(rule.params.get("排除括号内", "")).lower() in ("true", "1", "yes"):
                opens = [m.start() for m in re.finditer(r"[（(]", text)]
                closes = [m.start() for m in re.finditer(r"[）)]", text)]
                ci = 0
                for op in opens:
                    while ci < len(closes) and closes[ci] <= op:
                        ci += 1
                    if ci < len(closes):
                        paren_ranges.append((op + 1, closes[ci]))
                        ci += 1
            matches = list(compiled.finditer(text))
            if matches:
                for match in matches:
                    if any(
                        match.start() >= lo and match.end() <= hi
                        for lo, hi in paren_ranges
                    ):
                        continue  # 命中位于括号对内 (定义场景), 跳过
                    suggestions = rule.params.get("suggestion", "")
                    findings.append(AuditFinding(
                        type=FindingType.CUSTOM,
                        severity=severity,
                        message=rule.description,
                        rule_id=rule.rule_id,
                        page_index=page.index,
                        location=f"第 {page.slide_number or page.index+1} 页",
                        context=match.group(0)[:100],
                        suggestion=suggestions,
                    ))

        return findings

    def _execute_check_rule(
        self, rule: AuditRule, doc: Document, severity: FindingSeverity
    ) -> list[AuditFinding]:
        """执行 check 类型规则。所有检查委托给对应的 Auditor 内部方法。

        优先使用 pipeline 注入的审计器实例（消除重复创建和重复执行），
        若未注入则回退到创建新实例（兼容独立使用场景）。
        """
        findings: list[AuditFinding] = []
        check_type = rule.check_type

        dispatch_entry = self._DISPATCH.get(check_type)
        if dispatch_entry is not None:
            auditor_key, method_name, is_per_page, is_pptx_only = dispatch_entry
            if is_pptx_only and doc.format != "pptx":
                return findings
            auditor = self._resolve_auditor(auditor_key)
            method = getattr(auditor, method_name)
            if is_per_page:
                for page in doc.pages:
                    findings.extend(method(page, doc))
            else:
                findings.extend(method(doc))
            # 用 rules.md 声明的严重度覆盖审计器内部默认值 (配置驱动原则)
            for f in findings:
                f.severity = severity
        else:
            logger.warning(
                "未知的 check_type '%s' (规则 %s) — 不在 _DISPATCH 表中，已跳过。"
                " 检查 rules.md 中是否有拼写错误。",
                check_type, rule.rule_id,
            )
            # 与"失败可见性"哲学一致: 未知 check_type 转 SYS-ERROR, UI 可见
            findings.append(AuditFinding(
                type=FindingType.CUSTOM,
                severity=FindingSeverity.ERROR,
                message=f"规则 '{rule.rule_id}' 的 check_type '{check_type}' 未注册，检查未执行",
                rule_id="SYS-ERROR",
                location="系统",
                context=f"check_type={check_type} rule_id={rule.rule_id}"[:120],
                suggestion="检查 rules.md 中 '检查' 键的拼写是否与 _DISPATCH 表一致",
                metadata={"rule_id": rule.rule_id, "check_type": check_type},
            ))

        return findings

    def _resolve_auditor(self, key: str):
        """返回指定类型的审计器实例 (优先注入 → 回退创建, 带缓存)。

        key: "sa" (StructureAuditor), "fa" (FormatAuditor), "fca" (FactualAuditor)
        """
        if key in self._auditor_cache:
            return self._auditor_cache[key]

        # 优先使用注入的审计器实例
        injected_map = {
            "sa": self._structure_auditor,
            "fa": self._format_auditor,
            "fca": self._factual_auditor,
        }
        if injected_map.get(key) is not None:
            auditor = injected_map[key]
        else:
            auditor = self._create_auditor(key)
        self._auditor_cache[key] = auditor
        return auditor

    def _create_auditor(self, key: str):
        """回退路径: 从 rules.md 配置创建新的审计器实例。

        独立模式(无 pipeline 注入)下使用此路径 — 不需要 _skip_checks，
        因为没有 CustomRulesAuditor 分发来实现双重执行。
        """
        from src.auditors.factual import FactualAuditor
        from src.auditors.format import FormatAuditor
        from src.auditors.structure import StructureAuditor

        cfg = self._resolve_auditor_config()

        if key == "sa":
            return StructureAuditor(config={
                "required_sections": cfg.get("required_sections", []),
                "conclusion_keywords": cfg.get("conclusion_keywords", []),
                "exempt_layouts": cfg.get("exempt_layouts", []),
                "max_english_words": cfg.get("max_english_words", 10),
                "max_chinese_chars_title": cfg.get("max_chinese_chars_title", 40),
                # 陷阱 #4: 回退路径 config 键集必须与 build_auditors 一致
                "min_title_font_size": cfg.get("min_title_font_size", 28),
            })
        elif key == "fa":
            return FormatAuditor(config={
                "allowed_fonts": cfg.get("allowed_fonts", []),
                "title_size_range": cfg.get("title_size_range"),
                "body_size_range": cfg.get("body_size_range"),
                "max_chinese_chars": cfg.get("max_chinese_chars"),
                "max_english_chars": cfg.get("max_english_chars"),
                "max_explicit_newlines": cfg.get("max_explicit_newlines"),
                "max_chars_per_page": cfg.get("max_chars_per_page"),
                # 陷阱 #4: 回退路径 config 键集必须与 build_auditors 一致
                "min_contrast": cfg.get("min_contrast", 4.5),
                "large_text_min_contrast": cfg.get("large_text_min_contrast", 3.0),
                "large_text_threshold": cfg.get("large_text_threshold", 18),
            })
        elif key == "fca":
            return FactualAuditor(config=cfg)
        else:
            raise ValueError(f"Unknown auditor key: {key}")

    def _resolve_auditor_config(self) -> dict:
        """从 rules 提取并缓存配置。"""
        if self._auditor_cfg_cache is not None:
            return self._auditor_cfg_cache
        from src.engines.rule_parser import extract_auditor_config
        cfg = extract_auditor_config(self.rules)
        if self.config:
            for k, v in self.config.items():
                if k != "rules_path":
                    cfg[k] = v
        self._auditor_cfg_cache = cfg
        return cfg
