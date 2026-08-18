"""CI 验证脚本：html.escape 合规性检查。

检查 src/reporters/html_reporter.py 中所有用户可控文本是否经过 html.escape() 处理。
支持两种合规写法:
1. 内联转义: 模板中直接 `{escape(f.message)}`
2. 变量中转义: 先 `safe_message = escape(f.message)` 赋值，再在模板中引用 `{safe_message}`

退出码 0 = 通过，1 = 存在未转义字段。
"""

import re
import sys
from pathlib import Path

REPORTER = Path("src/reporters/html_reporter.py")

# 必须被 escape() 包裹的用户文本字段。
# 集中为模块常量: reporter 可 `from check_html_escape import REQUIRED_ESCAPE_FIELDS` 引用（可选）。
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


def find_variable_assignments(content: str) -> dict[str, str]:
    """提取简单的单行赋值 `var = rhs`（忽略含 # 的行，避免取到注释）。"""
    assignments: dict[str, str] = {}
    for m in re.finditer(r"^\s*(\w+)\s*=\s*([^\n#]+)$", content, re.MULTILINE):
        assignments[m.group(1)] = m.group(2).strip()
    return assignments


def find_escaped_variables(content: str) -> set[str]:
    """识别"转义结果先存变量"模式: `safe = escape(...)` / `safe = html.escape(...)`。

    返回保存了已转义内容的变量名集合，供模板引用 `{safe}` 时放行。
    """
    return {name for name, rhs in find_variable_assignments(content).items() if "escape(" in rhs}


def check_field_escaping(content: str) -> list[str]:
    """检查模板字符串中用户字段是否被 escape() 包裹（含变量中转义模式）。"""
    errors = []
    assignments = find_variable_assignments(content)
    escaped_vars = {n for n, r in assignments.items() if "escape(" in r}
    # 查找所有 {f.xxx} 或 {xxx} 模板表达式
    template_exprs = re.findall(r"\{([^}]+)\}", content)

    for field in REQUIRED_ESCAPE_FIELDS:
        # 引用该字段的模板表达式: 点引用 (f.xxx / .xxx) 或裸字段名 ({message})
        field_refs = [
            expr
            for expr in template_exprs
            if f".{field}" in expr or f"f.{field}" in expr or expr.strip() == field
        ]
        for ref in field_refs:
            # 内联转义 → 合规
            if "escape(" in ref or "escape (" in ref:
                continue
            var = ref.strip()
            # 变量中转义: message = escape(f.message) 后模板引用 {message} → 合规
            if var in escaped_vars:
                continue
            # 变量已赋值但未转义 (message = f.message) → 违规
            if var in assignments and "escape(" not in assignments[var]:
                errors.append(f"字段 '{field}' 未转义: {{{ref}}} (变量 {var} = {assignments[var]})")
                continue
            # 直接引用 (点引用或裸字段名) 且无赋值 → 违规
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
