"""CLI main() 进程内测试 — 提升 cli.py 覆盖率（subprocess 测试不计入 coverage）。

2026-10-29: subprocess 用例（test_cli_exit_codes / test_report_workflow 的 CLI 类）
验证的是真实进程行为，但不产生覆盖率；本文件用 monkeypatch sys.argv + 捕获
SystemExit 的方式覆盖 main() 的分支，两者互补。
"""

import json
import sys
from pathlib import Path

import pytest

from src.cli import main

pytestmark = pytest.mark.slow  # 端到端/子进程用例：pre-commit 快测跳过

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULES = str(PROJECT_ROOT / "rules.md")


def _run_main(monkeypatch, *argv: str) -> int:
    """进程内调用 main()，返回退出码（SystemExit.code 为 None 视作 0）。"""
    monkeypatch.setattr(sys, "argv", ["docaudit", *argv])
    with pytest.raises(SystemExit) as exc:
        main()
    code = exc.value.code
    return 0 if code is None else int(code)


def _write_md(path: Path, text: str = "# 标题\n\n这是正文内容。\n") -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TestMainUsage:
    def test_no_args_prints_help_exit_0(self, monkeypatch):
        assert _run_main(monkeypatch) == 0

    def test_unknown_option_exits_2(self, monkeypatch):
        assert _run_main(monkeypatch, "--no-such-flag") == 2

    def test_unsupported_output_suffix_exits_2(self, monkeypatch, tmp_path):
        src = _write_md(tmp_path / "a.md")
        assert _run_main(monkeypatch, str(src), "-o", str(tmp_path / "r.txt")) == 2

    def test_nonexistent_path_exits_1(self, monkeypatch, tmp_path):
        assert _run_main(monkeypatch, str(tmp_path / "nope.md")) == 1

    def test_empty_directory_exits_1(self, monkeypatch, tmp_path):
        assert _run_main(monkeypatch, str(tmp_path)) == 1


class TestMainAudit:
    def test_single_file_json_export(self, monkeypatch, tmp_path):
        src = _write_md(tmp_path / "a.md")
        out = tmp_path / "r.json"
        code = _run_main(monkeypatch, str(src), "--rules", RULES, "-o", str(out))
        assert code == 1  # 缺 CON-002 必备章节 → error
        assert out.exists()
        assert json.loads(out.read_text(encoding="utf-8"))["findings"]

    def test_fail_on_none_exits_0(self, monkeypatch, tmp_path):
        src = _write_md(tmp_path / "a.md")
        out = tmp_path / "r.json"
        code = _run_main(
            monkeypatch, str(src), "--rules", RULES, "--fail-on", "none", "-o", str(out)
        )
        assert code == 0

    def test_html_no_thumbnails(self, monkeypatch, tmp_path):
        src = _write_md(tmp_path / "a.md")
        out = tmp_path / "r.html"
        _run_main(monkeypatch, str(src), "--rules", RULES, "--no-thumbnails", "-o", str(out))
        assert out.exists()
        assert "<svg" not in out.read_text(encoding="utf-8")

    def test_corrupt_file_exits_1(self, monkeypatch, tmp_path):
        broken = tmp_path / "broken.pptx"
        broken.write_text("not a zip", encoding="utf-8")
        assert _run_main(monkeypatch, str(broken), "--rules", RULES) == 1

    def test_fix_unsupported_format_message(self, monkeypatch, tmp_path, capsys):
        src = _write_md(tmp_path / "a.md")
        # --fail-on none 固定退出码，避免用 "code in (0, 1)" 这种与取值域同宽的弱断言
        code = _run_main(monkeypatch, str(src), "--rules", RULES, "--fix", "--fail-on", "none")
        assert code == 0
        assert "暂不支持自动修复" in capsys.readouterr().out

    def test_exempt_file_filters_findings(self, monkeypatch, tmp_path):
        from src.cli import audit_file
        from src.engines.exemptions import save_exemptions

        src = _write_md(tmp_path / "a.md")
        _, findings = audit_file(str(src), rules_path=RULES)
        assert findings
        exempt_path = tmp_path / ".docauditignore"
        save_exemptions(exempt_path, {findings[0].exemption_key}, findings)

        out = tmp_path / "r.json"
        code = _run_main(
            monkeypatch,
            str(src),
            "--rules",
            RULES,
            "--exempt-file",
            str(exempt_path),
            "--fail-on",
            "none",
            "-o",
            str(out),
        )
        assert code == 0
        remaining = json.loads(out.read_text(encoding="utf-8"))["findings"]
        assert len(remaining) == len(findings) - 1


class TestMainBatch:
    def test_batch_csv_per_file(self, monkeypatch, tmp_path):
        for name in ("a.md", "b.md"):
            _write_md(tmp_path / name)
        out = tmp_path / "r.csv"
        code = _run_main(monkeypatch, str(tmp_path), "--rules", RULES, "-o", str(out))
        assert code == 1
        assert list(tmp_path.glob("r_*.csv"))

    def test_batch_sarif_aggregated_relative(self, monkeypatch, tmp_path):
        for name in ("a.md", "b.md"):
            _write_md(tmp_path / name)
        out = tmp_path / "r.sarif"
        _run_main(
            monkeypatch,
            str(tmp_path),
            "--rules",
            RULES,
            "-o",
            str(out),
            "--sarif-base",
            str(tmp_path),
        )
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["runs"]) == 1
        uris = {
            r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
            for r in data["runs"][0]["results"]
        }
        assert uris == {"a.md", "b.md"}

    def test_batch_html_per_file(self, monkeypatch, tmp_path):
        for name in ("a.md", "b.md"):
            _write_md(tmp_path / name)
        out = tmp_path / "r.html"
        _run_main(monkeypatch, str(tmp_path), "--rules", RULES, "-o", str(out))
        assert list(tmp_path.glob("r_*.html"))


class TestMainSubcommands:
    def test_rules_validate(self, monkeypatch):
        assert _run_main(monkeypatch, "rules", "validate") == 0

    def test_rules_list(self, monkeypatch):
        assert _run_main(monkeypatch, "rules", "list") == 0

    def test_rules_missing_subcommand_exits_2(self, monkeypatch):
        assert _run_main(monkeypatch, "rules") == 2

    def test_doctor_exit_0_without_network(self, monkeypatch):
        import requests

        monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError))
        assert _run_main(monkeypatch, "doctor") == 0
