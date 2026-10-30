"""scripts/ 工具测试：common.py 工具函数 + setup_offline.py 下载命令构建 + 锁文件生成。

规则:
- `_download_commands()` 是纯函数（不执行 pip），可离线单测
- 锁文件存在时 download 走 `-r requirements-<profile>.txt`；缺失时回退 pyproject 声明
- download 三步：运行时依赖 → 构建依赖（setuptools/wheel）→ 离线 dry-run 自检
"""

import os
import re
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


def test_packages_dir_prefers_project_root(tmp_path):
    """离线依赖缓存目录: 优先项目根 packages/, 兼容旧 scripts/packages (2026-11 审查)

    README/setup_offline 提示"把 packages/ 复制到项目根目录", HF 模型缓存也在
    <项目根>/packages/hf_cache; 旧实现把 wheel 下到 scripts/packages 与说明不符。
    """
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    legacy = scripts / "packages"
    legacy.mkdir()
    # 根目录尚未存在 + 旧位置存在 → 沿用旧位置（不让历史下载失效）
    assert common._packages_dir_for(tmp_path, scripts) == legacy
    # 根目录出现后优先根目录
    root_packages = tmp_path / "packages"
    root_packages.mkdir()
    assert common._packages_dir_for(tmp_path, scripts) == root_packages
    # 两处都不存在 → 默认项目根（新建目录在此）
    empty = tmp_path / "empty"
    empty.mkdir()
    assert common._packages_dir_for(empty, empty / "scripts") == empty / "packages"


def test_offline_scripts_share_packages_semantics():
    """setup_offline.sh 与 common.packages_dir() 的缓存位置语义必须一致 (双轨制)。"""
    sh = (SCRIPTS / "setup_offline.sh").read_text(encoding="utf-8")
    assert 'PACKAGES_DIR="$PROJECT_DIR/packages"' in sh
    assert 'if [ ! -d "$PACKAGES_DIR" ] && [ -d "$SCRIPT_DIR/packages" ]' in sh


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


def test_ensure_offline_env_sets_hf_hub_offline(monkeypatch):
    """离线红线: 下载/安装的 pip 子进程必须携带 HF_HUB_OFFLINE=1 (防 docling 首次运行联网)。"""
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    setup_offline.ensure_offline_env()
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    # setdefault 语义: 用户已显式设置时保持原值
    os.environ["HF_HUB_OFFLINE"] = "0"
    setup_offline.ensure_offline_env()
    assert os.environ.get("HF_HUB_OFFLINE") == "0"


def test_ensure_offline_env_sets_hf_hub_cache(monkeypatch):
    """离线红线: HF_HUB_CACHE 必须指向项目内 packages/hf_cache。

    docling 布局模型不随包分发 (2026-08 实证: 需从 HuggingFace Hub 下载)，
    缓存必须落在项目内才能随 packages/ 一起拷贝到离线机器。
    """
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    setup_offline.ensure_offline_env()
    cache = os.environ.get("HF_HUB_CACHE", "")
    assert "packages" in cache and "hf_cache" in cache, (
        f"HF_HUB_CACHE 应指向项目内 packages/hf_cache: {cache}"
    )
    # setdefault 语义: 用户已显式设置时保持原值
    os.environ["HF_HUB_CACHE"] = "/custom/cache"
    setup_offline.ensure_offline_env()
    assert os.environ["HF_HUB_CACHE"] == "/custom/cache"


def test_main_sets_offline_env(monkeypatch, tmp_path):
    """main() 必须在任何子进程执行前设置离线环境，download 与 install 两条路径均覆盖。"""
    calls = []
    monkeypatch.setattr(setup_offline, "ensure_offline_env", lambda: calls.append(1))
    packages = tmp_path / "packages"
    packages.mkdir()
    monkeypatch.setattr(setup_offline.common, "packages_dir", lambda: packages)
    assert setup_offline.main(["download", "core", "--print-cmd"]) == 0
    assert setup_offline.main(["install", "core", "--print-cmd"]) == 0
    assert len(calls) == 2


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


