"""CI 验证脚本：api-reference.md 同步检查。

检查 src/ 中的关键公开函数/类是否在 rules/api-reference.md 中有记录。
退出码 0 = 通过，1 = 存在未文档化的公开接口。
"""

import re
import sys
from pathlib import Path

SRC_ROOT = Path("src")
API_REF = Path("rules/api-reference.md")

# 需要检查的关键模块（公开入口点）
CHECKED_MODULES = [
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
    re.compile(r"^_"),        # 私有
    re.compile(r"^main$"),    # CLI 入口
    re.compile(r"^test_"),    # 测试
]


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


def check_api_reference(content: str, names: list[str], module: str) -> list[str]:
    """检查名称是否在 api-reference.md 中被提及。"""
    missing = []
    for name in names:
        if name not in content:
            missing.append(f"{module}: {name}")
    return missing


def main() -> int:
    if not API_REF.exists():
        print(f"ERROR: {API_REF} 不存在")
        return 1

    api_content = API_REF.read_text(encoding="utf-8")
    all_missing = []

    for module_path in CHECKED_MODULES:
        filepath = SRC_ROOT.parent / module_path if not Path(module_path).is_absolute() else Path(module_path)
        if not filepath.exists():
            filepath = Path(module_path)
        names = extract_public_names(filepath)
        missing = check_api_reference(api_content, names, module_path)
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
