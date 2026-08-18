"""CI 验证脚本：api-reference.md 同步检查。

检查 src/ 中的关键公开函数/类是否在 rules/api-reference.md 中有记录。
匹配方式: 名称须以"条目形式"出现 (表格行 `|...|` 或代码块 `...`)。
M10 增强: 同时校验函数签名 — 文档表格行须含该函数的形参名
(无参函数行须含 `()`；行内含多数形参名即可，容错子集；确有差异的行可在行尾
加豁免标记 `<!-- api-sync-exempt -->`)。
退出码 0 = 通过，1 = 存在未文档化的公开接口或签名不一致。
"""

import re
import sys
from pathlib import Path

SRC_ROOT = Path("src")
API_REF = Path("rules/api-reference.md")

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

# 忽略的函数/类名模式
IGNORE_PATTERNS = [
    re.compile(r"^_"),  # 私有
    re.compile(r"^main$"),  # CLI 入口
    re.compile(r"^test_"),  # 测试
]

# 签名豁免标记: 文档表格行行尾含此标记 → 跳过该函数的形参名检查
# (确有签名差异的行使用，见 api-reference.md 现有条目风格)
SIGNATURE_EXEMPT_MARKER = "api-sync-exempt"


def extract_public_names(filepath: Path) -> list[str]:
    """提取文件中的公开函数和类名。"""
    if not filepath.exists():
        return []

    content = filepath.read_text(encoding="utf-8")
    names = []

    # 匹配 def func_name( 和 class ClassName
    for match in re.finditer(r"^(?:def|class)\s+(\w+)", content, re.MULTILINE):
        name = match.group(1)
        if not any(pat.match(name) for pat in IGNORE_PATTERNS):
            names.append(name)

    return names


def _balanced_paren_end(content: str, start: int) -> int:
    """从 start 处的 '(' 起平衡括号扫描，返回配对的 ')' 索引 (找不到返回 len)。"""
    depth = 0
    i = start
    while i < len(content):
        ch = content[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(content)


def _split_top_level(s: str) -> list[str]:
    """按顶层逗号拆分 (忽略方括号/圆括号内的逗号，兼容嵌套泛型如 Callable[[str, int], None])。"""
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


def extract_public_signatures(filepath: Path) -> dict[str, list[str]]:
    """提取文件中公开函数的形参名列表: {函数名: [形参名, ...]}。

    仅顶层 def 函数 (类由 extract_public_names 的条目检查覆盖，无签名要求)。
    无参函数映射到空列表 (文档表格行须含 `()`)。
    私有/嵌套/main 按 IGNORE_PATTERNS 排除。
    """
    if not filepath.exists():
        return {}

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


def find_documented_line(content: str, name: str) -> str | None:
    """返回 name 以条目形式出现所在的行 (无 → None)。"""
    for line in content.splitlines():
        if is_documented(name, line):
            return line
    return None


def check_signatures(content: str, sigs: dict[str, list[str]], module: str) -> list[str]:
    """检查文档表格行中的形参名与代码签名一致性。

    - 无参函数: 行须含 `()`
    - 有参函数: 行内含多数形参名即可 (matched * 2 > len(params)，容错子集)
    - 行尾含豁免标记 (<!-- api-sync-exempt -->) → 跳过该函数签名检查
    """
    errors: list[str] = []
    for name, params in sigs.items():
        line = find_documented_line(content, name)
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


def is_documented(name: str, content: str) -> bool:
    """名称是否以"条目形式"记录在文档中。

    保守实现：名字必须出现在表格行 (`|` 包围) 或代码块 (`````` 包围) 中——
    即名字紧邻的前后字符是 `、`|` 或行首/行尾。
    仅"在正文散文里提到一次"不再算已记录（旧实现为子串匹配，易漏检）。
    """
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


def check_api_reference(
    content: str,
    names: list[str],
    module: str,
    sigs: dict[str, list[str]] | None = None,
) -> list[str]:
    """检查名称是否以条目形式记录在 api-reference.md 中。

    sigs: 可选 — extract_public_signatures() 的形参名表; 提供时追加签名一致性检查。
    """
    missing = []
    for name in names:
        if not is_documented(name, content):
            missing.append(f"{module}: {name}")
    if sigs:
        missing.extend(check_signatures(content, sigs, module))
    return missing


def main() -> int:
    if not API_REF.exists():
        print(f"ERROR: {API_REF} 不存在")
        return 1

    api_content = API_REF.read_text(encoding="utf-8")
    all_missing = []

    for module_path in CHECKED_MODULES:
        filepath = (
            SRC_ROOT.parent / module_path
            if not Path(module_path).is_absolute()
            else Path(module_path)
        )
        if not filepath.exists():
            filepath = Path(module_path)
        names = extract_public_names(filepath)
        sigs = extract_public_signatures(filepath)
        missing = check_api_reference(api_content, names, module_path, sigs=sigs)
        all_missing.extend(missing)

    if all_missing:
        print("api-reference.md 同步检查失败 — 以下公开接口未记录:")
        for item in all_missing:
            print(f"  - {item}")
        print(f"\n请将缺失接口补充到 {API_REF}")
        return 1

    print("api-reference.md sync check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
