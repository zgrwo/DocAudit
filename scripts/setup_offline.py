"""DocAudit 离线安装脚本（Windows）。

用法:
  setup_offline.bat download [profile]  - 联网下载依赖到 packages/
  setup_offline.bat install  [profile]  - 从本地 packages/ 离线安装

profile: core（默认）| pdf | full
"""

import os
import subprocess
import sys
from pathlib import Path

import common

USAGE = """DocAudit 离线安装脚本（Windows）

用法:
  setup_offline.bat download [profile]  - 联网下载依赖到 packages/
  setup_offline.bat install  [profile]  - 从本地 packages/ 离线安装

profile 选项:
  core  (默认) - PPTX/DOCX/MD 审查
  pdf           - core + PDF 支持
  full          - core + PDF + 开发工具

示例:
  setup_offline.bat download core
  setup_offline.bat install  core
"""

PROFILES = {
    "core": "",
    "pdf": "[pdf]",
    "full": "[all]",
}


def ensure_offline_env() -> None:
    """设置离线红线环境变量（未设置时，在 main() 最先调用）。

    - HF_HUB_OFFLINE=1: 防止 docling 首次运行尝试联网下载模型/词典
    - HF_HUB_CACHE=<项目>/packages/hf_cache: docling 布局模型缓存落在项目内，
      随 packages/ 一起拷贝到离线机器（2026-08 实证: 模型不随 pip 包分发，
      离线 PDF 首转前需在有网机器预下载，见 README「已知限制」）
    """
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    hf_cache = Path(__file__).resolve().parent.parent / "packages" / "hf_cache"
    os.environ.setdefault("HF_HUB_CACHE", str(hf_cache))


def main(argv):
    common.reconfigure_utf8()
    ensure_offline_env()
    print_cmd = "--print-cmd" in argv
    args = [a for a in argv if not a.startswith("--")]

    if not args or args[0] not in ("download", "install"):
        print(USAGE)
        return 0

    action = args[0]
    profile = args[1] if len(args) > 1 else "core"
    if profile not in PROFILES:
        print(f"[错误] 未知 profile: {profile}")
        print()
        print(USAGE)
        return 1
    extras = PROFILES[profile]
    label = profile

    # 引导阶段解释器可能 <3.10，重执行到最佳版本
    if sys.version_info < (3, 10):  # noqa: UP036 — 引导阶段解释器可能 <3.10，降级重执行是刻意设计
        best = common.find_python()
        if best is None:
            print("[X] 未找到 Python 3.10+，请先安装。")
            common.pause()
            return 1
        return subprocess.run([best[0], str(Path(__file__).resolve()), *argv]).returncode

    root = common.project_root()
    packages = common.packages_dir()

    if action == "download":
        return _download(root, packages, extras, label, print_cmd)
    return _install(root, packages, extras, label, print_cmd)


def _download_commands(root, packages, extras, profile):
    """构建下载三步命令（纯函数，便于测试）。

    1. 运行时依赖：优先按锁文件 requirements-<profile>.txt 下载（版本可复现），
       缺失时回退 pyproject 声明解析（附警告）
    2. 构建依赖：显式下载 setuptools/wheel —— pip download 不会保存它们，
       而离线安装本地项目（PEP 517 构建）必需
    3. 离线自检：`pip install --dry-run --ignore-installed --no-index
       --find-links=packages/ ...`，在联网端就暴露 packages/ 不完整的问题

    返回 (commands, warn)。
    """
    lock = root / f"requirements-{profile}.txt"
    if lock.exists():
        dl = [
            sys.executable,
            "-m",
            "pip",
            "download",
            "-r",
            str(lock),
            "-d",
            str(packages),
        ]
        check = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--ignore-installed",
            "--no-index",
            f"--find-links={packages}",
            "-r",
            str(lock),
            str(root),
        ]
        warn = None
    else:
        dl = [
            sys.executable,
            "-m",
            "pip",
            "download",
            f"{root}{extras}",
            "-d",
            str(packages),
        ]
        check = [
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
        warn = (
            f"[警告] 未找到 requirements-{profile}.txt，回退到 pyproject 声明解析（结果不可复现）"
        )
    build = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "setuptools",
        "wheel",
        "-d",
        str(packages),
    ]
    return [dl, build, check], warn


