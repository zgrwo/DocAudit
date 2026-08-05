"""CI 验证脚本：html.escape 合规性检查。

检查 src/reporters/html_reporter.py 中所有用户可控文本是否经过 html.escape() 处理。
退出码 0 = 通过，1 = 存在未转义字段。
"""

import re
import sys
from pathlib import Path

REPORTER = Path("src/reporters/html_reporter.py")

# 必须被 escape() 包裹的用户文本字段
REQUIRED_ESCAPE_FIELDS = [
    "message",
    "context",
    "suggestion",
    "location",
    "source_path",
    "title",
    "rule_id",
]


def check_escape_import(content: str) -> list[str]:
    """确认 html.escape 已导入。"""
    errors = []
    if "from html import escape" not in content and "import html" not in content:
        errors.append("html_reporter.py 缺少 html.escape 导入")
    return errors


def check_field_escaping(content: str) -> list[str]:
    """检查模板字符串中用户字段是否被 escape() 包裹。"""
    errors = []
    # 查找所有 {f.xxx} 或 {xxx} 模板表达式
    template_exprs = re.findall(r"\{([^}]+)\}", content)

    for field in REQUIRED_ESCAPE_FIELDS:
        # 查找引用该字段的模板表达式
        field_refs = [expr for expr in template_exprs if f".{field}" in expr or f"f.{field}" in expr]
        for ref in field_refs:
            # 检查是否被 escape() 包裹
            if "escape(" not in ref and "escape (" not in ref:
                errors.append(f"字段 '{field}' 未转义: {{{ref}}}")

    return errors


def main() -> int:
    if not REPORTER.exists():
        print(f"ERROR: {REPORTER} 不存在")
        return 1

    content = REPORTER.read_text(encoding="utf-8")
    errors = []
    errors.extend(check_escape_import(content))
    errors.extend(check_field_escaping(content))

    if errors:
        print("html.escape 合规性检查失败:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("html.escape compliance check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
