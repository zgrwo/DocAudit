"""DocAudit 一键启动脚本（Windows）。

用法:
  run.bat             - 检测环境 -> 准备虚拟环境 -> 安装依赖 -> 启动 Web
  run.bat --check     - 只做健康检查，不启动 Web
"""

import subprocess
import sys
from pathlib import Path

import common


def main(argv):
    common.reconfigure_utf8()
    root = common.project_root()
    venv = common.venv_dir()
    venv_py = common.venv_python()
    check_only = "--check" in argv

    common.set_console_title("DocAudit — 本地离线文档审查系统")
    common.banner(["DocAudit — 本地离线文档审查系统", "一键启动脚本 v1.0"])

    # ---- 1. 检测 Python 3.10+ ----
    print("  [1] 检测 Python 环境...")
    if sys.version_info < (3, 10):  # noqa: UP036 — 引导阶段解释器可能 <3.10，降级重执行是刻意设计
        best = common.find_python()
        if best is None:
            print("  [X] 未找到 Python 3.10+")
            print()
            print("      请从 https://www.python.org/downloads/ 下载安装 Python 3.10+")
            print("      安装时请勾选 \"Add Python to PATH\" 选项")
            print()
            print("      如已安装但未被检测到，请将 Python 加入系统 PATH 后重试")
            common.pause()
            return 1
        exe, ver = best
        print(f"  [..] 使用 Python {ver} 重新启动...")
        return subprocess.run([exe, str(Path(__file__).resolve()), *argv]).returncode
    print(f"  [OK] 找到 Python {sys.version.split()[0]}")

    # ---- 2. 准备虚拟环境 ----
    print("  [2] 准备虚拟环境...")
    if not venv_py.exists():
        print("        首次运行，正在创建虚拟环境...")
        if common.run([sys.executable, "-m", "venv", str(venv), "--clear"], cwd=root) != 0:
            print("  [X] 虚拟环境创建失败，请检查磁盘空间和权限")
            common.pause()
            return 1
        print("  [OK] 虚拟环境创建成功")
    else:
        print("  [OK] 虚拟环境已就绪")

    # ---- 3. 检查依赖 ----
    print("  [3] 检查依赖...")
    deps_ok = common.run_quiet([venv_py, "-c", "import streamlit"], cwd=root)
    if check_only:
        if deps_ok:
            print("  [OK] 依赖已安装")
        else:
            print("  [..] 依赖未安装（正式运行 run.bat 时会自动安装）")
        print()
        print("  [OK] 环境检查通过。")
        return 0
    if not deps_ok:
        print("        正在安装 DocAudit 及全部依赖 约需 1-3 分钟...")
        common.run([venv_py, "-m", "pip", "install", "--upgrade", "pip", "-q"], cwd=root)
        if common.run([venv_py, "-m", "pip", "install", f"{root}[all]", "-q"], cwd=root) != 0:
            print("  [X] 依赖安装失败，请检查网络连接后重试")
            common.pause()
            return 1
        print("  [OK] 依赖安装完成")
    else:
        print("  [OK] 依赖已安装")

    # ---- 启动 Web UI ----
    print()
    print("  [启动] 启动 Web 界面...")
    common.banner(
        [
            "浏览器将自动打开 http://127.0.0.1:8501",
            "上传文档 → 点击审查 → 查看结果",
            "按 Ctrl+C 或关闭此窗口停止服务",
        ]
    )
    common.run([venv_py, "-m", "streamlit", "run", str(root / "app.py")], cwd=root)
    print()
    print("  DocAudit 已停止。")
    common.pause()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
