"""DocAudit 手动安装脚本（Windows）：创建虚拟环境并安装全部依赖，不启动 Web。"""

import subprocess
import sys

import common


def main():
    common.reconfigure_utf8()
    common.set_console_title("DocAudit — 手动安装")

    root = common.project_root()
    venv = common.venv_dir()
    venv_py = common.venv_python()

    if sys.version_info < (3, 10):
        best = common.find_python()
        if best is None:
            print("[X] 未找到 Python 3.10+，请先从 https://www.python.org/downloads/ 安装。")
            common.pause()
            return 1
        return subprocess.run([best[0], str(__file__)]).returncode

    print("[1/3] 创建虚拟环境...")
    if not venv_py.exists():
        if common.run([sys.executable, "-m", "venv", str(venv)], cwd=root) != 0:
            print("[X] 创建虚拟环境失败")
            common.pause()
            return 1
        print("  [OK] 已创建 .venv")
    else:
        print("  [OK] .venv 已存在")

    print("[2/3] 安装依赖（约需 1-3 分钟）...")
    common.run([venv_py, "-m", "pip", "install", "--upgrade", "pip", "-q"], cwd=root)
    if common.run([venv_py, "-m", "pip", "install", f"{root}[all]", "-q"], cwd=root) != 0:
        print("[X] 依赖安装失败，请检查网络连接后重试")
        common.pause()
        return 1
    print("  [OK] 依赖安装完成")

    print("[3/3] 验证安装...")
    verify = [
        venv_py, "-c",
        "import streamlit; from src.converters import PptxConverter; "
        "from src.auditors import StructureAuditor; print('  [OK] 核心模块导入成功')",
    ]
    if common.run(verify, cwd=root) != 0:
        print("[警告] 模块导入验证失败")

    print()
    print("安装完成！下一步:")
    print("  启动 Web UI:   .venv\\Scripts\\streamlit run app.py")
    print("  或直接运行:    scripts\\run.bat")
    print()
    print("  启动 LanguageTool (可选): docker-compose up -d")
    common.pause()
    return 0


if __name__ == "__main__":
    sys.exit(main())
