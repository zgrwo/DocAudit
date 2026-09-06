"""治理门禁的 pytest 化（2026-09-06 5S：原 tools/ 五门禁的回归版）。

原 tools/check_*.py 独立脚本随 5S 移除，本文件将其检查逻辑原样移植为测试断言，
保证等价的自动把关（skill 双份同步门禁因 .qoder/ 移除而失去意义，不再保留）：

- test_bare_handlers_gate   裸异常处理器（AST 感知；`# bare-handler-ok` 豁免约定不变）
- test_html_escape_gate     html_reporter.py + app.py 的 html.escape 合规
- test_api_sync_gate        公开接口在 api-reference.md 的条目化记录 + 签名一致性
- test_doc_numbers_gate     白名单文档数字与实测一致（防数字漂移复发，历史 3+ 次）

维护义务：新增/删除测试文件或用例后，必须同步白名单文档中的数字
（AGENTS.md / CLAUDE.md / README.md / api-reference / project-structure / specification），
test_doc_numbers_gate 会在数字漂移时失败并指名文件。
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────────────────────────────────────
# 门禁 1：裸异常处理器检查（移植自 tools/check_bare_handlers.py）
# ─────────────────────────────────────────────────────────────────────────────

BARE_HANDLER_MARKER = "# bare-handler-ok"
EXCLUDED_DIRS = {
    ".venv",
    "build",
    "dist",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "logs",
    "packages",
    "docaudit.egg-info",
}


def iter_py_files(scope: Path) -> list[Path]:
    """返回作用域内待检查的 .py 文件（目录递归且排除生成/虚拟环境目录）。"""
    return [p for p in scope.rglob("*.py") if not any(part in EXCLUDED_DIRS for part in p.parts)]


def check_bare_handlers_in_file(path: Path) -> list[str]:
    """检查单个文件，返回违规描述列表（空 = 通过）。"""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, UnicodeDecodeError, SyntaxError) as e:
        return [f"{path}: 解析失败: {e}"]

    lines = source.splitlines()
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.type is None:
            findings.append(f"{path}:{node.lineno}: 裸 except:（必须指定异常类型）")
            continue
        tname = node.type.id if isinstance(node.type, ast.Name) else None
        if tname == "BaseException":
            findings.append(
                f"{path}:{node.lineno}: except BaseException（会吞掉 KeyboardInterrupt/SystemExit）"
            )
            continue
        if tname != "Exception":
            continue  # 具体异常类型放行

        body_stmts = [s for s in node.body if not isinstance(s, ast.Pass)]
        if body_stmts:
            continue  # 有实际处理语句（return/raise/调用/赋值/日志）→ 放行

        # 豁免标记可出现在 except 语句上一行到最后一个 body 语句行之间的任意行
        end_line = node.body[-1].end_lineno if node.body else node.lineno
        window = lines[max(0, node.lineno - 2) : end_line]
        if any(BARE_HANDLER_MARKER in line for line in window):
            continue
        findings.append(
            f"{path}:{node.lineno}: except Exception 静默吞异常（体为空/仅 pass）；"
            f"若为刻意的降级路径，请在 except 行附 '{BARE_HANDLER_MARKER} — 理由'"
        )
    return findings


def test_bare_handlers_gate():
    """全仓库（排除生成目录，含 .venv）AST 扫描：无裸 except / 静默吞异常。"""
    findings: list[str] = []
    for py_file in iter_py_files(PROJECT_ROOT):
        findings.extend(check_bare_handlers_in_file(py_file))
    assert not findings, "裸异常处理器检查失败:\n" + "\n".join(f"  - {f}" for f in findings)


# ─────────────────────────────────────────────────────────────────────────────
# 门禁 2：html.escape 合规性检查（移植自 tools/check_html_escape.py）
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_ESCAPE_FIELDS = [
    "message",
    "context",
    "suggestion",
    "location",
    "source_path",
    "title",
    "rule_id",
]


def find_variable_assignments(content: str) -> dict[str, str]:
    """提取简单的单行赋值 `var = rhs`（忽略含 # 的行，避免取到注释）。"""
    return {
        m.group(1): m.group(2).strip()
        for m in re.finditer(r"^\s*(\w+)\s*=\s*([^\n#]+)$", content, re.MULTILINE)
    }


