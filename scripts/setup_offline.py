"""DocAudit 离线安装脚本（Windows）。

用法:
  setup_offline.bat download [profile]  - 联网下载依赖到 packages/
  setup_offline.bat install  [profile]  - 从本地 packages/ 离线安装

profile: core（默认）| pdf | full
"""

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


def main(argv):
    common.reconfigure_utf8()
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
    if sys.version_info < (3, 10):
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


def _download(root, packages, extras, label, print_cmd):
    print(f"[DocAudit] 下载依赖 profile={label} 到 packages/ ...")
    print()
    packages.mkdir(exist_ok=True)
    cmd = [
        sys.executable, "-m", "pip", "download",
        f"{root}{extras}", "-d", str(packages),
    ]
    if print_cmd:
        print("将执行:")
        print("  " + " ".join(str(a) for a in cmd))
        return 0
    if common.run(cmd, cwd=root) != 0:
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
    upg = [venv_py, "-m", "pip", "install", "--upgrade", "pip", "-q"]
    inst = [
        venv_py, "-m", "pip", "install",
        "--no-index", f"--find-links={packages}", f"{root}{extras}",
    ]
    if print_cmd:
        print("将执行:")
        print("  " + " ".join(str(a) for a in upg))
        print("  " + " ".join(str(a) for a in inst))
        return 0
    common.run(upg, cwd=root)
    if common.run(inst, cwd=root) != 0:
        print("[错误] 依赖安装失败，请检查 packages/ 中的文件是否完整")
        return 1

    print("[2/2] 验证安装...")
    verify = [
        venv_py, "-c",
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
