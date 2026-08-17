"""scripts/ 工具测试：common.py 工具函数 + setup_offline.py 下载命令构建 + 锁文件生成。

规则:
- `_download_commands()` 是纯函数（不执行 pip），可离线单测
- 锁文件存在时 download 走 `-r requirements-<profile>.txt`；缺失时回退 pyproject 声明
- download 三步：运行时依赖 → 构建依赖（setuptools/wheel）→ 离线 dry-run 自检
"""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import common  # noqa: E402
import setup_offline  # noqa: E402
from gen_requirements_lock import parse_would_install  # noqa: E402

# ── common.py ─────────────────────────────────────────────────────────────

def test_version_tuple():
    assert common._version_tuple("Python 3.12.5") == (3, 12)
    assert common._version_tuple("garbage") is None
    assert common._version_tuple(None) is None


def test_disp_width_cjk_doubled():
    assert common._disp_width("ab") == 2
    assert common._disp_width("审查") == 4
    assert common._disp_width("a审") == 3


def test_run_quiet():
    assert common.run_quiet([sys.executable, "-c", "pass"])
    assert not common.run_quiet([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert not common.run_quiet([sys.executable, "-c", "pass"], cwd=Path("不存在目录"))


def test_common_paths():
    assert common.project_root().name != ""  # scripts/ 的父目录存在
    assert common.packages_dir().name == "packages"
    assert common.venv_dir().name == ".venv"
    assert common.venv_python().name in ("python.exe", "python")


def test_banner(capsys):
    common.banner(["DocAudit"])
    out = capsys.readouterr().out
    assert "DocAudit" in out
    assert out.lstrip().startswith("+")


# ── setup_offline.py ──────────────────────────────────────────────────────

def test_profiles_mapping():
    assert setup_offline.PROFILES == {"core": "", "pdf": "[pdf]", "full": "[all]"}


def test_download_commands_with_lockfile(tmp_path):
    lock = tmp_path / "requirements-core.txt"
    lock.write_text("six==1.17.0\n", encoding="utf-8")
    packages = tmp_path / "packages"

    commands, warn = setup_offline._download_commands(tmp_path, packages, "", "core")

    assert warn is None
    assert len(commands) == 3
    # 1) 运行时依赖按锁文件下载
    dl, build, check = commands
    assert "-r" in dl and str(lock) in dl and "-d" in dl
    # 2) 构建依赖显式下载（pip download 不会保存它们，而离线安装需要）
    assert "setuptools" in build and "wheel" in build
    # 3) 离线 dry-run 自检：从 packages/ 单独解析锁文件 + 项目本身
    assert "--dry-run" in check
    assert "--ignore-installed" in check
    assert "--no-index" in check
    assert f"--find-links={packages}" in check
    assert "-r" in check and str(lock) in check
    assert str(tmp_path) in check


def test_download_commands_fallback_without_lockfile(tmp_path):
    packages = tmp_path / "packages"
    commands, warn = setup_offline._download_commands(tmp_path, packages, "[pdf]", "pdf")

    assert warn is not None and "回退" in warn
    dl, build, check = commands
    assert f"{tmp_path}[pdf]" in dl  # 旧行为：按 pyproject extras 解析
    assert "setuptools" in build and "wheel" in build
    assert "--dry-run" in check and "--no-index" in check


def test_install_upgrade_command_is_offline():
    """回归: 离线安装的 pip 升级必须 --no-index (完全离线红线, 曾联网尝试)"""
    packages = Path("fake/packages")
    cmd = setup_offline._install_upgrade_command("venv-python", packages)
    assert cmd[0] == "venv-python" and "-m" in cmd and "pip" in cmd
    assert "--upgrade" in cmd and "pip" in cmd
    assert "--no-index" in cmd
    assert f"--find-links={packages}" in cmd


# ── gen_requirements_lock.py ──────────────────────────────────────────────

def test_parse_would_install():
    text = (
        "Processing .\\packages\\six-1.17.0-py2.py3-none-any.whl (from x)\n"
        "Would install Jinja2-3.1.6 MarkupSafe-3.0.3 docling-core-2.91.0 "
        "antlr4-python3-runtime-4.9.3 python-dateutil-2.9.0.post0 docaudit-0.1.0\n"
    )
    pinned = parse_would_install(text)
    assert pinned == [
        "antlr4-python3-runtime==4.9.3",
        "docling-core==2.91.0",
        "jinja2==3.1.6",
        "markupsafe==3.0.3",
        "python-dateutil==2.9.0.post0",
    ]  # docaudit 自身被剔除，名称归一化为小写


def test_parse_would_install_empty():
    assert parse_would_install("Processing something\n") == []
