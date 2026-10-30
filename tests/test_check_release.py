import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_release  # noqa: E402


def _make_fake_root(tmp_path: Path, *, version="0.2.0", changelog_header="## [0.2.0] - 2026-10-29"):
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nversion = "{version}"\n', encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (tmp_path / "src" / "cli.py").write_text(f'print("DocAudit {version}")\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        f"# Changelog\n\n{changelog_header}\n\n## [0.1.0] - 2026-07-26\n", encoding="utf-8"
    )
    for rel in ("README.md", "LICENSE", "rules.md", "app.py", "MANIFEST.in"):
        (tmp_path / rel).write_text("x", encoding="utf-8")
    (tmp_path / "glossary").mkdir()
    (tmp_path / "glossary" / "semiconductor_core.yaml").write_text("terms: []\n", encoding="utf-8")
    (tmp_path / "vocab").mkdir()
    (tmp_path / "vocab" / "accept.txt").write_text("x\n", encoding="utf-8")
    (tmp_path / "docs" / "specification").mkdir(parents=True)
    (tmp_path / "docs" / "specification" / "api-reference.md").write_text("x", encoding="utf-8")
    (tmp_path / "docs" / "governance").mkdir(parents=True)
    (tmp_path / "docs" / "governance" / "release-checklist.md").write_text("x", encoding="utf-8")
    (tmp_path / "docs" / "user-manual").mkdir(parents=True)
    (tmp_path / "docs" / "user-manual" / "user-manual.md").write_text("x", encoding="utf-8")
    return tmp_path


class TestCheckRelease:
    def test_fake_root_all_pass(self, tmp_path):
        root = _make_fake_root(tmp_path)
        results = check_release.run_checks(root=root)
        assert all(r["ok"] for r in results), results

    def test_version_mismatch_fails(self, tmp_path):
        root = _make_fake_root(tmp_path)
        (root / "src" / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
        ok, detail = check_release.check_version_sync(root)
        assert not ok
        assert "不一致" in detail

    def test_unreleased_requires_flag(self, tmp_path):
        root = _make_fake_root(tmp_path, changelog_header="## [Unreleased]")
        ok, _ = check_release.check_changelog("0.2.0", root, allow_unreleased=False)
        assert not ok
        ok, _ = check_release.check_changelog("0.2.0", root, allow_unreleased=True)
        assert ok

    def test_wrong_changelog_version_fails(self, tmp_path):
        root = _make_fake_root(tmp_path, changelog_header="## [0.1.0]")
        ok, detail = check_release.check_changelog("0.2.0", root)
        assert not ok
        assert "0.1.0" in detail

    def test_missing_required_file_fails(self, tmp_path):
        root = _make_fake_root(tmp_path)
        (root / "LICENSE").unlink()
        ok, detail = check_release.check_required_files(root)
        assert not ok
        assert "LICENSE" in detail

    def test_cli_version_mismatch_fails(self, tmp_path):
        root = _make_fake_root(tmp_path)
        (root / "src" / "cli.py").write_text('print("DocAudit 1.0.0")\n', encoding="utf-8")
        ok, _ = check_release.check_cli_version("0.2.0", root)
        assert not ok

    def test_current_repo_passes_release_checks(self):
        """真实仓库：版本同步 / CHANGELOG 发行头 / 必备文件 / CLI --version 全通过。"""
        results = check_release.run_checks()
        failed = [r for r in results if not r["ok"]]
        assert not failed, failed

    def test_main_json_and_exit_code(self, capsys):
        code = check_release.main(["--json"])
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert {row["id"] for row in data} >= {"version_sync", "changelog", "required_files"}


def test_release_checklist_documented():
    """发行标准文档存在且被 docs 索引引用（SSOT 可发现）。"""
    checklist = ROOT / "docs" / "governance" / "release-checklist.md"
    assert checklist.exists()
    index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert "release-checklist.md" in index


class TestLockCacheIntegrity:
    """2026-11 审查：锁文件 pin 必须存在于离线缓存（离线安装可执行）。"""

    @staticmethod
    def _pin(path: Path, lines: list[str]) -> None:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_missing_cache_is_skipped(self, tmp_path):
        ok, detail = check_release.check_lock_cache(tmp_path)
        assert ok and "跳过" in detail

    def test_all_pins_present_passes(self, tmp_path):
        packages = tmp_path / "packages"
        packages.mkdir()
        (packages / "demo_pkg-1.2.3-py3-none-any.whl").write_bytes(b"")
        self._pin(tmp_path / "requirements-core.txt", ["demo-pkg==1.2.3"])
        ok, detail = check_release.check_lock_cache(tmp_path)
        assert ok, detail
        assert "命中" in detail

    def test_version_dots_are_not_normalized(self, tmp_path):
        """1.15.0 不能被归一化成 1-15-0（历史 bug 回归）。"""
        packages = tmp_path / "packages"
        packages.mkdir()
        (packages / "accelerate-1.15.0-py3-none-any.whl").write_bytes(b"")
        self._pin(tmp_path / "requirements-full.txt", ["accelerate==1.15.0"])
        ok, detail = check_release.check_lock_cache(tmp_path)
        assert ok, detail

    def test_missing_pin_fails_with_preview(self, tmp_path):
        packages = tmp_path / "packages"
        packages.mkdir()
        self._pin(tmp_path / "requirements-pdf.txt", ["demo-pkg==9.9.9"])
        ok, detail = check_release.check_lock_cache(tmp_path)
        assert not ok
        assert "demo-pkg==9.9.9" in detail

    def test_project_cache_is_complete(self):
        """当前仓库：packages/ 存在时全部 pin 必须命中（防止锁文件/缓存再次漂移）。"""
        ok, detail = check_release.check_lock_cache(ROOT)
        assert ok, detail
