"""rules.md 解析器 — 将 Markdown 规则文件转换为可执行规则"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class AuditRule:
    """单条审查规则"""

    rule_id: str
    category: str  # "structure" | "format" | "terminology" | "content"
    severity: str  # "error" | "warning" | "info"
    description: str
    check_type: str  # 检查类型标识
    params: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""  # 原始 Markdown 文本 (调试用)

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "check_type": self.check_type,
            "params": self.params,
        }


# ── 全局参数（rules.md frontmatter `parameters:`）────────────────────────
# 这些阈值原先硬编码在各 Auditor 里（2026-11 审查列为"假阳性只能改代码"）。
# 现统一从 rules.md 声明, 未声明时用这里的默认值（与历史硬编码值一致）。
# GLOBAL_PARAM_SPECS: name → (type, default, min, max, 中文名)
GLOBAL_PARAM_SPECS: dict[str, tuple[type, Any, float | None, float | None, str]] = {
    "alignment_tolerance": (float, 5.0, 0.0, 100.0, "对齐容差 (pt)"),
    "max_font_types": (int, 3, 1, 50, "全局字体种类上限"),
    "near_duplicate_similarity": (float, 0.90, 0.50, 1.0, "近似重复页相似度阈值"),
    "near_duplicate_min_chars": (int, 40, 10, 10000, "近似重复页最小字符数"),
    "conclusion_min_paragraphs": (int, 3, 1, 100, "CON-004 判断 2 的内容段落门槛"),
    "table_fit_height_ratio": (float, 1.15, 1.0, 5.0, "表格行高不足判定倍率"),
    "table_fit_min_excess_pt": (float, 6.0, 0.0, 100.0, "表格行高不足最小超出 (pt)"),
    "table_fit_col_ratio": (float, 1.05, 1.0, 5.0, "表格列宽不足判定倍率"),
    "table_fit_col_min_excess_pt": (float, 2.0, 0.0, 100.0, "表格列宽不足最小超出 (pt)"),
    "table_margin_pt_pptx": (float, 7.2, 0.0, 50.0, "PPTX 单元格默认内边距 (pt)"),
    "table_margin_pt_docx": (float, 5.4, 0.0, 50.0, "DOCX 单元格默认内边距 (pt)"),
    "text_overflow_height_ratio": (float, 1.15, 1.0, 5.0, "文本溢出判定倍率"),
    "text_overflow_min_excess_pt": (float, 8.0, 0.0, 100.0, "文本溢出最小超出 (pt)"),
    "image_min_dpi": (float, 150.0, 1.0, 10000.0, "图片最低 DPI"),
    "numeric_length_units": (
        list,
        ["nm", "μm", "um", "mm", "cm", "m"],
        None,
        None,
        "CON-001 视为工艺节点的长度单位",
    ),
    "common_uppercase_extra": (list, [], None, None, "缩写扫描额外豁免词 (大写)"),
}


def global_param_defaults() -> dict[str, Any]:
    """全局参数默认值（深拷贝列表，避免调用方修改默认值）。"""
    defaults: dict[str, Any] = {}
    for name, (_typ, default, _lo, _hi, _label) in GLOBAL_PARAM_SPECS.items():
        defaults[name] = list(default) if isinstance(default, list) else default
    return defaults


def _read_rules_text(file_path: str | Path) -> str:
    """读取 rules.md（UTF-8 → GBK 回退，去 BOM，永不抛解码异常）。

    2026-11 max 审查 S7：Windows 记事本保存的 UTF-8 BOM 会让 ``startswith("---")``
    失效 → frontmatter ``parameters:`` 被静默忽略（全局阈值全部回退默认值）。
    """
    path = Path(file_path)
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        logger.warning("rules.md 非 UTF-8 编码，尝试 GBK 回退读取: %s", file_path)
        content = path.read_text(encoding="gbk", errors="replace")
    return content.lstrip("\ufeff")


def parse_rules_globals(file_path: str | Path) -> dict[str, Any]:
    """解析 rules.md frontmatter 的 ``parameters:`` 全局参数（原样返回，不做类型转换）。

    非法类型/范围的报错由 ``validation.validate_rules`` 负责；运行时由
    ``extract_auditor_config`` 做带告警的强制转换（不能因一处笔误阻断审查）。
    """
    path = Path(file_path)
    if not path.exists():
        return {}
    content = _read_rules_text(path)
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    raw = data.get("parameters")
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items()}


def _coerce_global(name: str, raw: Any, current: Any) -> Any:
    """把 rules.md 的全局参数值转换成期望类型；非法值告警并保留当前值。"""
    typ, _default, lo, hi, label = GLOBAL_PARAM_SPECS[name]
    banner = f"全局参数 {label}（{name}）"
    if typ is list:
        if isinstance(raw, str):
            values = [v.strip() for v in raw.split(",") if v.strip()]
        elif isinstance(raw, (list, tuple)):
            values = [str(v).strip() for v in raw if str(v).strip()]
        else:
            logger.warning("%s 值无效: %r，使用默认值 %r", banner, raw, current)
            return current
        return values
    try:
        value = typ(raw)
    except (TypeError, ValueError):
        logger.warning("%s 值无效: %r，使用默认值 %r", banner, raw, current)
        return current
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        logger.warning("%s 超出范围 [%s, %s]: %r，使用默认值 %r", banner, lo, hi, raw, current)
        return current
    return value


def _parse_frontmatter_body(content: str) -> tuple[dict | None, str]:
    """拆 frontmatter 与正文；返回 (frontmatter mapping 或 None, 正文)。"""
    if not content.startswith("---"):
        return None, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, content
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None, parts[2]
    return (data if isinstance(data, dict) else None), parts[2]


def parse_rules_md(file_path: str | Path) -> list[AuditRule]:
    """解析 rules.md 文件，返回规则列表"""
    path = Path(file_path)
    if not path.exists():
        logger.warning("规则文件不存在: %s", file_path)
        return []

    # 编码回退 (2026-09-06 审查 B-1): 用户误存 GBK 的 rules.md 不应使整个规则
    # 配置失效 (UnicodeDecodeError 直接抛出) — 与 vocabulary 的回退链对齐;
    # gbk+replace 兜底永不失败, 非 GBK 字节以 U+FFFD 可见呈现。
    content = _read_rules_text(path)

    # 解析 YAML frontmatter (跳过；parameters 由 parse_rules_globals 读取)
    _frontmatter, body = _parse_frontmatter_body(content)

    rules: list[AuditRule] = []
    current_section = ""

    lines = body.split("\n")

    for line in lines:
        line = line.rstrip()

        # 跳过空行
        if not line.strip():
            continue

        # 一级标题 → 大类 (结构规则 / 格式规则 / 术语规则 / 内容规则)
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            section = m.group(1).strip()
            if "结构" in section:
                current_section = "structure"
            elif "格式" in section:
                current_section = "format"
            elif "术语" in section:
                current_section = "terminology"
            elif "内容" in section:
                current_section = "content"
            else:
                current_section = section
            continue

        # 二级标题 → 具体规则 ID
        m = re.match(r"^##\s+([\w-]+):\s*(.+)$", line)
        if m:
            rule_id = m.group(1).strip()
            rule_desc = m.group(2).strip()

            # 创建规则对象
            rules.append(
                AuditRule(
                    rule_id=rule_id,
                    category=current_section,
                    severity="warning",  # 默认值，后续解析覆盖
                    description=rule_desc,
                    check_type="",
                    raw_text="",
                )
            )
            continue

        # 三级标题 → 子规则 (如 TERM-001: xxx)
        m = re.match(r"^###\s+([\w-]+):\s*(.+)$", line)
        if m:
            rule_id = m.group(1).strip()
            rule_desc = m.group(2).strip()

            rules.append(
                AuditRule(
                    rule_id=rule_id,
                    category=current_section,
                    severity="warning",
                    description=rule_desc,
                    check_type="",
                    raw_text="",
                )
            )
            continue

        # 属性行 (- key: value)
        if rules and line.strip().startswith("-"):
            attr_line = line.strip().lstrip("-").strip()
            if ":" in attr_line:
                key, _, value = attr_line.partition(":")
                key = key.strip()
                value = value.strip()

                rule = rules[-1]

                if key == "严重度" or key == "severity":
                    rule.severity = value.lower()
                elif key == "检查" or key == "check":
                    rule.check_type = value
                elif key == "说明" or key == "description":
                    rule.description = value
                elif key == "建议" or key == "suggestion":
                    rule.params["suggestion"] = value
                elif key == "字体" or key == "fonts":
                    # 解析列表 [A, B, C]
                    vals = _parse_list(value)
                    rule.params["allowed_fonts"] = vals
                elif key == "模式" or key == "pattern":
                    # strip surrounding quotes
                    value = value.strip()
                    if (value.startswith('"') and value.endswith('"')) or (
                        value.startswith("'") and value.endswith("'")
                    ):
                        value = value[1:-1]
                    rule.params["pattern"] = value
                elif key == "章节" or key == "sections":
                    vals = _parse_list(value)
                    rule.params["required_sections"] = vals
                elif key == "标题":
                    rule.params["title_range"] = _parse_range(value)
                elif key == "正文":
                    rule.params["body_range"] = _parse_range(value)
                elif key == "最大字数":
                    try:
                        rule.params["max_chars"] = int(value)
                    except (ValueError, TypeError):
                        # 保留原始值（2026-10-29 审查）：旧实现静默改成 200，
                        # 导致 extract 无法告警、validation 复查时已看不到非法原值。
                        rule.params["max_chars"] = value
                elif key == "关键词" or key == "keywords":
                    vals = _parse_list(value)
                    rule.params["关键词"] = vals
                elif key == "豁免版式" or key == "exempt_layouts":
                    vals = _parse_list(value)
                    rule.params["exempt_layouts"] = vals
                elif key == "量词关键词" or key == "unit_keywords":
                    rule.params["量词关键词"] = _parse_list(value)
                elif key in ("最小数字个数", "evidence_min_numbers"):
                    rule.params[key] = _safe_int(value)
                elif key in ("最小内容段落", "section_min_paragraphs"):
                    rule.params[key] = _safe_int(value)
                elif key in ("最小字数", "section_min_chars"):
                    rule.params[key] = _safe_int(value)
                else:
                    rule.params[key] = value

    logger.info("从 rules.md 解析到 %d 条规则", len(rules))
    return rules


def _safe_int(value: Any) -> int | str:
    """解析整数；失败时保留原始值（供 validation 报告非法原值）。"""
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return str(value)


def _parse_list(value: str) -> list[str]:
    """解析 [A, B, C] 格式的列表值"""
    value = value.strip().strip("[]")
    if not value:
        return []
    return [v.strip().strip("\"'") for v in value.split(",")]


def _parse_range(value: str) -> tuple[int, int] | None:
    """解析 {min: X, max: Y} 格式的范围值。

    Returns:
        (min, max) 元组，解析失败返回 None（调用方应使用默认值）。
    """
    # 尝试 JSON 风格
    match = re.search(r"min\s*:\s*(\d+).*?max\s*:\s*(\d+)", value)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    # 尝试简单范围 (X-Y)
    match = re.match(r"(\d+)\s*[-–—]\s*(\d+)", value)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    logger.warning("无法解析范围值: %s，将使用默认值", value)
    return None


def extract_auditor_config(
    rules: list[AuditRule], globals_: dict[str, Any] | None = None
) -> dict[str, Any]:
    """从 rules.md 解析结果中提取各 Auditor 的配置参数。

    Args:
        rules: ``parse_rules_md`` 结果。
        globals_: ``parse_rules_globals`` 结果（rules.md frontmatter 的
            ``parameters:``）；未声明或非法值回退 ``GLOBAL_PARAM_SPECS`` 默认值
            并记 warning（运行时降级；校验时由 ``validate_rules`` 显式报错）。

    Returns:
        dict with keys: allowed_fonts, title_size_range, body_size_range,
                        required_sections, max_chars_per_page,
                        以及全局参数（alignment_tolerance / max_font_types /
                        near_duplicate_* / conclusion_min_paragraphs /
                        table_fit_* / table_margin_* / text_overflow_* /
                        image_min_dpi / numeric_length_units /
                        common_uppercase_extra）
    """
    config: dict[str, Any] = global_param_defaults()
    config.update(
        {
            "allowed_fonts": ["微软雅黑", "Arial", "Calibri", "Noto Sans SC"],
            "title_size_range": (28, 44),
            "body_size_range": (12, 32),
            "required_sections": [],
            "max_chinese_chars": 150,
            "max_english_chars": 300,
            "max_explicit_newlines": 3,
            "max_chars_per_page": 200,
            "conclusion_keywords": [
                "结论",
                "小结",
                "总结",
                "要点",
                "关键",
                "建议",
                "展望",
                "Summary",
                "Conclusion",
                "Key",
                "Takeaway",
                "Recommend",
            ],
            "max_english_words": 10,  # STR-004
            "max_chinese_chars_title": 40,  # STR-004
            "min_title_font_size": 28,  # STR-001 标题页大号标题文本判定阈值
            "min_contrast": 4.5,  # FMT-008 表格对比度阈值 (WCAG AA 正文)
            "large_text_min_contrast": 3.0,  # FMT-008 大字对比度阈值 (WCAG AA 大字)
            "large_text_threshold": 18,  # FMT-008 大字字号阈值 (pt)
        }
    )

    # rules.md frontmatter `parameters:` 覆盖全局阈值（非法值告警并保留默认）
    for _name, _raw in (globals_ or {}).items():
        if _name in GLOBAL_PARAM_SPECS:
            config[_name] = _coerce_global(_name, _raw, config[_name])
        else:
            logger.warning("rules.md parameters 含未知参数键: %s（已忽略）", _name)

    for rule in rules:
        rid = rule.rule_id

        if rid.startswith("FMT-001") and "allowed_fonts" in rule.params:
            config["allowed_fonts"] = rule.params["allowed_fonts"]

        elif rid.startswith("FMT-002"):
            if "title_range" in rule.params and rule.params["title_range"] is not None:
                config["title_size_range"] = rule.params["title_range"]
            if "body_range" in rule.params and rule.params["body_range"] is not None:
                config["body_size_range"] = rule.params["body_range"]

        elif rid.startswith("FMT-003"):
            if "max_chars" in rule.params:
                try:
                    config["max_chars_per_page"] = int(rule.params["max_chars"])
                except (ValueError, TypeError):
                    logger.warning(
                        "FMT-003 最大字数 值无效: %s，使用默认值 %d",
                        rule.params["max_chars"],
                        config["max_chars_per_page"],
                    )

        elif rid.startswith("FMT-004"):
            if "max_chinese" in rule.params or "中文上限" in rule.params:
                try:
                    config["max_chinese_chars"] = int(
                        rule.params.get("中文上限", rule.params.get("max_chinese", 150))
                    )
                except (ValueError, TypeError):
                    logger.warning(
                        "FMT-004 中文上限 值无效: %s，使用默认值 %d",
                        rule.params.get("中文上限", rule.params.get("max_chinese")),
                        config["max_chinese_chars"],
                    )
            if "max_english" in rule.params or "英文上限" in rule.params:
                try:
                    config["max_english_chars"] = int(
                        rule.params.get("英文上限", rule.params.get("max_english", 300))
                    )
                except (ValueError, TypeError):
                    logger.warning(
                        "FMT-004 英文上限 值无效: %s，使用默认值 %d",
                        rule.params.get("英文上限", rule.params.get("max_english")),
                        config["max_english_chars"],
                    )
            if "max_newlines" in rule.params or "最大显式换行" in rule.params:
                try:
                    config["max_explicit_newlines"] = int(
                        rule.params.get("最大显式换行", rule.params.get("max_newlines", 3))
                    )
                except (ValueError, TypeError):
                    logger.warning(
                        "FMT-004 最大显式换行 值无效: %s，使用默认值 %d",
                        rule.params.get("最大显式换行", rule.params.get("max_newlines")),
                        config["max_explicit_newlines"],
                    )

        elif rid.startswith("FMT-008"):
            if "最小对比度" in rule.params:
                try:
                    config["min_contrast"] = float(rule.params["最小对比度"])
                except (ValueError, TypeError):
                    logger.warning(
                        "FMT-008 最小对比度 值无效: %s，使用默认值 %s",
                        rule.params["最小对比度"],
                        config["min_contrast"],
                    )
            if "大字最小对比度" in rule.params:
                try:
                    config["large_text_min_contrast"] = float(rule.params["大字最小对比度"])
                except (ValueError, TypeError):
                    logger.warning(
                        "FMT-008 大字最小对比度 值无效: %s，使用默认值 %s",
                        rule.params["大字最小对比度"],
                        config["large_text_min_contrast"],
                    )
            if "大字字号阈值" in rule.params:
                try:
                    config["large_text_threshold"] = float(rule.params["大字字号阈值"])
                except (ValueError, TypeError):
                    logger.warning(
                        "FMT-008 大字字号阈值 值无效: %s，使用默认值 %s",
                        rule.params["大字字号阈值"],
                        config["large_text_threshold"],
                    )

        elif rid.startswith("STR-001"):
            if "最小标题字号" in rule.params:
                try:
                    config["min_title_font_size"] = int(rule.params["最小标题字号"])
                except (ValueError, TypeError):
                    logger.warning(
                        "STR-001 最小标题字号 值无效: %s，使用默认值 %s",
                        rule.params["最小标题字号"],
                        config["min_title_font_size"],
                    )

        elif rid.startswith("STR-004"):
            if "最大英文词数" in rule.params:
                try:
                    config["max_english_words"] = int(rule.params["最大英文词数"])
                except (ValueError, TypeError):
                    logger.warning(
                        "STR-004 最大英文词数 值无效: %s，使用默认值 %d",
                        rule.params["最大英文词数"],
                        config["max_english_words"],
                    )
            if "最大中文字数" in rule.params:
                try:
                    config["max_chinese_chars_title"] = int(rule.params["最大中文字数"])
                except (ValueError, TypeError):
                    logger.warning(
                        "STR-004 最大中文字数 值无效: %s，使用默认值 %d",
                        rule.params["最大中文字数"],
                        config["max_chinese_chars_title"],
                    )

        elif rid.startswith("CON-002"):
            if "required_sections" in rule.params:
                config["required_sections"] = rule.params["required_sections"]
            # P1-3: 严重度配置驱动 — 原先 _check_required_sections 硬编码 ERROR，
            # 用户改 rules.md 的 CON-002 严重度不生效；现由声明驱动。
            config["required_sections_severity"] = rule.severity

        elif rid.startswith("CON-004"):
            if "关键词" in rule.params:
                config["conclusion_keywords"] = rule.params["关键词"]
            if "exempt_layouts" in rule.params:
                config["exempt_layouts"] = rule.params["exempt_layouts"]

        # 内容级检查参数 (2026-11): CON-005 结论量化 / CON-006 章节实体 / CON-007 单位
        elif rid.startswith("CON-005"):
            if "关键词" in rule.params:
                config["conclusion_keywords"] = rule.params["关键词"]
            if "最小数字个数" in rule.params:
                config["evidence_min_numbers"] = rule.params["最小数字个数"]
        elif rid.startswith("CON-006"):
            if "最小内容段落" in rule.params:
                config["section_min_paragraphs"] = rule.params["最小内容段落"]
            if "最小字数" in rule.params:
                config["section_min_chars"] = rule.params["最小字数"]
        elif rid.startswith("CON-007"):
            if "量词关键词" in rule.params:
                config["unit_keywords"] = rule.params["量词关键词"]

    # languagetool_url 接线 (2026-08 审查 L6): 任一规则 params 含该键即注入 config,
    # 由 pipeline.build_auditors 传给 LanguageAuditor (本地服务地址, 白名单在
    # LanguageToolClient._validate_base_url 拦截外部地址)。
    for rule in rules:
        if "languagetool_url" in rule.params:
            config["languagetool_url"] = str(rule.params["languagetool_url"])
            break

    # 无 check_type 的 format 规则严重度通道 (2026-09-06 审查 C-1):
    # FMT-001/002/004 无 `检查:` 键, 不进 _DISPATCH, 其 findings 严重度原先
    # 硬编码在 FormatAuditor 内部 — rules.md 的严重度声明静默失效。
    # 现收集到 rule_severities, 由 FormatAuditor.audit() 按 rule_id 统一覆盖
    # (与 custom_rules._execute_check_rule 的 dispatch 覆盖同哲学: rules.md
    # 是严重度的唯一来源)。独立循环收集, 避免与上方 elif 参数分支互斥。
    rule_severities: dict[str, str] = {
        rule.rule_id: rule.severity
        for rule in rules
        if rule.rule_id.startswith("FMT-") and not rule.check_type
    }
    if rule_severities:
        config["rule_severities"] = rule_severities

    return config
