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
    category: str                      # "structure" | "format" | "terminology" | "content"
    severity: str                      # "error" | "warning" | "info"
    description: str
    check_type: str                    # 检查类型标识
    params: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""                 # 原始 Markdown 文本 (调试用)

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "check_type": self.check_type,
            "params": self.params,
        }


def parse_rules_md(file_path: str | Path) -> list[AuditRule]:
    """解析 rules.md 文件，返回规则列表"""
    path = Path(file_path)
    if not path.exists():
        logger.warning("规则文件不存在: %s", file_path)
        return []

    content = path.read_text(encoding="utf-8")

    # 解析 YAML frontmatter (可选，当前仅用于跳过)
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                yaml.safe_load(parts[1])  # validate but discard
            except yaml.YAMLError:
                pass
            body = parts[2]

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
            rules.append(AuditRule(
                rule_id=rule_id,
                category=current_section,
                severity="warning",  # 默认值，后续解析覆盖
                description=rule_desc,
                check_type="",
                raw_text="",
            ))
            continue

        # 三级标题 → 子规则 (如 TERM-001: xxx)
        m = re.match(r"^###\s+([\w-]+):\s*(.+)$", line)
        if m:
            rule_id = m.group(1).strip()
            rule_desc = m.group(2).strip()

            rules.append(AuditRule(
                rule_id=rule_id,
                category=current_section,
                severity="warning",
                description=rule_desc,
                check_type="",
                raw_text="",
            ))
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
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
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
                        rule.params["max_chars"] = 200
                elif key == "关键词" or key == "keywords":
                    vals = _parse_list(value)
                    rule.params["关键词"] = vals
                elif key == "豁免版式" or key == "exempt_layouts":
                    vals = _parse_list(value)
                    rule.params["exempt_layouts"] = vals
                else:
                    rule.params[key] = value

    logger.info("从 rules.md 解析到 %d 条规则", len(rules))
    return rules


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


def extract_auditor_config(rules: list[AuditRule]) -> dict[str, Any]:
    """从 rules.md 解析结果中提取各 Auditor 的配置参数。

    Returns:
        dict with keys: allowed_fonts, title_size_range, body_size_range,
                        required_sections, max_chars_per_page
    """
    config: dict[str, Any] = {
        "allowed_fonts": ["微软雅黑", "Arial", "Calibri", "Noto Sans SC"],
        "title_size_range": (28, 40),
        "body_size_range": (12, 22),
        "required_sections": [],
        "max_chinese_chars": 150,
        "max_english_chars": 300,
        "max_explicit_newlines": 3,
        "max_chars_per_page": 200,
        "conclusion_keywords": [
            "结论", "小结", "总结", "要点", "关键", "建议", "展望",
            "Summary", "Conclusion", "Key", "Takeaway", "Recommend",
        ],
        "max_english_words": 10,        # STR-004
        "max_chinese_chars_title": 40,  # STR-004
        "min_contrast": 4.5,            # FMT-008 表格对比度阈值 (WCAG AA 正文)
        "large_text_min_contrast": 3.0, # FMT-008 大字对比度阈值 (WCAG AA 大字)
        "large_text_threshold": 18,     # FMT-008 大字字号阈值 (pt)
    }

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
                    logger.warning("FMT-003 最大字数 值无效: %s，使用默认值 %d",
                                   rule.params["max_chars"], config["max_chars_per_page"])

        elif rid.startswith("FMT-004"):
            if "max_chinese" in rule.params or "中文上限" in rule.params:
                try:
                    config["max_chinese_chars"] = int(rule.params.get("中文上限", rule.params.get("max_chinese", 150)))
                except (ValueError, TypeError):
                    logger.warning("FMT-004 中文上限 值无效: %s，使用默认值 %d",
                                   rule.params.get("中文上限", rule.params.get("max_chinese")), config["max_chinese_chars"])
            if "max_english" in rule.params or "英文上限" in rule.params:
                try:
                    config["max_english_chars"] = int(rule.params.get("英文上限", rule.params.get("max_english", 300)))
                except (ValueError, TypeError):
                    logger.warning("FMT-004 英文上限 值无效: %s，使用默认值 %d",
                                   rule.params.get("英文上限", rule.params.get("max_english")), config["max_english_chars"])
            if "max_newlines" in rule.params or "最大显式换行" in rule.params:
                try:
                    config["max_explicit_newlines"] = int(rule.params.get("最大显式换行", rule.params.get("max_newlines", 3)))
                except (ValueError, TypeError):
                    logger.warning("FMT-004 最大显式换行 值无效: %s，使用默认值 %d",
                                   rule.params.get("最大显式换行", rule.params.get("max_newlines")), config["max_explicit_newlines"])

        elif rid.startswith("FMT-008"):
            if "最小对比度" in rule.params:
                try:
                    config["min_contrast"] = float(rule.params["最小对比度"])
                except (ValueError, TypeError):
                    logger.warning("FMT-008 最小对比度 值无效: %s，使用默认值 %s",
                                   rule.params["最小对比度"], config["min_contrast"])
            if "大字最小对比度" in rule.params:
                try:
                    config["large_text_min_contrast"] = float(rule.params["大字最小对比度"])
                except (ValueError, TypeError):
                    logger.warning("FMT-008 大字最小对比度 值无效: %s，使用默认值 %s",
                                   rule.params["大字最小对比度"], config["large_text_min_contrast"])
            if "大字字号阈值" in rule.params:
                try:
                    config["large_text_threshold"] = float(rule.params["大字字号阈值"])
                except (ValueError, TypeError):
                    logger.warning("FMT-008 大字字号阈值 值无效: %s，使用默认值 %s",
                                   rule.params["大字字号阈值"], config["large_text_threshold"])

        elif rid.startswith("STR-004"):
            if "最大英文词数" in rule.params:
                try:
                    config["max_english_words"] = int(rule.params["最大英文词数"])
                except (ValueError, TypeError):
                    logger.warning("STR-004 最大英文词数 值无效: %s，使用默认值 %d",
                                   rule.params["最大英文词数"], config["max_english_words"])
            if "最大中文字数" in rule.params:
                try:
                    config["max_chinese_chars_title"] = int(rule.params["最大中文字数"])
                except (ValueError, TypeError):
                    logger.warning("STR-004 最大中文字数 值无效: %s，使用默认值 %d",
                                   rule.params["最大中文字数"], config["max_chinese_chars_title"])

        elif rid.startswith("CON-002") and "required_sections" in rule.params:
            config["required_sections"] = rule.params["required_sections"]

        elif rid.startswith("CON-004"):
            if "关键词" in rule.params:
                config["conclusion_keywords"] = rule.params["关键词"]
            if "exempt_layouts" in rule.params:
                config["exempt_layouts"] = rule.params["exempt_layouts"]

    return config