def check_field_escaping(content: str) -> list[str]:
    """检查模板字符串中用户字段是否被 escape() 包裹（含变量中转义模式）。"""
    errors = []
    assignments = find_variable_assignments(content)
    escaped_vars = {n for n, r in assignments.items() if "escape(" in r}
    template_exprs = re.findall(r"\{([^}]+)\}", content)

    for field in REQUIRED_ESCAPE_FIELDS:
        field_refs = [
            expr
            for expr in template_exprs
            if f".{field}" in expr or f"f.{field}" in expr or expr.strip() == field
        ]
        for ref in field_refs:
            if "escape(" in ref or "escape (" in ref:
                continue
            var = ref.strip()
            if var in escaped_vars:
                continue
            if var in assignments and "escape(" not in assignments[var]:
                errors.append(f"字段 '{field}' 未转义: {{{ref}}} (变量 {var} = {assignments[var]})")
                continue
            errors.append(f"字段 '{field}' 未转义: {{{ref}}}")

    return errors


def _extract_st_call_args(content: str) -> list[str]:
    """提取 st.markdown(...) / st.expander(...) 调用的参数内容 (平衡括号匹配，支持多行)。"""
    args_list: list[str] = []
    for m in re.finditer(r"st\.(?:markdown|expander)\s*\(", content):
        start = m.end()
        depth = 1
        i = start
        while i < len(content) and depth > 0:
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
            i += 1
        args_list.append(content[start : max(start, i - 1)])
    return args_list


def _variable_base(expr: str) -> str:
    """模板表达式的变量基名: {msg[:80]} → msg; {finding.message} → finding。"""
    return expr.strip().split("[")[0].split(".")[0]


def _field_of_rhs(rhs: str) -> str | None:
    """赋值右侧是否引用用户字段 → 返回字段名 (无 → None)。"""
    for field in REQUIRED_ESCAPE_FIELDS:
        if f".{field}" in rhs or f"f.{field}" in rhs or rhs.strip() == field:
            return field
    return None


def check_streamlit_escaping(content: str) -> list[str]:
    """检查 app.py 中 st.markdown/st.expander 模板表达式对用户字段的直接引用。"""
    errors: list[str] = []
    assignments = find_variable_assignments(content)
    escaped_vars = {n for n, r in assignments.items() if "escape(" in r}

    for args in _extract_st_call_args(content):
        for ref in re.findall(r"\{([^}]+)\}", args):
            base = _variable_base(ref)
            field: str | None = None
            for fld in REQUIRED_ESCAPE_FIELDS:
                if f".{fld}" in ref or f"f.{fld}" in ref or ref.strip() == fld:
                    field = fld
                    break
            if field is None and base in assignments:
                field = _field_of_rhs(assignments[base])
            if field is None:
                continue
            if "escape(" in ref or "escape (" in ref:
                continue
            if base in escaped_vars:
                continue
            if base in assignments and "escape(" not in assignments[base]:
                errors.append(
                    f"app.py st.markdown/st.expander 中字段 '{field}' 未转义: {{{ref}}} "
                    f"(变量 {base} = {assignments[base]})"
                )
                continue
            errors.append(f"app.py st.markdown/st.expander 中字段 '{field}' 未转义: {{{ref}}}")

    return errors


def test_html_escape_gate():
    """html_reporter.py 与 app.py 的用户可控文本必须经 html.escape()。"""
    reporter = (PROJECT_ROOT / "src/reporters/html_reporter.py").read_text(encoding="utf-8")
    app = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")

    errors: list[str] = []
    if "from html import escape" not in reporter and "import html" not in reporter:
        errors.append("html_reporter.py 缺少 html.escape 导入")
    errors.extend(check_field_escaping(reporter))
    errors.extend(check_streamlit_escaping(app))
    assert not errors, "html.escape 合规性检查失败:\n" + "\n".join(f"  - {e}" for e in errors)


# ─────────────────────────────────────────────────────────────────────────────
# 门禁 3：api-reference.md 同步检查（移植自 tools/check_api_sync.py）
# ─────────────────────────────────────────────────────────────────────────────

API_REF_PATH = PROJECT_ROOT / "docs/specification/api-reference.md"

# 需要检查的关键模块（公开入口点）
CHECKED_MODULES = [
    "src/models/document.py",
    "src/models/finding.py",
    "src/engines/pipeline.py",
    "src/reporters/html_reporter.py",
    "src/reporters/json_reporter.py",
    "src/cli.py",
    "src/auditors/structure.py",
    "src/auditors/format.py",
    "src/auditors/factual.py",
    "src/auditors/language.py",
    "src/auditors/custom_rules.py",
    "src/converters/base.py",
    "src/converters/pptx_converter.py",
    "src/converters/docx_converter.py",
    "src/converters/md_converter.py",
    "src/converters/pdf_converter.py",
    "src/engines/rule_parser.py",
    "src/engines/terminology.py",
    "src/engines/vocabulary.py",
    "src/engines/languagetool.py",
    "src/engines/autofix.py",
]

# 忽略的函数/类名模式：私有 / CLI 入口 / 测试
IGNORE_PATTERNS = [re.compile(r"^_"), re.compile(r"^main$"), re.compile(r"^test_")]

