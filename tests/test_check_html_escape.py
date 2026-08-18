"""tools/check_html_escape.py 的测试。

规则（与 tools/check_html_escape.py 保持一致）:
- 用户字段 (message/context/suggestion/location/source_path/title/rule_id) 必须被 escape() 包裹
- 支持内联转义 `{escape(f.message)}` 与变量中转义 `safe = escape(f.message)` 后 `{safe}`
- 裸字段引用 `{message}` 未转义 → 违规
"""

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from check_html_escape import (  # noqa: E402
    REQUIRED_ESCAPE_FIELDS,
    check_escape_import,
    check_field_escaping,
    find_escaped_variables,
)


def test_required_fields_constant():
    """字段清单集中为模块常量，覆盖红线要求的所有用户文本字段"""
    assert "message" in REQUIRED_ESCAPE_FIELDS
    assert "context" in REQUIRED_ESCAPE_FIELDS
    assert "suggestion" in REQUIRED_ESCAPE_FIELDS
    assert "location" in REQUIRED_ESCAPE_FIELDS
    assert "source_path" in REQUIRED_ESCAPE_FIELDS
    assert "title" in REQUIRED_ESCAPE_FIELDS


def test_escape_import_detection():
    assert check_escape_import("from html import escape") == []
    assert check_escape_import("import html") == []
    assert len(check_escape_import("no import here")) == 1


def test_inline_escape_ok():
    content = textwrap.dedent(
        """\
        html = f"<div>{escape(f.message)}</div>"
        """
    )
    assert check_field_escaping(content) == []


def test_unescaped_dotted_field_flagged():
    content = textwrap.dedent(
        """\
        html = f"<div>{f.message}</div>"
        """
    )
    errors = check_field_escaping(content)
    assert len(errors) == 1
    assert "message" in errors[0]


def test_unescaped_bare_field_flagged():
    """裸字段名引用 {message} 未转义 → 违规（旧实现只查点引用，会漏检）"""
    content = textwrap.dedent(
        """\
        html = f"<div>{message}</div>"
        """
    )
    errors = check_field_escaping(content)
    assert len(errors) == 1
    assert "message" in errors[0]


def test_escaped_variable_pattern_ok():
    """转义结果先存变量再插入模板 → 合规 (新增检测)"""
    content = textwrap.dedent(
        """\
        safe_message = escape(f.message)
        safe_ctx = html.escape(f.context)
        html = f"<div>{safe_message} | {safe_ctx}</div>"
        """
    )
    assert find_escaped_variables(content) == {"safe_message", "safe_ctx"}
    assert check_field_escaping(content) == []


def test_bare_var_with_escape_assignment_ok():
    """变量名与字段同名: message = escape(f.message) 后 {message} → 合规 (新增检测)"""
    content = textwrap.dedent(
        """\
        message = escape(f.message)
        html = f"<div>{message}</div>"
        """
    )
    assert find_escaped_variables(content) == {"message"}
    assert check_field_escaping(content) == []


def test_bare_var_without_escape_assignment_flagged():
    """变量名与字段同名但未转义: message = f.message 后 {message} → 违规"""
    content = textwrap.dedent(
        """\
        message = f.message
        html = f"<div>{message}</div>"
        """
    )
    assert find_escaped_variables(content) == set()
    errors = check_field_escaping(content)
    assert len(errors) == 1
    assert "message" in errors[0]


def test_clean_reporter_like_content_passes():
    """模拟当前 html_reporter.py 的合规写法 → 无违规"""
    content = textwrap.dedent(
        """\
        from html import escape
        parts.append(f'<div class="finding-message">{escape(f.message or "")}</div>')
        parts.append(f'<div class="finding-context">{escape(f.context)}</div>')
        parts.append(f'<div class="finding-suggestion">{escape(f.suggestion)}</div>')
        parts.append(f'<div class="finding-location">{escape(f.location)}</div>')
        html = f"<title>{escape(title)}</title><p>{escape(doc.source_path)}</p>"
        """
    )
    assert check_escape_import(content) == []
    assert check_field_escaping(content) == []


def test_non_field_vars_ignored():
    """与字段无关的模板变量 (计数/样式) → 不误报"""
    content = textwrap.dedent(
        """\
        html = f"<div class='stat'>{error_count} 个问题</div>"
        """
    )
    assert check_field_escaping(content) == []
