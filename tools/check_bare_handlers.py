"""CI 验证脚本：裸异常处理器检查（AST 感知）。

规则:
- `except:`（裸捕获）→ 违规（无条件禁止，不可豁免）
- `except BaseException` → 违规（会吞掉 KeyboardInterrupt / SystemExit，不可豁免）
- `except Exception`（含 `as e`）体为空或只有 `pass` → 违规，
  除非附 `# bare-handler-ok` 注释（刻意的降级路径须附理由）
- 具体异常类型（ValueError / yaml.YAMLError / (A, B) 元组）→ 放行
- 处理器体内有 return / raise / 调用 / 赋值 / 日志等语句 → 放行（视为已处理）；
  其中"赋值降级"（如 `x = None`）属已处理，但仍建议附 `# bare-handler-ok — 理由`
  说明刻意降级意图，便于后续读者理解

豁免标记位置：`# bare-handler-ok` 可出现在 except 语句**上一行**到最后一个
body 语句行之间的任意行（含 except 上一行——常见的「# 降级」注释写在 except
之前的习惯也被识别）。

与裸 grep 不同：AST 解析天然跳过 docstring / 注释中的教学文字（
如「禁止写 `except:`」这类反例），不会误报。

退出码 0 = 通过，1 = 存在违规。
"""

import ast
import sys
from pathlib import Path

NOQA_MARKER = "# bare-handler-ok"
EXCLUDED_DIRS = {
    ".venv",
    "build",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "logs",
    ".qoder",
}


def iter_py_files(scope: Path) -> list[Path]:
    """返回作用域内待检查的 .py 文件（文件参数直接返回，目录递归且排除生成目录）。"""
    if scope.is_file():
        return [scope] if scope.suffix == ".py" else []
    return [p for p in scope.rglob("*.py") if not any(part in EXCLUDED_DIRS for part in p.parts)]


def check_file(path: Path) -> list[str]:
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

        # noqa 标记可出现在 except 语句上一行 到 最后一个 body 语句行 之间的任意行
        # (含 except 上一行 — 常见的「# 降级」注释写在 except 之前的习惯, 2026-08 P1 修复)
        end_line = node.body[-1].end_lineno if node.body else node.lineno
        start = max(0, node.lineno - 2)  # 含 except 上一行 (0-indexed)
        window = lines[start:end_line]
        if any(NOQA_MARKER in line for line in window):
            continue
        findings.append(
            f"{path}:{node.lineno}: except Exception 静默吞异常（体为空/仅 pass）；"
            f"若为刻意的降级路径，请在 except 行附 '{NOQA_MARKER} — 理由'"
        )
    return findings


def main(argv: list[str]) -> int:
    if argv:
        scopes = [Path(a) for a in argv]
    else:
        scopes = [Path.cwd()]

    all_findings: list[str] = []
    for scope in scopes:
        if not scope.exists():
            print(f"ERROR: 路径不存在: {scope}")
            return 1
        for py_file in iter_py_files(scope):
            all_findings.extend(check_file(py_file))

    if all_findings:
        print("裸异常处理器检查失败:")
        for f in all_findings:
            print(f"  - {f}")
        print(f"\n共 {len(all_findings)} 处违规。")
        return 1
    print("check_bare_handlers passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
