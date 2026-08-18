"""tools/check_api_sync.py 的测试。

条目形式匹配规则（与 tools/check_api_sync.py 保持一致）:
- 名称必须出现在表格行（| 包围）或代码块（` 包围）中才算已记录
- 保守实现: 名字紧邻的前后字符必须是 `、| 或行首/行尾
- 仅"在正文散文里提到一次"不算已记录（旧实现是子串匹配，会漏检）
"""

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from check_api_sync import (  # noqa: E402
    check_api_reference,
    extract_public_names,
    is_documented,
)

# ── is_documented: 条目形式匹配 ──────────────────────────────


def test_name_in_backticks_recorded():
    """代码块 (`name`) 中的名称 → 已记录"""
    assert is_documented("parse_rules_md", "| `parse_rules_md` | `(file_path)` |")


def test_name_in_table_row_recorded():
    """表格行 (| 包围) 中的名称 → 已记录"""
    assert is_documented("audit", "| `audit` | `(doc: Document)` | → `list[AuditFinding]` |")


def test_name_in_prose_not_recorded():
    """仅在正文散文中出现 → 不算已记录（旧子串匹配会误放行）"""
    doc = "建议不要直接调用 Pipeline 类，应通过 build_auditors 使用。"
    assert is_documented("Pipeline", doc) is False


def test_name_in_plain_heading_not_recorded():
    """普通标题中的名称（无反引号/表格）→ 不算已记录"""
    doc = "### LanguageToolClient src/engines/languagetool.py"
    assert is_documented("LanguageToolClient", doc) is False


def test_name_as_substring_of_other_entry_not_recorded():
    """名称是其他条目子串（`check_chinese_only` 含 'check'）→ 不算已记录"""
    doc = "| `check_chinese_only` | `(text: str)` | 仅中文检查 |"
    assert is_documented("check", doc) is False


def test_name_at_line_start_or_end():
    """名称在行首/行尾且边界为分隔符 → 已记录"""
    assert is_documented("Run", "`Run`")
    assert is_documented("convert", "|`convert`|")


# ── extract_public_names ─────────────────────────────────────


def test_extract_public_names(tmp_path):
    src = tmp_path / "sample.py"
    src.write_text(
        textwrap.dedent(
            """\
            def public_func():
                pass

            class PublicClass:
                def method(self):
                    pass

            def _private():
                pass

            def main():
                pass
            """
        ),
        encoding="utf-8",
    )
    names = extract_public_names(src)
    assert names == ["public_func", "PublicClass"]  # 私有/嵌套/main 排除


# ── check_api_reference ──────────────────────────────────────


def test_check_api_reference_missing_reported():
    content = "| `parse_rules_md` | `(file_path)` |"
    missing = check_api_reference(
        content, ["parse_rules_md", "AuditRule"], "src/engines/rule_parser.py"
    )
    assert missing == ["src/engines/rule_parser.py: AuditRule"]


def test_check_api_reference_all_documented():
    content = textwrap.dedent(
        """\
        ### `AuditRule` src/engines/rule_parser.py

        | 方法 | 签名 |
        |------|------|
        | `parse_rules_md` | `(file_path: str | Path)` |
        """
    )
    missing = check_api_reference(
        content, ["parse_rules_md", "AuditRule"], "src/engines/rule_parser.py"
    )
    assert missing == []


# ── 端到端: 临时模块 + 临时文档 ─────────────────────────────


def test_module_missing_from_doc_flags(tmp_path):
    """模块中的公开名在文档中未记录 → 报告缺失"""
    module = tmp_path / "new_module.py"
    module.write_text("def shiny_new_api(): ...\n", encoding="utf-8")
    api_doc = tmp_path / "api.md"
    api_doc.write_text("# API\n\nshiny_new_api 是核心接口。\n", encoding="utf-8")

    names = extract_public_names(module)
    missing = check_api_reference(api_doc.read_text(encoding="utf-8"), names, str(module))
    assert missing == [f"{module}: shiny_new_api"]


def test_module_entry_added_passes(tmp_path):
    """补上条目形式的记录后 → 不再缺失"""
    module = tmp_path / "new_module.py"
    module.write_text("def shiny_new_api(): ...\n", encoding="utf-8")
    api_doc = tmp_path / "api.md"
    api_doc.write_text(
        "# API\n\n| 函数 | 签名 |\n|------|------|\n| `shiny_new_api` | `()` |\n",
        encoding="utf-8",
    )

    names = extract_public_names(module)
    missing = check_api_reference(api_doc.read_text(encoding="utf-8"), names, str(module))
    assert missing == []
