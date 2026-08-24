"""CI 验证脚本：文档数字一致性检查（防数字漂移复发）。

背景: 文档数字漂移已复发 3+ 次 (测试数 53→119→139→158→181→189、规则数 25→26、
format.py 检查数 10→11)，仅靠人工维护必然漏。本工具将"当前事实"数字纳入 CI 门禁。

检查项 (白名单文档中声明的数字 vs 代码实际值):
- 测试用例数   = pytest --collect-only 实测
- 规则数       = rules.md 的 "## " 条目数
- 测试文件数   = tests/test_*.py 数量
- format.py 检查数 = src/auditors/format.py 的 _check_* 方法数

历史/规划语境自动排除:
- 「」引号内的数字 (如「53 用例」历史教训记录)
- CHANGELOG 的 [0.1.0] 历史区 (历史条目数字是当时事实)
- 规划文档 (refactoring-plan.md / skills/ 等) 不在白名单, 愿景数字不受检

退出码 0 = 通过，1 = 存在漂移。
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 只检查"当前事实"文档；历史/规划文档 (refactoring-plan.md 等) 不在白名单
CHECKED_FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "rules/api-reference.md",
    "rules/project-structure.md",
    "rules/specification.md",
    "CHANGELOG.md",  # 仅 Unreleased 区 (历史区在 extract 时截断)
]

# 测试用例数: "189 个用例" / "（189 用例）" / "189 个测试用例"
_TEST_COUNT_RES = [
    re.compile(r"(\d+)\s*个用例"),
    re.compile(r"(\d+)\s*用例"),
    re.compile(r"(\d+)\s*个测试用例"),
]
# 规则数: "26 条规则" / "26 条审查规则" / "26 条配置驱动规则" / "规则: 26 条" / "（26 条"
# LOW12: 「（N 条豁免」是豁免/排除数量语境，不是规则数声明 — 用否定前瞻排除
_RULE_COUNT_RES = [
    re.compile(r"(\d+)\s*条(?:审查|配置驱动)?规则"),
    re.compile(r"规则[：:]\s*(\d+)\s*条"),
    re.compile(r"（(\d+)\s*条(?!\s*豁免)"),
]
# 测试文件数: "12 个文件" (排除 "超过 5 个文件" 会话管理指南语境)
_FILE_COUNT_RES = [re.compile(r"(?<!超过 )(\d+)\s*个文件")]
# format.py 检查数: "| `format.py` | `FormatAuditor` | FMT-001~008 | 11 |"
_FORMAT_CHECK_RE = re.compile(r"\|\s*`format\.py`\s*\|[^|]*\|[^|]*\|\s*(\d+)\s*\|")

_MISSING_DOC = """\
[FAIL] {file} 不存在 (应随仓库存在, 请检查路径)
"""


def strip_quoted_context(text: str) -> str:
    """剥离「」引号内容: 引号内是历史教训/教学语境, 数字不参与检查。"""
    return re.sub(r"「[^」]*」", "", text)


def _unreleased_section(text: str) -> str:
    """只保留 Unreleased 区 (历史版本条目是当时事实, 不检查)。"""
    m = re.search(r"^## \[Unreleased\].*?(?=^## \[)", text, re.MULTILINE | re.DOTALL)
    return m.group(0) if m else text


def _declared_values(text: str, patterns: list[re.Pattern]) -> set[int]:
    values: set[int] = set()
    for pat in patterns:
        for m in pat.finditer(text):
            try:
                values.add(int(m.group(1)))
            except ValueError:
                continue
    return values


def check_declarations(files: list[tuple[str, str]], actual: dict) -> list[str]:
    """核心纯函数: 检查文档声明数字与 actual 一致。

    Args:
        files: [(相对路径, 文档内容), ...]
        actual: {"test_count", "rule_count", "file_count", "format_checks"}

    Returns: 错误描述列表 (空 = 通过)。
    """
    errors: list[str] = []
    for rel_path, content in files:
        if rel_path.endswith("CHANGELOG.md"):
            content = _unreleased_section(content)
        content = strip_quoted_context(content)

        # test_count == -1 表示"收集不完整/未知"，跳过测试数检查避免误报
        if actual["test_count"] != -1:
            for value in _declared_values(content, _TEST_COUNT_RES):
                if value != actual["test_count"]:
                    errors.append(
                        f"{rel_path}: 测试用例数声明 {value} ≠ 实际 {actual['test_count']} "
                        f"(pytest --collect-only 实测)"
                    )
        for value in _declared_values(content, _RULE_COUNT_RES):
            if value != actual["rule_count"]:
                errors.append(
                    f"{rel_path}: 规则数声明 {value} ≠ 实际 {actual['rule_count']} "
                    f"(rules.md '## ' 条目数)"
                )
        for value in _declared_values(content, _FILE_COUNT_RES):
            if value != actual["file_count"]:
                errors.append(
                    f"{rel_path}: 测试文件数声明 {value} ≠ 实际 {actual['file_count']} "
                    f"(tests/test_*.py 数量)"
                )
        m = _FORMAT_CHECK_RE.search(content)
        if m and int(m.group(1)) != actual["format_checks"]:
            errors.append(
                f"{rel_path}: format.py 检查数声明 {m.group(1)} "
                f"≠ 实际 {actual['format_checks']} (_check_* 方法数)"
            )
    return errors


def count_rules(rules_md: str) -> int:
    """rules.md 的 '## ' 规则条目数 (忽略 '# ' 一级标题)。"""
    return len(re.findall(r"^## ", rules_md, re.MULTILINE))


def count_test_files(tests_dir: Path) -> int:
    """tests/ 下 test_*.py 文件数。"""
    return len(list(tests_dir.glob("test_*.py")))


def count_format_checks(format_py: Path) -> int:
    """src/auditors/format.py 的 _check_* 方法数。"""
    content = format_py.read_text(encoding="utf-8")
    return len(re.findall(r"^\s+def (_check_\w+)\(", content, re.MULTILINE))


def collect_actual_counts(root: Path) -> dict:
    """从代码/仓库收集实际值。"""
    # 测试用例数: pytest --collect-only (快, ~0.2s)
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    combined = (r.stdout or "") + "\n" + (r.stderr or "")
    m = re.search(r"(\d+) tests? collected", combined)
    if m is None:
        # 收集完全失败 (如未装 pytest) — 输出诊断，-1 表示"未知"
        print(
            f"[警告] pytest --collect-only 失败 (exit={r.returncode}): "
            f"{r.stderr.strip()[-300:] or r.stdout.strip()[-300:]}"
        )
        test_count = -1
    else:
        test_count = int(m.group(1))
        # 收集有 error (如缺失 streamlit 等可选依赖导致部分测试模块收集失败)
        # → 测试数不完整，不可作为"实际值"比对，否则误报数字漂移 (2026-08 P0-2)
        if re.search(r"\berrors?\b", combined, re.IGNORECASE) or "Interrupted" in combined:
            print(
                f"[警告] pytest --collect-only 存在 error，收集到 {test_count} 个用例不完整"
                f"（可能缺失依赖，如 streamlit）。已跳过测试数检查。\n"
                f"  请使用完整依赖的解释器 (如 .venv/Scripts/python.exe) 运行本门禁。"
            )
            test_count = -1

    rules_md = (root / "rules.md").read_text(encoding="utf-8")
    return {
        "test_count": test_count,
        "rule_count": count_rules(rules_md),
        "file_count": count_test_files(root / "tests"),
        "format_checks": count_format_checks(root / "src" / "auditors" / "format.py"),
    }


def main(argv: list[str]) -> int:
    if argv:
        roots = [Path(a) for a in argv]
    else:
        roots = [ROOT]

    all_errors: list[str] = []
    for root in roots:
        actual = collect_actual_counts(root)
        files: list[tuple[str, str]] = []
        missing = False
        for rel in CHECKED_FILES:
            p = root / rel
            if not p.exists():
                all_errors.append(_MISSING_DOC.format(file=rel))
                missing = True
                continue
            files.append((rel, p.read_text(encoding="utf-8")))
        if missing:
            continue
        all_errors.extend(check_declarations(files, actual))

    if all_errors:
        print("文档数字一致性检查失败:")
        for e in all_errors:
            print(f"  - {e}")
        print("\n请同步文档中的数字声明 (修改代码后必须同步 AGENTS.md/README 等)。")
        return 1
    print("check_doc_numbers passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
