"""自定义规则审查器 — 基于 rules.md 的规则引擎"""

import logging
import re
from pathlib import Path
from typing import Any

from src.auditors.base import BaseAuditor
from src.engines.check_registry import CHECK_REGISTRY, CheckSpec  # noqa: F401 — 向后兼容 re-export
from src.engines.rule_parser import AuditRule, parse_rules_md
from src.engines.vocabulary import Vocabulary
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity, FindingType
from src.text_utils import mask_prose_noise

logger = logging.getLogger(__name__)


class CustomRulesAuditor(BaseAuditor):
    """执行 rules.md 中定义的自定义审查规则

    规则类型：
    - regex: 正则模式匹配
    - check: 检查类型标识 (如 first_slide_has_title_layout 等)
    - 参数: 通过 params 传递 (如 allowed_fonts, required_sections)

    dispatch 检查由 src/engines/check_registry.py 的 CHECK_REGISTRY 派生（单一真相来源，
    注册表置于 Engine 层以避免 Engine→Auditor 反向依赖）。
    """

    # ── 派生: check_type → (auditor_key, method_name, per_page, pptx_only) ──
    _DISPATCH = {
        check_type: (spec.auditor, spec.method, spec.per_page, spec.pptx_only)
        for check_type, spec in CHECK_REGISTRY.items()
    }

    @classmethod
    def skip_checks_for(cls, auditor_key: str) -> list[str]:
        """返回某 Auditor 在 pipeline 模式下应跳过的内部守卫键。

        pipeline 用它替代手写 `_skip_checks` 列表：dispatch 注册与跳过名单
        永远一致，不会出现"注册了但没跳过 → 重复执行"或反之。
        """
        return [
            spec.skip_key or check_type
            for check_type, spec in CHECK_REGISTRY.items()
            if spec.auditor == auditor_key
        ]

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
                errors.append(f"_DISPATCH['{check_type}']: unknown auditor key '{key}'")
                continue
            if not hasattr(auditor_cls, method_name):
                errors.append(
                    f"_DISPATCH['{check_type}']: {auditor_cls.__name__}.{method_name}() not found"
                )
        return errors

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.rules_path = config.get("rules_path", "rules.md") if config else "rules.md"
        # 可选: TERM-* regex 规则可复用 vocab/accept.txt 白名单。
        # 未传 vocab_dir 时保持旧行为（不加载白名单），兼容独立使用。
        self.vocab_dir = config.get("vocab_dir") if config else None
        self._vocabulary = Vocabulary(self.vocab_dir) if self.vocab_dir else None
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
                findings.append(
                    AuditFinding(
                        type=FindingType.SYSTEM,
                        severity=FindingSeverity.ERROR,
                        message=f"规则 '{rule.rule_id}' 执行失败: {e}",
                        rule_id="SYS-ERROR",
                        location="系统",
                        # context 前缀带 rule_id (2026-09-06 审查 E-1): 两条不同规则
                        # 抛出相同异常文本时 dedup_key 不再碰撞折叠
                        context=f"rule={rule.rule_id}: {e}"[:120],
                        suggestion="请检查文档内容或规则配置",
                        metadata={"rule_id": rule.rule_id, "error": str(e)},
                    )
                )

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
            # 与"失败可见性"哲学一致: 无效正则不能只 warning 后静默返回空，
            # 否则用户改坏 rules.md 后报告仍显示"干净"。生成 SYS-ERROR 保证 UI 可见。
            logger.warning("规则 %s 的正则无效: %s", rule.rule_id, e, exc_info=True)
            findings.append(
                AuditFinding(
                    type=FindingType.SYSTEM,
                    severity=FindingSeverity.ERROR,
                    message=f"规则 '{rule.rule_id}' 的正则表达式无效: {e}",
                    rule_id="SYS-ERROR",
                    location="系统",
                    context=f"rule={rule.rule_id} pattern={pattern_str[:80]}"[:120],
                    suggestion="请检查 rules.md 中该规则的 '模式' 是否为合法正则",
                    metadata={"rule_id": rule.rule_id, "error": str(e)},
                )
            )
            return findings

        # 仅首次出现: 同一匹配文本只报告第一次；用于 TERM-003 避免每页重复。
        # 白名单: 复用 vocab/accept.txt，避免已认可技术缩写被当作"未翻译"。
        first_only = str(rule.params.get("仅首次出现", "")).lower() in ("true", "1", "yes")
        use_whitelist = str(rule.params.get("排除白名单", "")).lower() in ("true", "1", "yes")
        seen_terms: set[str] = set()

        for page in doc.pages:
            # 代码块/URL 内的文本不是正文用法 (如代码常量里的缩写)；
            # 掩码等长替换、字符位置不变，context 仍可回原文切片
            text = mask_prose_noise(page.all_text)
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
                    matched_term = match.group(0)
                    # 定义场景: 命中位于括号对内 (如 "全称 (TSV)"), 跳过。
                    # 仅首次出现模式下也标记为已见，后续重复不再报告。
                    if any(match.start() >= lo and match.end() <= hi for lo, hi in paren_ranges):
                        if first_only:
                            seen_terms.add(matched_term)
                        continue
                    # 英文 (中文) 定义格式: 缩写后紧跟括号内容 → 视为已附翻译。
                    # 仅首次出现模式需要标记已见，避免后续使用再次报告。
                    if first_only and re.match(
                        r"\s*[（(][^）)]*[）)]",
                        text[match.end() : match.end() + 80],
                    ):
                        seen_terms.add(matched_term)
                        continue
                    if use_whitelist and self._vocabulary is not None:
                        if self._vocabulary.is_accepted(matched_term):
                            if first_only:
                                seen_terms.add(matched_term)
                            continue
                    if first_only:
                        if matched_term in seen_terms:
                            continue
                        seen_terms.add(matched_term)
                    suggestions = rule.params.get("suggestion", "")
                    findings.append(
                        AuditFinding(
                            type=FindingType.CUSTOM,
                            severity=severity,
                            message=rule.description,
                            rule_id=rule.rule_id,
                            page_index=page.index,
                            location=f"第 {page.slide_number or page.index + 1} 页",
                            context=matched_term[:100],
                            suggestion=suggestions,
                        )
                    )

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
            # 用 rules.md 声明的严重度覆盖审计器内部默认值 (配置驱动设计, 2026-08 审查 L9):
            # rules.md 是严重度的唯一来源 — dispatch 委托的审计器方法只是"检测器",
            # 其内置严重度仅是代码内兜底；此处统一覆盖保证同一条规则在不同
            # 文档/环境下严重度一致且可由用户通过 rules.md 配置调整。
            for f in findings:
                f.severity = severity
        else:
            logger.warning(
                "未知的 check_type '%s' (规则 %s) — 不在 _DISPATCH 表中，已跳过。"
                " 检查 rules.md 中是否有拼写错误。",
                check_type,
                rule.rule_id,
            )
            # 与"失败可见性"哲学一致: 未知 check_type 转 SYS-ERROR, UI 可见
            findings.append(
                AuditFinding(
                    type=FindingType.SYSTEM,
                    severity=FindingSeverity.ERROR,
                    message=f"规则 '{rule.rule_id}' 的 check_type '{check_type}' 未注册，检查未执行",
                    rule_id="SYS-ERROR",
                    location="系统",
                    context=f"check_type={check_type} rule_id={rule.rule_id}"[:120],
                    suggestion="检查 rules.md 中 '检查' 键的拼写是否与 _DISPATCH 表一致",
                    metadata={"rule_id": rule.rule_id, "check_type": check_type},
                )
            )

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

        配置键集由 `src/engines/auditor_config.build_auditor_configs` 统一定义
        （与 pipeline.build_auditors 共用），回退路径不再手写第二份 dict。
        """
        from src.auditors.factual import FactualAuditor
        from src.auditors.format import FormatAuditor
        from src.auditors.structure import StructureAuditor
        from src.engines.auditor_config import build_auditor_configs

        configs = build_auditor_configs(
            self._resolve_auditor_config(),
            enabled_rule_ids={r.rule_id for r in self.rules},
            vocab_dir=self.vocab_dir,
        )
        if key == "sa":
            return StructureAuditor(config=configs["sa"])
        if key == "fa":
            return FormatAuditor(config=configs["fa"])
        if key == "fca":
            return FactualAuditor(config=configs["fca"])
        raise ValueError(f"Unknown auditor key: {key}")

    def _resolve_auditor_config(self) -> dict:
        """从 rules 提取并缓存配置（含 rules.md frontmatter 全局参数）。"""
        if self._auditor_cfg_cache is not None:
            return self._auditor_cfg_cache
        from src.engines.rule_parser import extract_auditor_config, parse_rules_globals

        globals_ = {}
        if self.rules_path:
            globals_ = parse_rules_globals(self.rules_path)
        cfg = extract_auditor_config(self.rules, globals_)
        if self.config:
            for k, v in self.config.items():
                if k != "rules_path":
                    cfg[k] = v
        self._auditor_cfg_cache = cfg
        return cfg
