"""豁免持久化 (.docauditignore) 测试 — 跨会话复用误报豁免。"""

import json
import subprocess
import sys
from pathlib import Path

from src.engines.exemptions import (
    apply_exemptions,
    load_exemptions,
    save_exemptions,
)
from src.models.finding import AuditFinding, FindingSeverity, FindingType

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _finding(message="测试问题", page=0, rule_id="FMT-001"):
    return AuditFinding(
        type=FindingType.FORMAT,
        severity=FindingSeverity.WARNING,
        message=message,
        rule_id=rule_id,
        page_index=page,
        location=f"第 {page + 1} 页",
        context="上下文",
    )


class TestLoadExemptions:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_exemptions(tmp_path / "nope.json") == set()

    def test_roundtrip(self, tmp_path):
        findings = [_finding(), _finding(message="另一个", page=2, rule_id="STR-002")]
        keys = {f.exemption_key for f in findings}
        path = tmp_path / ".docauditignore"
        save_exemptions(path, keys, findings)
        assert load_exemptions(path) == keys

    def test_metadata_saved_for_human_review(self, tmp_path):
        f = _finding(page=3)
        path = tmp_path / ".docauditignore"
        save_exemptions(path, {f.exemption_key}, [f])
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == 1
        entry = data["exemptions"][0]
        assert entry["key"] == f.exemption_key
        assert entry["rule_id"] == "FMT-001"
        assert entry["page"] == 4  # 1-based

    def test_legacy_bare_list_supported(self, tmp_path):
        path = tmp_path / ".docauditignore"
        path.write_text(json.dumps(["abc", "def"]), encoding="utf-8")
        assert load_exemptions(path) == {"abc", "def"}

    def test_corrupt_json_returns_empty(self, tmp_path):
        path = tmp_path / ".docauditignore"
        path.write_text("{not json", encoding="utf-8")
        assert load_exemptions(path) == set()

    def test_entries_without_key_ignored(self, tmp_path):
        path = tmp_path / ".docauditignore"
        path.write_text(
            json.dumps({"exemptions": [{"rule_id": "X"}, "ok", None]}), encoding="utf-8"
        )
        assert load_exemptions(path) == {"ok"}

    def test_empty_save_roundtrip(self, tmp_path):
        path = tmp_path / ".docauditignore"
        save_exemptions(path, set())
        assert load_exemptions(path) == set()


class TestApplyExemptions:
    def test_filters_and_counts(self):
        findings = [_finding(), _finding(message="保留")]
        keys = {findings[0].exemption_key}
        kept, exempted = apply_exemptions(findings, keys)
        assert exempted == 1
        assert len(kept) == 1
        assert kept[0].message == "保留"

    def test_no_keys_returns_original(self):
        findings = [_finding()]
        kept, exempted = apply_exemptions(findings, set())
        assert kept is findings
        assert exempted == 0

    def test_unknown_key_keeps_all(self):
        kept, exempted = apply_exemptions([_finding()], {"deadbeef"})
        assert len(kept) == 1
        assert exempted == 0


class TestCliExemptFile:
    """CLI --exempt-file: 命中项不计入报告与退出码。"""

    def _write_md(self, path: Path) -> None:
        path.write_text("# 标题\n\n这是正文内容。\n", encoding="utf-8")

    def _run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "src" / "cli.py"), *args],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT_ROOT),
            encoding="utf-8",
            errors="replace",
        )

    def test_exemption_file_filters_report(self, tmp_path):
        from src.cli import audit_file

        src = tmp_path / "a.md"
        self._write_md(src)
        _, findings = audit_file(str(src), rules_path=str(PROJECT_ROOT / "rules.md"))
        assert findings, "样例应产生至少一条 finding"

        exempt_path = tmp_path / ".docauditignore"
        save_exemptions(exempt_path, {findings[0].exemption_key}, findings)

        plain = tmp_path / "plain.json"
        exempted = tmp_path / "exempted.json"
        self._run_cli(str(src), "--rules", str(PROJECT_ROOT / "rules.md"), "-o", str(plain))
        result = self._run_cli(
            str(src),
            "--rules",
            str(PROJECT_ROOT / "rules.md"),
            "--exempt-file",
            str(exempt_path),
            "-o",
            str(exempted),
        )
        assert "[EXEMPT]" in result.stdout
        n_plain = len(json.loads(plain.read_text(encoding="utf-8"))["findings"])
        n_exempted = len(json.loads(exempted.read_text(encoding="utf-8"))["findings"])
        assert n_exempted == n_plain - 1