# 签名豁免标记: 文档表格行行尾含此标记 → 跳过该函数的形参名检查
SIGNATURE_EXEMPT_MARKER = "api-sync-exempt"


def _extract_public_names(filepath: Path) -> list[str]:
    """提取文件中的公开函数和类名。"""
    content = filepath.read_text(encoding="utf-8")
    return [
        m.group(1)
        for m in re.finditer(r"^(?:def|class)\s+(\w+)", content, re.MULTILINE)
        if not any(pat.match(m.group(1)) for pat in IGNORE_PATTERNS)
    ]


def _balanced_paren_end(content: str, start: int) -> int:
    """从 start 处的 '(' 起平衡括号扫描，返回配对的 ')' 索引 (找不到返回 len)。"""
    depth = 0
    i = start
    while i < len(content):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(content)


def _split_top_level(s: str) -> list[str]:
    """按顶层逗号拆分 (忽略括号内逗号，兼容嵌套泛型如 Callable[[str, int], None])。"""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def _parse_params(param_str: str) -> list[str]:
    """形参列表字符串 → 形参名列表 (剔除 self/cls、*args/**kwargs、类型注解、默认值)。"""
    params: list[str] = []
    for part in _split_top_level(param_str):
        part = part.strip()
        if not part:
            continue
        name = part.split(":")[0].split("=")[0].strip()
        if not name or name in ("self", "cls") or name.startswith("*"):
            continue
        params.append(name)
    return params


def _extract_public_signatures(filepath: Path) -> dict[str, list[str]]:
    """提取文件中顶层公开函数的形参名列表: {函数名: [形参名, ...]}。"""
    content = filepath.read_text(encoding="utf-8")
    sigs: dict[str, list[str]] = {}
    for match in re.finditer(r"^def\s+(\w+)", content, re.MULTILINE):
        name = match.group(1)
        if any(pat.match(name) for pat in IGNORE_PATTERNS):
            continue
        open_paren = content.find("(", match.end(), match.end() + 200)
        if open_paren == -1:
            sigs[name] = []
            continue
        close_paren = _balanced_paren_end(content, open_paren)
        sigs[name] = _parse_params(content[open_paren + 1 : close_paren])
    return sigs


def _is_documented(name: str, content: str) -> bool:
    """名称是否以"条目形式"记录（表格行 `|` 包围或反引号 ` 包围），散文提及不算。"""
    for line in content.splitlines():
        idx = 0
        while True:
            i = line.find(name, idx)
            if i == -1:
                break
            before = line[i - 1] if i > 0 else ""
            after = line[i + len(name)] if i + len(name) < len(line) else ""
            if before in ("`", "|", "") and after in ("`", "|", ""):
                return True
            idx = i + 1
    return False


def _find_documented_line(content: str, name: str) -> str | None:
    for line in content.splitlines():
        if _is_documented(name, line):
            return line
    return None


def _check_signatures(content: str, sigs: dict[str, list[str]], module: str) -> list[str]:
    """检查文档表格行中的形参名与代码签名一致性（行尾豁免标记可跳过）。"""
    errors: list[str] = []
    for name, params in sigs.items():
        line = _find_documented_line(content, name)
        if line is None:
            continue  # 名称缺失由名称检查报告
        if SIGNATURE_EXEMPT_MARKER in line:
            continue
        if not params:
            if "()" not in line:
                errors.append(f"{module}: {name} 无参函数，文档行须含 '()' — {line.strip()}")
        else:
            missing = [p for p in params if p not in line]
            matched = len(params) - len(missing)
            if matched * 2 <= len(params):
                errors.append(
                    f"{module}: {name} 文档行缺少形参名 {missing} "
                    f"(签名与 api-reference.md 不一致) — {line.strip()}"
                )
    return errors


def test_api_sync_gate():
    """src/ 公开接口必须以条目形式记录于 api-reference.md 且签名一致。"""
    api_content = API_REF_PATH.read_text(encoding="utf-8")
    missing: list[str] = []
    for module_path in CHECKED_MODULES:
        filepath = PROJECT_ROOT / module_path
        if not filepath.exists():
            missing.append(f"{module_path}: 文件不存在")
            continue
        for name in _extract_public_names(filepath):
            if not _is_documented(name, api_content):
                missing.append(f"{module_path}: {name}")
        missing.extend(
            _check_signatures(api_content, _extract_public_signatures(filepath), module_path)
        )
    assert not missing, (
        "api-reference.md 同步检查失败 — 以下公开接口未记录或签名不一致:\n"
        + "\n".join(f"  - {m}" for m in missing)
    )


# ─────────────────────────────────────────────────────────────────────────────
# 门禁 4：文档数字一致性检查（移植自 tools/check_doc_numbers.py）
# ─────────────────────────────────────────────────────────────────────────────

