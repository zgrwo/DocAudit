"""从本地 packages/ 离线解析生成 requirements-<profile>.txt 锁定文件。

用法:
  python scripts/gen_requirements_lock.py

原理:
  对每个 profile（core/pdf/full）运行
    pip install --dry-run --ignore-installed --no-index --find-links=packages <项目>[extras]
  解析输出中的 "Would install ..." 列表（名称-版本 形式），生成钉死版本的
  requirements-<profile>.txt。解析完全离线、基于 packages/ 目录的当前内容，
  保证下载步骤与安装步骤使用同一份版本集合。

何时重新生成:
  - 修改 pyproject.toml 依赖声明后
  - 升级 packages/ 目录后（重新 download 后）

输出文件被 scripts/setup_offline.py / setup_offline.sh 的 download 步骤使用。
"""

import re
import subprocess
import sys
from pathlib import Path

PROFILES = {"core": "", "pdf": "[pdf]", "full": "[all]"}
TOKEN_RE = re.compile(r"^(?P<name>.+)-(?P<ver>\d[0-9A-Za-z.+\-]*)$")
SKIP_PROJECTS = {"docaudit"}  # 项目自身由源码目录安装，不进入锁文件

HEADER = """# DocAudit 离线依赖锁定文件（profile={profile}）
# 由 scripts/gen_requirements_lock.py 生成，请勿手改。
# 重新生成: python scripts/gen_requirements_lock.py
"""


def parse_would_install(text: str) -> list[str]:
    """从 pip --dry-run 输出中解析 'Would install Name-Version ...' 列表。

    返回排序去重的 `name==version` 钉死列表；项目自身（docaudit）被剔除。
    """
    lines = [line for line in text.splitlines() if line.startswith("Would install")]
    if not lines:
        return []
    pinned = set()
    for token in lines[-1].split()[2:]:  # 去掉 "Would install"
        m = TOKEN_RE.match(token)
        if not m:
            continue
        name = m.group("name").lower()
        if name in SKIP_PROJECTS:
            continue
        pinned.add(f"{name}=={m.group('ver')}")
    return sorted(pinned)


def resolve_profile(root: Path, packages: Path, extras: str) -> list[str]:
    """离线 dry-run 解析一个 profile，返回钉死依赖列表。"""
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--dry-run",
        "--ignore-installed",
        "--no-index",
        f"--find-links={packages}",
        f"{root}{extras}",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[FAIL] profile 解析失败 (exit={r.returncode})")
        print(r.stderr[-2000:])
        sys.exit(1)
    return parse_would_install(r.stdout)


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    packages = root / "scripts" / "packages"
    if not packages.is_dir():
        print(f"[错误] packages/ 目录不存在: {packages}")
        print("       请先运行 setup_offline download 生成依赖缓存。")
        return 1

    for profile, extras in PROFILES.items():
        pinned = resolve_profile(root, packages, extras)
        out = root / f"requirements-{profile}.txt"
        content = HEADER.format(profile=profile) + "\n".join(pinned) + "\n"
        out.write_text(content, encoding="utf-8")
        print(f"[OK] {out.name}: {len(pinned)} 个依赖")
    print("完成。重新生成 setup_offline 后即可用锁文件下载。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
