"""配置校验 — rules.md / glossary/*.yaml / vocab/*.txt 的显式失败。

运行时各加载器对非法配置是「告警后降级」（不能因为一处笔误阻断审查）；
本模块提供**主动校验**，由 `docaudit rules validate` 暴露，让配置错误在
提交/CI 阶段显式失败（2026-10-29 补齐 R-24 剩余项）。

只做静态检查，不执行审查，不需要文档输入。
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.engines.check_registry import CHECK_REGISTRY
from src.engines.rule_parser import parse_rules_md

logger = logging.getLogger(__name__)

_VALID_SEVERITIES = {"error", "warning", "info"}
_RULE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d{3}(?:-[A-Z])?$")
_BOOL_KEYS = ("仅中文页面", "大小写敏感", "排除括号内", "排除白名单", "仅首次出现")
_BOOL_VALUES = {"true", "false", "1", "0", "yes", "no"}
_TERM_KEYS = {"pattern", "preferred", "context", "severity"}
# 无 check_type、无 pattern 但由 Auditor 内置参数驱动的规则（合法形态）
_NATIVE_RULE_IDS = {"FMT-001", "FMT-002", "FMT-004", "CON-002"}


@dataclass
class ValidationResult:
    """校验结果。errors 非空即视为配置不可用 (CLI exit 1)。"""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def merge(self, other: "ValidationResult") -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def to_lines(self) -> list[str]:
        lines = [f"  [ERROR] {e}" for e in self.errors]
        lines.extend(f"  [WARN]  {w}" for w in self.warnings)
        return lines


def _read_text_with_fallback(path: Path) -> str:
    """utf-8 → gbk → replace（与 rules/vocabulary/glossary 加载器一致）。"""
    for encoding in ("utf-8", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def validate_rules(rules_path: str | Path = "rules.md") -> ValidationResult:
    """校验 rules.md：ID/严重度/check_type/正则/数值范围/重复项。"""
    result = ValidationResult()
    path = Path(rules_path)
    if not path.exists():
        result.errors.append(f"规则文件不存在: {path}")
        return result

    try:
        rules = parse_rules_md(path)
    except Exception as e:  # noqa: BLE001 — 校验器必须报告而非崩溃
        result.errors.append(f"规则文件解析失败: {path} — {e}")
        return result

    if not rules:
        result.errors.append(f"未解析到任何规则（检查 '## 规则ID: 说明' 标题格式）: {path}")
        return result

    seen_ids: dict[str, int] = {}
    for rule in rules:
        rid = rule.rule_id
        seen_ids[rid] = seen_ids.get(rid, 0) + 1
        if not _RULE_ID_RE.match(rid):
            result.errors.append(f"规则 ID 格式非法: '{rid}'（应为 STR-001 / CON-003-A 形式）")
        if rule.severity not in _VALID_SEVERITIES:
            result.errors.append(
                f"{rid}: 严重度 '{rule.severity}' 非法（仅支持 error/warning/info）"
            )

        check_type = rule.check_type
        if check_type and check_type != "regex" and check_type not in CHECK_REGISTRY:
            result.errors.append(
                f"{rid}: 未知 check_type '{check_type}'（不在 CHECK_REGISTRY，规则将静默跳过）"
            )

        if check_type == "regex":
            pattern = rule.params.get("pattern")
            if not pattern:
                result.errors.append(f"{rid}: regex 规则缺少 '模式:' (pattern)")
            else:
                try:
                    re.compile(str(pattern))
                except re.error as e:
                    result.errors.append(f"{rid}: 正则无法编译 — {e}")
        elif not check_type and rid not in _NATIVE_RULE_IDS:
            result.warnings.append(
                f"{rid}: 既无 '检查:' 也无 '模式:'，且不是已知内置参数规则 → 可能永不执行"
            )

        _validate_params(rule, result)
        _validate_bool_params(rule, result)

    for rid, count in seen_ids.items():
        if count > 1:
            result.errors.append(f"规则 ID 重复 {count} 次: {rid}（后者会覆盖前者行为）")

    return result


def _validate_params(rule, result: ValidationResult) -> None:
    """针对性数值/列表参数校验（不追求穷举，覆盖已知易错项）。"""
    rid = rule.rule_id
    params = rule.params

    for key, label in (("title_range", "标题字号"), ("body_range", "正文字号")):
        if key in params and params[key] is None:
            result.errors.append(f"{rid}: {label}范围无法解析（应为 min: X, max: Y）")

    title_range = params.get("title_range")
    if isinstance(title_range, tuple) and title_range[0] > title_range[1]:
        result.errors.append(f"{rid}: 标题字号范围 min > max {title_range}")

    body_range = params.get("body_range")
    if isinstance(body_range, tuple) and body_range[0] > body_range[1]:
        result.errors.append(f"{rid}: 正文字号范围 min > max {body_range}")

    if rid.startswith("FMT-001"):
        fonts = params.get("allowed_fonts")
        if not fonts:
            result.errors.append(f"{rid}: 允许字体列表为空（FMT-001 将无字体可通过）")

    if rid.startswith("FMT-003"):
        max_chars = params.get("max_chars")
        if max_chars is not None:
            try:
                if int(max_chars) <= 0:
                    result.errors.append(f"{rid}: 最大字数必须为正整数，实际 {max_chars}")
            except (TypeError, ValueError):
                result.errors.append(f"{rid}: 最大字数不是整数: {max_chars}")

    if rid.startswith("FMT-008"):
        for key in ("最小对比度", "大字最小对比度"):
            if key in params:
                try:
                    value = float(params[key])
                except (TypeError, ValueError):
                    result.errors.append(f"{rid}: {key} 不是数字: {params[key]}")
                    continue
                if not 1.0 <= value <= 21.0:
                    result.errors.append(f"{rid}: {key} 超出 WCAG 范围 [1, 21]: {value}")
        if "大字字号阈值" in params:
            try:
                if float(params["大字字号阈值"]) <= 0:
                    result.errors.append(f"{rid}: 大字字号阈值必须为正数")
            except (TypeError, ValueError):
                result.errors.append(f"{rid}: 大字字号阈值不是数字: {params['大字字号阈值']}")

    if rid.startswith("CON-002"):
        sections = params.get("required_sections")
        if not sections:
            result.errors.append(f"{rid}: 必含章节列表为空（CON-002 将永远通过）")

    if rid.startswith("CON-004") and "关键词" in params and not params["关键词"]:
        result.errors.append(f"{rid}: 结论关键词列表为空（CON-004 将永不触发）")


def _validate_bool_params(rule, result: ValidationResult) -> None:
    """布尔类参数只接受 true/false/1/0/yes/no（运行时不认识的写法会被静默当 false）。"""
    for key in _BOOL_KEYS:
        if key not in rule.params:
            continue
        value = str(rule.params[key]).strip().lower()
        if value not in _BOOL_VALUES:
            result.warnings.append(
                f"{rule.rule_id}: '{key}: {rule.params[key]}' 不是布尔值 "
                f"({'/'.join(sorted(_BOOL_VALUES))})，运行时将按 false 处理"
            )


def validate_glossary(glossary_dir: str | Path = "glossary") -> ValidationResult:
    """校验 glossary/*.yaml：YAML 结构、term 必填字段、正则、未知键。"""
    result = ValidationResult()
    directory = Path(glossary_dir)
    if not directory.exists():
        result.errors.append(f"术语表目录不存在: {directory}")
        return result

    yaml_files = sorted(directory.glob("*.yaml"))
    if not yaml_files:
        result.warnings.append(f"术语表目录为空（无 *.yaml）: {directory}")
        return result

    known_patterns: dict[str, str] = {}
    for yaml_file in yaml_files:
        name = yaml_file.name
        try:
            data = yaml.safe_load(_read_text_with_fallback(yaml_file))
        except yaml.YAMLError as e:
            result.errors.append(f"{name}: YAML 语法错误 — {e}")
            continue
        if not isinstance(data, dict):
            result.errors.append(f"{name}: 顶层应为映射（含 category/version/terms）")
            continue
        if "terms" not in data:
            result.errors.append(f"{name}: 缺少 terms 列表")
            continue
        if "category" not in data:
            result.warnings.append(f"{name}: 缺少 category（运行时显示为 '未分类'）")
        terms = data.get("terms")
        if not isinstance(terms, list):
            result.errors.append(f"{name}: terms 必须是列表")
            continue
        for idx, item in enumerate(terms, 1):
            prefix = f"{name} terms[{idx}]"
            if not isinstance(item, dict):
                result.errors.append(f"{prefix}: 条目应为映射")
                continue
            pattern = item.get("pattern")
            if not pattern:
                result.errors.append(f"{prefix}: 缺少 pattern")
            else:
                try:
                    re.compile(str(pattern))
                except re.error as e:
                    result.errors.append(f"{prefix}: 正则无法编译 — {e}")
                if str(pattern) in known_patterns:
                    result.warnings.append(
                        f"{prefix}: pattern 与 {known_patterns[str(pattern)]} 重复"
                    )
                else:
                    known_patterns[str(pattern)] = name
            if "preferred" not in item:
                result.warnings.append(f"{prefix}: 缺少 preferred（建议列会为空）")
            severity = item.get("severity")
            if severity is not None and str(severity).lower() not in _VALID_SEVERITIES:
                result.errors.append(f"{prefix}: 严重度 '{severity}' 非法")
            unknown = set(item) - _TERM_KEYS
            if unknown:
                result.warnings.append(f"{prefix}: 未知字段 {sorted(unknown)}（运行时忽略）")

    return result


def validate_vocab(vocab_dir: str | Path = "vocab") -> ValidationResult:
    """校验 vocab/accept.txt 与 reject.txt：编码、重复项、reject 正则。"""
    result = ValidationResult()
    directory = Path(vocab_dir)
    if not directory.exists():
        result.errors.append(f"词汇表目录不存在: {directory}")
        return result

    accept = directory / "accept.txt"
    reject = directory / "reject.txt"
    if not accept.exists() and not reject.exists():
        result.warnings.append(f"词汇表目录为空（无 accept.txt / reject.txt）: {directory}")
        return result

    if accept.exists():
        seen: set[str] = set()
        for lineno, line in enumerate(_read_text_with_fallback(accept).splitlines(), 1):
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            key = entry.lower()
            if key in seen:
                result.warnings.append(f"accept.txt:{lineno}: 重复条目 '{entry}'")
            seen.add(key)

    if reject.exists():
        for lineno, line in enumerate(_read_text_with_fallback(reject).splitlines(), 1):
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            word = re.match(r"^(.+?)\s*#\s*(.+)$", entry)
            pattern_text = word.group(1).strip() if word else entry
            try:
                re.compile(pattern_text, re.IGNORECASE)
            except re.error as e:
                result.errors.append(f"reject.txt:{lineno}: 正则无法编译 '{pattern_text}' — {e}")

    return result


def validate_configuration(
    rules_path: str | Path = "rules.md",
    glossary_dir: str | Path | None = "glossary",
    vocab_dir: str | Path | None = "vocab",
) -> ValidationResult:
    """聚合校验 rules.md + glossary + vocab（None 表示跳过对应部分）。"""
    result = validate_rules(rules_path)
    if glossary_dir is not None:
        result.merge(validate_glossary(glossary_dir))
    if vocab_dir is not None:
        result.merge(validate_vocab(vocab_dir))
    return result