def _download(root, packages, extras, label, print_cmd):
    print(f"[DocAudit] 下载依赖 profile={label} 到 packages/ ...")
    print()
    packages.mkdir(exist_ok=True)
    commands, warn = _download_commands(root, packages, extras, label)
    if warn:
        print(warn)
    if print_cmd:
        print("将执行:")
        for cmd in commands:
            print("  " + " ".join(str(a) for a in cmd))
        return 0
    for idx, cmd in enumerate(commands, start=1):
        if common.run(cmd, cwd=root) != 0:
            if idx == 3:
                print(
                    "[错误] 离线自检失败：packages/ 不完整，"
                    "请勿将其拷贝到离线机器（缺少 wheel 或构建依赖）"
                )
            else:
                print("[错误] 下载失败，请检查网络连接")
            return 1
    print()
    print("========================================")
    print(" 下载完成！packages/ 文件列表:")
    print("========================================")
    for pat in ("*.whl", "*.tar.gz"):
        for p in sorted(packages.glob(pat)):
            print(" ", p.name)
    print()
    print("请将 packages/ 文件夹复制到离线机器的项目根目录,")
    print(f"然后在离线机器上运行: setup_offline.bat install {label}")
    return 0


def _install_upgrade_command(venv_py, packages):
    """构建离线 pip 升级命令 (纯函数): 完全离线红线 — 必须 --no-index 从 packages/ 取 pip wheel。"""
    return [
        venv_py,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "pip",
        "-q",
        "--no-index",
        f"--find-links={packages}",
    ]


def _install(root, packages, extras, label, print_cmd):
    if not packages.exists():
        print("[错误] packages/ 文件夹不存在，请先在有网机器上运行:")
        print("       setup_offline.bat download core")
        return 1
    venv = common.venv_dir()
    venv_py = common.venv_python()

    if not venv_py.exists():
        print("[0/2] 创建虚拟环境...")
        if common.run([sys.executable, "-m", "venv", str(venv)], cwd=root) != 0:
            print("[错误] 创建虚拟环境失败")
            return 1
    else:
        print("[0/2] 虚拟环境已存在")

    print(f"[1/2] 从本地 packages/ 安装依赖 profile={label}...")
    # pip 升级必须离线 (完全离线红线): 从 packages/ 找 pip wheel,
    # 找不到时跳过升级并继续 (现有 pip 可用)
    upg = _install_upgrade_command(venv_py, packages)
    inst = [
        venv_py,
        "-m",
        "pip",
        "install",
        "--no-index",
        f"--find-links={packages}",
        f"{root}{extras}",
    ]
    if print_cmd:
        print("将执行:")
        print("  " + " ".join(str(a) for a in upg))
        print("  " + " ".join(str(a) for a in inst))
        return 0
    if common.run(upg, cwd=root) != 0:
        print("[警告] pip 升级失败 (packages/ 中无 pip wheel 属正常)，使用现有 pip 继续")
    if common.run(inst, cwd=root) != 0:
        print("[错误] 依赖安装失败，请检查 packages/ 中的文件是否完整")
        return 1

    print("[2/2] 验证安装...")
    verify = [
        venv_py,
        "-c",
        "import streamlit; from src.converters import PptxConverter; "
        "from src.auditors import StructureAuditor; print('        核心模块导入成功')",
    ]
    if common.run(verify, cwd=root) != 0:
        print("[警告] 模块导入验证失败")

    print()
    print("========================================")
    print(" 离线安装完成！")
    print("========================================")
    print(" 启动 Web UI:")
    print("   .venv\\Scripts\\streamlit run app.py")
    print()
    print(" CLI 审查:")
    print("   .venv\\Scripts\\python src\\cli.py 文档.pptx")
    print("========================================")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
