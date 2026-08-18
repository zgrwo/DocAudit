"""tools/check_doc_numbers.py 的测试。

检查白名单文档中"当前事实"数字声明与代码实际值一致 (防数字漂移复发):
- 测试用例数 (pytest --collect-only 实测)
- 规则数 (rules.md ## 条目数)
- 测试文件数 (tests/test_*.py 数量)
- format.py 检查方法数 (project-structure.md 表格)
"""

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))


from check_doc_numbers import (
    check_declarations,
    count_format_checks,
    count_rules,
    count_test_files,
    strip_quoted_context,
)


def _lines(*parts: str) -> str:
    return "\n".join(parts)


def test_strip_quoted_context():
    """「」引号内的历史数字不参与检查 ('「53 用例」' 是历史教训记录)"""
    text = "CHANGELOG「53 用例」实际 189、agents.md 测试表 5 文件实际 12"
    stripped = strip_quoted_context(text)
    assert "53 用例" not in stripped
    assert "实际 189" in stripped  # 引号外保留


def test_check_test_count_ok():
    doc = _lines(
        "全量 pytest tests/ -v（189 用例）",
        "tests/ # 189 个用例（12 个文件，含黄金测试）",
    )
    errors = check_declarations(
        [("AGENTS.md", doc)],
        {"test_count": 189, "rule_count": 26, "file_count": 12, "format_checks": 11},
    )
    assert errors == []


def test_check_test_count_mismatch():
    doc = "全量 pytest tests/ -v（188 用例）"
    errors = check_declarations(
        [("AGENTS.md", doc)],
        {"test_count": 189, "rule_count": 26, "file_count": 12, "format_checks": 11},
    )
    assert len(errors) == 1
    assert "AGENTS.md" in errors[0]
    assert "测试用例数" in errors[0] and "189" in errors[0]


def test_check_rule_count_mismatch():
    doc = "本地离线文档审查系统：PPTX/DOCX/PDF/MD → 25 条规则"
    errors = check_declarations(
        [("AGENTS.md", doc)],
        {"test_count": 189, "rule_count": 26, "file_count": 12, "format_checks": 11},
    )
    assert len(errors) == 1
    assert "规则数" in errors[0] and "26" in errors[0]


def test_check_file_count_mismatch():
    doc = "189 个用例，11 个文件："
    errors = check_declarations(
        [("AGENTS.md", doc)],
        {"test_count": 189, "rule_count": 26, "file_count": 12, "format_checks": 11},
    )
    assert len(errors) == 1
    assert "测试文件数" in errors[0] and "12" in errors[0]


def test_check_format_checks_mismatch():
    doc = "| `format.py` | `FormatAuditor` | FMT-001~008 | 10 |"
    errors = check_declarations(
        [("rules/project-structure.md", doc)],
        {"test_count": 189, "rule_count": 26, "file_count": 12, "format_checks": 11},
    )
    assert len(errors) == 1
    assert "format.py" in errors[0] and "11" in errors[0]


def test_rule_count_variants_detected():
    """规则数声明的多种写法都被识别"""
    doc = _lines(
        "规则: 26 条",
        "共 26 条审查规则",
        "（26 条，配置驱动）",
        "26 条配置驱动规则",
    )
    errors = check_declarations(
        [("README.md", doc)],
        {"test_count": 189, "rule_count": 26, "file_count": 12, "format_checks": 11},
    )
    assert errors == []


def test_rule_count_exemption_context_ignored():
    """LOW12: 「（N 条豁免」语境 (豁免/排除数量) 不算规则数声明 — 防误报"""
    doc = "上述规则中（3 条豁免仅限本次审查），其余（26 条均生效）"
    errors = check_declarations(
        [("README.md", doc)],
        {"test_count": 189, "rule_count": 26, "file_count": 12, "format_checks": 11},
    )
    assert errors == []


def test_rule_count_exemption_with_space_ignored():
    """LOW12: 「（N 条 豁免」带空格同样排除"""
    doc = "（3 条 豁免处理）"
    errors = check_declarations(
        [("README.md", doc)],
        {"test_count": 189, "rule_count": 26, "file_count": 12, "format_checks": 11},
    )
    assert errors == []


def test_changelog_historical_section_ignored():
    """CHANGELOG 0.1.0 历史区不检查 (119 个测试用例是历史事实)"""
    doc = _lines(
        "## [Unreleased]",
        "- 文档数字漂移：CHANGELOG 测试用例数 53 → 189",
        "## [0.1.0] - 2026-07-26",
        "- 119 个测试用例（模型/审计器/引擎/规则/集成）",
    )
    errors = check_declarations(
        [("CHANGELOG.md", doc)],
        {"test_count": 189, "rule_count": 26, "file_count": 12, "format_checks": 11},
    )
    assert errors == []


def test_count_rules():
    rules_md = _lines(
        "## STR-001: 标题页",
        "## STR-002: 编号",
        "## FMT-001: 字体",
        "# 术语规则",
        "## TERM-001: 术语",
    )
    assert count_rules(rules_md) == 4  # ## 条目数 (忽略 # 一级标题)


def test_count_test_files(tmp_path):
    for name in ("test_a.py", "test_b.py", "helper.py"):
        (tmp_path / name).write_text("", encoding="utf-8")
    assert count_test_files(tmp_path) == 2


def test_count_format_checks(tmp_path):
    src = tmp_path / "format.py"
    src.write_text(
        textwrap.dedent(
            """\
            class FormatAuditor:
                def _check_font_consistency(self, page): ...
                def _check_font_size(self, page): ...
                def audit(self, doc): ...
                def _helper_private(self): ...
            """
        ),
        encoding="utf-8",
    )
    assert count_format_checks(src) == 2  # 只数 _check_* 方法