# 只检查"当前事实"文档；历史/规划文档不在白名单，愿景数字不受检
DOC_NUMBER_FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "docs/specification/api-reference.md",
    "docs/governance/project-structure.md",
    "docs/specification/specification.md",
    "CHANGELOG.md",  # 仅 Unreleased 区 (历史区在 extract 时截断)
]

# 测试用例数: "349 个用例" / "（349 用例）" / "349 个测试用例"
TEST_COUNT_RES = [
    re.compile(r"(\d+)\s*个用例"),
    re.compile(r"(\d+)\s*用例"),
    re.compile(r"(\d+)\s*个测试用例"),
]
# 规则数: "26 条规则" / "26 条审查规则" / "规则: 26 条"
# 「（N 条豁免」是豁免/排除数量语境，不是规则数声明 — 用否定前瞻排除
RULE_COUNT_RES = [
    re.compile(r"(\d+)\s*条(?:审查|配置驱动)?规则"),
    re.compile(r"规则[：:]\s*(\d+)\s*条"),
    re.compile(r"（(\d+)\s*条(?!\s*豁免)"),
]
# 测试文件数: "18 个文件" (排除 "超过 5 个文件" 会话管理指南语境)
FILE_COUNT_RES = [re.compile(r"(?<!超过 )(\d+)\s*个文件")]
# format.py 检查数: "| `format.py` | `FormatAuditor` | FMT-001~008 | 11 |"
FORMAT_CHECK_RE = re.compile(r"\|\s*`format\.py`\s*\|[^|]*\|[^|]*\|\s*(\d+)\s*\|")


def _strip_quoted_context(text: str) -> str:
    """剥离「」引号内容: 引号内是历史教训/教学语境, 数字不参与检查。"""
    return re.sub(r"「[^」]*」", "", text)


def _unreleased_section(text: str) -> str:
    """只保留 CHANGELOG Unreleased 区 (历史版本条目是当时事实, 不检查)。"""
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


def _collect_actual_counts() -> dict:
    """从代码/仓库收集实际值；收集不完整时 test_count=-1（跳过测试数检查防误报）。"""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    combined = (r.stdout or "") + "\n" + (r.stderr or "")
    m = re.search(r"(\d+) tests? collected", combined)
    if m is None:
        test_count = -1
    else:
        test_count = int(m.group(1))
        # 收集有 error（如缺失可选依赖）→ 测试数不完整，不可作为"实际值"比对
        if re.search(r"\berrors?\b", combined, re.IGNORECASE) or "Interrupted" in combined:
            test_count = -1

    rules_md = (PROJECT_ROOT / "rules.md").read_text(encoding="utf-8")
    return {
        "test_count": test_count,
        "rule_count": len(re.findall(r"^## ", rules_md, re.MULTILINE)),
        "file_count": len(list((PROJECT_ROOT / "tests").glob("test_*.py"))),
        "format_checks": len(
            re.findall(
                r"^\s+def (_check_\w+)\(",
                (PROJECT_ROOT / "src/auditors/format.py").read_text(encoding="utf-8"),
                re.MULTILINE,
            )
        ),
    }


def test_doc_numbers_gate():
    """白名单文档声明的数字（用例数/规则数/文件数/format 检查数）与实测一致。"""
    actual = _collect_actual_counts()
    errors: list[str] = []
    for rel in DOC_NUMBER_FILES:
        path = PROJECT_ROOT / rel
        assert path.exists(), f"白名单文档不存在: {rel}"
        content = path.read_text(encoding="utf-8")
        if rel.endswith("CHANGELOG.md"):
            content = _unreleased_section(content)
        content = _strip_quoted_context(content)

        if actual["test_count"] != -1:
            for value in _declared_values(content, TEST_COUNT_RES):
                if value != actual["test_count"]:
                    errors.append(f"{rel}: 测试用例数声明 {value} ≠ 实际 {actual['test_count']}")
        for value in _declared_values(content, RULE_COUNT_RES):
            if value != actual["rule_count"]:
                errors.append(f"{rel}: 规则数声明 {value} ≠ 实际 {actual['rule_count']}")
        for value in _declared_values(content, FILE_COUNT_RES):
            if value != actual["file_count"]:
                errors.append(f"{rel}: 测试文件数声明 {value} ≠ 实际 {actual['file_count']}")
        m = FORMAT_CHECK_RE.search(content)
        if m and int(m.group(1)) != actual["format_checks"]:
            errors.append(
                f"{rel}: format.py 检查数声明 {m.group(1)} ≠ 实际 {actual['format_checks']}"
            )
    assert not errors, "文档数字一致性检查失败:\n" + "\n".join(f"  - {e}" for e in errors)
