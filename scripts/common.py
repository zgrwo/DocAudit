"""共享工具：DocAudit Windows 启动脚本。

这些脚本必须在项目依赖安装前运行，故本模块只依赖 Python 标准库，
并需兼容 Python 3.8+（引导阶段可能跑在较旧的解释器上）。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def reconfigure_utf8() -> None:
    """让 stdout/stderr 始终以 UTF-8 输出，避免受控制台代码页影响。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def project_root() -> Path:
    """项目根目录（scripts/ 的父目录）。"""
    return Path(__file__).resolve().parent.parent


def packages_dir() -> Path:
    """离线依赖缓存目录。"""
    return Path(__file__).resolve().parent / "packages"


def venv_dir() -> Path:
    return project_root() / ".venv"


def venv_python() -> Path:
    if sys.platform == "win32":
        return venv_dir() / "Scripts" / "python.exe"
    return venv_dir() / "bin" / "python"


def run(cmd, cwd=None) -> int:
    """运行子进程并继承标准输入输出（日志与 Ctrl+C 自然生效）。"""
    return subprocess.run([str(a) for a in cmd], cwd=str(cwd) if cwd else None).returncode


def run_quiet(cmd, cwd=None) -> bool:
    """静默运行子进程，返回是否成功（0 退出码）。"""
    try:
        r = subprocess.run(
            [str(a) for a in cmd],
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def _version_tuple(text: str):
    m = re.search(r"(\d+)\.(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _version_text(exe) -> str:
    try:
        r = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return ((r.stdout or "").strip() + " " + (r.stderr or "").strip()).strip()
    except Exception:
        return ""


def _python_install_bases():
    bases = []
    for env in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            bases.append(
                Path(base) / "Programs" / "Python"
                if env == "LOCALAPPDATA"
                else Path(base) / "Python"
            )
    return bases


def find_python():
    """返回 (python_exe, version_text) 或 None，选择最高版本且 >=3.10 的解释器。

    三级降级策略（比批处理版更稳）：
      1. py 启动器 --list-paths（覆盖所有已装版本，含未入 PATH 的）
      2. PATH 中的 python3 / python
      3. 常见安装路径扫描
    """
    candidates = []

    def consider(exe, ver_text):
        vt = _version_tuple(ver_text)
        if not vt or vt < (3, 10):
            return
        try:
            exe = os.path.abspath(exe)
        except Exception:
            return
        candidates.append((vt, exe))

    # 0. 当前解释器（引导阶段跑进来的那个）
    consider(sys.executable, sys.version)

    # 1. py 启动器：列出所有已装版本
    py = shutil.which("py")
    if py:
        try:
            r = subprocess.run([py, "--list-paths"], capture_output=True, text=True, timeout=15)
            out = (r.stdout or "") + (r.stderr or "")
        except Exception:
            out = ""
        for line in out.splitlines():
            m = re.search(r"-V:(\d+\.\d+)", line)
            if not m:
                continue
            path = line[m.end() :].lstrip("* ").strip()
            if path:
                consider(path, m.group(1))

    # 2. PATH 中的 python3 / python
    for name in ("python3", "python"):
        exe = shutil.which(name)
        if exe:
            consider(exe, _version_text(exe))

    # 3. 常见安装路径
    for base in _python_install_bases():
        for ver in ("313", "312", "311", "310"):
            exe = base / ("Python" + ver) / "python.exe"
            if exe.exists():
                consider(str(exe), _version_text(str(exe)))

    if not candidates:
        return None

    best = {}
    for vt, exe in candidates:
        key = os.path.normcase(exe)
        if key not in best or vt > best[key][0]:
            best[key] = (vt, exe)
    vt, exe = max(best.values(), key=lambda x: x[0])
    return (exe, _version_text(exe) or f"{vt[0]}.{vt[1]}")


def pause(prompt="\n按回车键退出...") -> None:
    try:
        input(prompt)
    except EOFError:
        pass


def _disp_width(s: str) -> int:
    w = 0
    for ch in s:
        w += 2 if ord(ch) > 0x2E80 else 1
    return w


def banner(lines) -> None:
    """打印一个简单方框横幅（按东亚字符宽度对齐）。"""
    width = max(30, max(_disp_width(line) for line in lines) + 2)
    print()
    print("+" + "=" * width + "+")
    for line in lines:
        print("| " + line + " " * (width - _disp_width(line) - 1) + "|")
    print("+" + "=" * width + "+")
    print()


def set_console_title(title: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(title)
        except Exception:
            pass  # bare-handler-ok — 控制台标题尽力而为，失败不影响功能