def test_shell_scripts_use_project_root_semantics():
    """2026-09-06 r5 审查 F-01/F-02/F-03: .sh 三件套必须项目根语义 + venv 绝对路径。

    install.sh 曾 `pip install "$SCRIPT_DIR[all]"` 指向 scripts/ 自身（无 pyproject
    必失败），且相对 `.venv` + 裸 pip 有 CWD 强依赖 — 静态断言防「脚本双轨制失配」
    同族复发（tooling-pitfalls ⑪）。
    """
    for name in ("install.sh", "run.sh", "setup_offline.sh"):
        content = (SCRIPTS / name).read_text(encoding="utf-8")
        # 只检查执行行 — 注释中的历史模式引用（如修复说明）不参与断言
        code = "\n".join(line for line in content.splitlines() if not line.lstrip().startswith("#"))
        assert re.search(r'PROJECT_DIR="\$\(cd .*&& pwd\)"', content), (
            f"{name}: 必须从脚本位置派生项目根 PROJECT_DIR"
        )
        assert "$SCRIPT_DIR[all]" not in code and "$SCRIPT_DIR$EXTRAS" not in code, (
            f"{name}: 不得以 scripts/ 自身作为 pip 安装目标"
        )
        assert "venv .venv" not in code, (
            f"{name}: venv 必须经 $VENV_DIR 绝对路径创建（相对路径有 CWD 强依赖）"
        )
        # 行首直接 source 相对 venv 才算执行行; echo 提示文本（用户在项目根执行
        # 的操作指引）合法含 "source .venv/bin/activate" 字样
        assert not re.search(r"^\s*source \.venv", code, re.MULTILINE), (
            f"{name}: 不得 source 相对路径 venv（执行行须用 $VENV_DIR）"
        )


# ── benchmark.py（性能基线脚本）────────────────────────────────


def test_benchmark_generates_and_measures():
    import benchmark

    results = benchmark.run_benchmark(sizes=[2], formats=("docx",), with_html=False)
    assert len(results) == 1
    row = results[0]
    assert row["format"] == "docx"
    assert row["pages"] == 2
    assert row["convert_s"] >= 0.0
    assert row["findings"] >= 0
    assert row["bytes"] > 0


def test_benchmark_main_writes_json(tmp_path, capsys):
    import json

    import benchmark

    out = tmp_path / "bench.json"
    code = benchmark.main(["--sizes", "2", "--format", "docx", "--json", str(out), "--no-html"])
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data and data[0]["format"] == "docx"
    assert "[BENCH] JSON 已写入" in capsys.readouterr().out


def test_benchmark_invalid_sizes_exits_2(capsys):
    import benchmark

    assert benchmark.main(["--sizes", "a,b"]) == 2


# ── .pre-commit-config.yaml 契约 ───────────────────────────────


def _pre_commit_config() -> dict:
    import yaml

    path = SCRIPTS.parent / ".pre-commit-config.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_pre_commit_hooks_present():
    config = _pre_commit_config()
    hook_ids = [h["id"] for repo in config["repos"] for h in repo["hooks"]]
    assert "ruff-check" in hook_ids
    assert "ruff-format" in hook_ids
    assert "docaudit-rules-validate" in hook_ids
    assert "docaudit-fast-tests" in hook_ids


def test_pre_commit_fast_tests_on_pre_push():
    """快测 ~40s：放 pre-push，避免每次 commit 都等；commit 只做 lint + 配置校验。"""
    config = _pre_commit_config()
    hooks = {h["id"]: h for repo in config["repos"] for h in repo["hooks"]}
    assert hooks["docaudit-fast-tests"]["stages"] == ["pre-push"]
    assert "stages" not in hooks["docaudit-rules-validate"]


def test_pre_commit_ruff_version_matches_pyproject():
    """pre-commit 的 ruff rev 必须与 pyproject 钉版一致，避免 format 漂移。"""
    from pathlib import Path

    config = _pre_commit_config()
    revs = [repo.get("rev") for repo in config["repos"] if "ruff" in repo.get("repo", "")]
    assert revs and all(r == "v0.16.3" for r in revs), revs
    pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert "ruff==0.16.3" in pyproject or "ruff== 0.16.3" in pyproject
