"""发行自检 — 版本 / CHANGELOG / 必备文件 / CLI 版本一致性（离线，无网络）。

用途：在打 tag 前用一条命令确认"发行标准"里可机器判定的部分，避免版本双源
漂移、CHANGELOG 忘记改发行头、必备文档缺失等低级问题。

用法:
    python scripts/check_release.py                     # 按发行标准检查
    python scripts/check_release.py --allow-unreleased  # 开发期（允许 [Unreleased]）
    python scripts/check_release.py --require-tag       # 要求 vX.Y.Z tag 已存在
    python scripts/check_release.py --json              # 机器可读输出

退出码: 0 = 全部通过；1 = 存在失败项（逐条 [FAIL]）。
完整人工检查项见 docs/governance/release-checklist.md。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "rules.md",
    "app.py",
    "glossary/semiconductor_core.yaml",
    "vocab/accept.txt",
    "docs/specification/api-reference.md",
    "docs/user-manual/user-manual.md",
    "docs/governance/release-checklist.md",
    "MANIFEST.in",
)


def _read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def pyproject_version(root: Path = ROOT) -> str | None:
    m = re.search(r'^version\s*=\s*"([^"]+)"', _read(root / "pyproject.toml"), re.MULTILINE)
    return m.group(1) if m else None


def module_version(root: Path = ROOT) -> str | None:
    m = re.search(
        r'^__version__\s*=\s*"([^"]+)"', _read(root / "src" / "__init__.py"), re.MULTILINE
    )
    return m.group(1) if m else None


def check_version_sync(root: Path = ROOT) -> tuple[bool, str]:
    py_v, mod_v = pyproject_version(root), module_version(root)
    if not py_v or not mod_v:
        return False, f"版本号缺失: pyproject={py_v} src.__version__={mod_v}"
    if not re.fullmatch(r"\d+\.\d+\.\d+", py_v):
        return False, f"pyproject 版本号非语义化: {py_v}"
    if py_v != mod_v:
        return False, f"版本双源不一致: pyproject={py_v} vs src.__version__={mod_v}"
    return True, f"版本 {py_v} 双源一致"


def check_changelog(
    version: str, root: Path = ROOT, allow_unreleased: bool = False
) -> tuple[bool, str]:
    text = _read(root / "CHANGELOG.md")
    first = re.search(r"^## \[([^\]]+)\]", text, re.MULTILINE)
    if not first:
        return False, "CHANGELOG 缺少 `## [版本]` 段"
    first_name = first.group(1)
    if first_name == "Unreleased":
        if allow_unreleased:
            return True, "CHANGELOG 为 [Unreleased]（--allow-unreleased）"
        return False, "CHANGELOG 仍是 [Unreleased]：发行前需改为 `## [版本] - 日期`"
    if first_name != version:
        return False, f"CHANGELOG 最上方段是 [{first_name}]，应为 [{version}]"
    return True, f"CHANGELOG 发行段 [{version}] 就位"


def check_required_files(root: Path = ROOT) -> tuple[bool, str]:
    missing = [rel for rel in REQUIRED_FILES if not (root / rel).exists()]
    if missing:
        return False, f"缺少必备文件: {', '.join(missing)}"
    return True, f"必备文件齐全 ({len(REQUIRED_FILES)} 个)"


def check_cli_version(version: str, root: Path = ROOT) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [sys.executable, str(root / "src" / "cli.py"), "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(root),
        )
    except OSError as e:
        return False, f"无法执行 CLI: {e}"
    output = (result.stdout or "").strip()
    expected = f"DocAudit {version}"
    if result.returncode != 0 or output != expected:
        return (
            False,
            f"`--version` 输出异常: rc={result.returncode} out={output!r}（期望 {expected!r}）",
        )
    return True, f"CLI --version → {expected}"


def check_git_tag(version: str, root: Path = ROOT) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"v{version}"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(root),
        )
    except OSError as e:
        return False, f"无法执行 git: {e}"
    if result.returncode != 0:
        return False, f"tag v{version} 不存在（git tag v{version}）"
    return True, f"tag v{version} 已存在"


def run_checks(
    root: Path = ROOT,
    allow_unreleased: bool = False,
    require_tag: bool = False,
) -> list[dict]:
    version = pyproject_version(root) or "0.0.0"
    checks = [
        ("version_sync", check_version_sync(root)),
        ("changelog", check_changelog(version, root, allow_unreleased)),
        ("required_files", check_required_files(root)),
        ("lock_cache", check_lock_cache(root)),
        ("cli_version", check_cli_version(version, root)),
    ]
    if require_tag:
        checks.append(("git_tag", check_git_tag(version, root)))
    return [{"id": cid, "ok": ok, "detail": detail} for cid, (ok, detail) in checks]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DocAudit 发行自检")
    parser.add_argument(
        "--allow-unreleased", action="store_true", help="允许 CHANGELOG 为 [Unreleased]"
    )
    parser.add_argument("--require-tag", action="store_true", help="要求 vX.Y.Z tag 已存在")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    results = run_checks(allow_unreleased=args.allow_unreleased, require_tag=args.require_tag)
    failed = [r for r in results if not r["ok"]]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("[RELEASE] DocAudit 发行自检")
        for row in results:
            print(f"  [{'PASS' if row['ok'] else 'FAIL'}] {row['id']}: {row['detail']}")
        print(f"[RELEASE] {'OK' if not failed else f'FAILED — {len(failed)} 项未通过'}")
    return 0 if not failed else 1


def _normalized_package(name: str) -> str:
    """PEP 503 名称归一化（大小写/`_`/`.` → `-`）。"""
    return re.sub(r"[-_.]+", "-", name).lower()


def _cache_has(packages: Path, name: str, version: str) -> bool:
    """packages/ 中是否存在 name==version 的 wheel/sdist（文件名前缀匹配）。

    注意：只归一化**包名**部分，版本号里的点必须保留（否则 1.15.0 → 1-15-0 永远匹配不上）。
    """
    target = _normalized_package(name) + "-" + version.lower()
    for path in packages.iterdir():
        if not path.is_file():
            continue
        # wheel/sdist 文件名中的包名常用下划线（python_dotenv），版本号保持原样
        filename = path.name.lower().replace("_", "-")
        if not filename.startswith(target):
            continue
        rest = filename[len(target) :]
        if not rest or rest[0] in "-.":
            return True
    return False


def check_lock_cache(root: Path = ROOT) -> tuple[bool, str]:
    """锁文件每个 pin 必须在离线缓存 packages/ 中存在（防"锁文件声称、离线装不了"）。

    2026-11 审查发现：requirements-*.txt 有 15 个版本不在 packages/，离线安装会失败。
    packages/ 不存在时（CI / 干净 clone）跳过该项。
    """
    packages = root / "packages"
    if not packages.is_dir():
        return True, "跳过（无离线缓存 packages/，CI 环境不适用）"
    missing: list[str] = []
    total = 0
    for profile in ("core", "pdf", "full"):
        lock = root / f"requirements-{profile}.txt"
        if not lock.exists():
            continue
        for line in lock.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"^([A-Za-z0-9_.-]+)==([^;\s]+)", line)
            if not match:
                continue
            total += 1
            name, version = match.group(1), match.group(2)
            if not _cache_has(packages, name, version):
                missing.append(f"{name}=={version}")
    if missing:
        preview = ", ".join(sorted(set(missing))[:5])
        return (
            False,
            f"{len(set(missing))} 个 pin 不在 packages/（离线安装会失败）: {preview}",
        )
    return True, f"锁文件 {total} 个 pin 均命中离线缓存 packages/"


if __name__ == "__main__":
    sys.exit(main())
