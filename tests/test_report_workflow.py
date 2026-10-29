"""报告工作流测试 — HTML 分组/缩略图、CSV、SARIF、CLI 导出接线。

2026-10-29: 补齐 handoff「报告工作流」待办：按文件分组、SVG 线框、SARIF/CSV。
"""

import csv
import io
import json
import subprocess
import sys
from pathlib import Path

from src.models.document import Document, DocumentMetadata, Page, PageElement, Paragraph
from src.models.finding import AuditFinding, FindingSeverity, FindingType
from src.reporters.csv_reporter import generate_csv_report
from src.reporters.html_reporter import generate_html_report
from src.reporters.sarif_reporter import generate_sarif_report

PROJECT_ROOT = Path(__file__).resolve().parent.parent

XSS = '<script>alert("x")</script>'


def _finding(
    *,
    severity=FindingSeverity.WARNING,
    rule_id="FMT-001",
    page=0,
    message="测试问题",
    source_file=None,
):
    meta = {"source_file": source_file} if source_file else {}
    return AuditFinding(
        type=FindingType.FORMAT,
        severity=severity,
        message=message,
        rule_id=rule_id,
        page_index=page,
        location=f"第 {page + 1} 页",
        context="上下文",
        suggestion="建议",
        metadata=meta,
    )


def _doc(pages=None, props=None):
    return Document(
        format="pptx",
        source_path="deck.pptx",
        metadata=DocumentMetadata(custom_properties=props or {}),
        pages=pages if pages is not None else [Page(index=0, slide_number=1)],
    )


def _frame(left, top, width, height, name="文本框"):
    return PageElement(
        type="text_frame",
        left=left,
        top=top,
        width=width,
        height=height,
        shape_name=name,
        paragraphs=[Paragraph(text="内容", runs=[])],
    )


class TestSarifReporter:
    def test_minimal_sarif_structure(self):
        findings = [
            _finding(severity=FindingSeverity.ERROR, page=1, rule_id="STR-001"),
            _finding(severity=FindingSeverity.INFO, page=0, rule_id="FMT-007"),
        ]
        report = json.loads(generate_sarif_report(_doc(), findings))
        assert report["version"] == "2.1.0"
        assert "sarif" in report["$schema"]
        run = report["runs"][0]
        assert run["tool"]["driver"]["name"] == "DocAudit"
        assert {r["id"] for r in run["tool"]["driver"]["rules"]} == {"STR-001", "FMT-007"}
        # error 在前 (与 HTML/CSV 共用排序)
        assert run["results"][0]["ruleId"] == "STR-001"
        assert run["results"][0]["level"] == "error"
        assert run["results"][1]["level"] == "note"

    def test_severity_to_sarif_level_mapping(self):
        findings = [
            _finding(severity=FindingSeverity.WARNING, rule_id="A"),
            _finding(severity=FindingSeverity.INFO, rule_id="B"),
            _finding(severity=FindingSeverity.ERROR, rule_id="C"),
        ]
        results = json.loads(generate_sarif_report(_doc(), findings))["runs"][0]["results"]
        assert [r["level"] for r in results] == ["error", "warning", "note"]

    def test_partial_fingerprint_is_stable_across_runs(self):
        findings = [_finding()]
        a = json.loads(generate_sarif_report(_doc(), findings))
        b = json.loads(generate_sarif_report(_doc(), findings))
        fp_a = a["runs"][0]["results"][0]["partialFingerprints"]
        fp_b = b["runs"][0]["results"][0]["partialFingerprints"]
        assert fp_a == fp_b
        assert fp_a["docAuditFinding/v1"]

    def test_batch_uses_source_file_artifact_uri(self):
        findings = [_finding(source_file="a.pptx")]
        result = json.loads(generate_sarif_report(_doc(), findings))["runs"][0]["results"][0]
        uri = result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        assert uri.endswith("a.pptx")

    def test_writes_file_and_returns_text(self, tmp_path):
        out = tmp_path / "r.sarif"
        text = generate_sarif_report(_doc(), [_finding()], output_path=out)
        assert out.exists()
        assert json.loads(out.read_text(encoding="utf-8"))["version"] == "2.1.0"
        assert json.loads(text)["runs"][0]["results"]

    def test_empty_findings(self):
        report = json.loads(generate_sarif_report(_doc(), []))
        assert report["runs"][0]["results"] == []
        assert report["runs"][0]["tool"]["driver"]["rules"] == []


class TestCsvReporter:
    def test_header_and_rows(self):
        findings = [_finding(severity=FindingSeverity.ERROR, page=2)]
        rows = list(csv.reader(io.StringIO(generate_csv_report(findings))))
        assert rows[0][0] == "rule_id"
        assert rows[1][0] == "FMT-001"
        assert rows[1][1] == "error"
        assert rows[1][3] == "3"  # 页码 1-based

    def test_formula_injection_sanitized(self):
        findings = [_finding(message="=cmd|'/c calc'!A1")]
        rows = list(csv.reader(io.StringIO(generate_csv_report(findings))))
        assert rows[1][5].startswith("'=")

    def test_comma_quoted(self):
        findings = [_finding(message="a,b")]
        rows = list(csv.reader(io.StringIO(generate_csv_report(findings))))
        assert rows[1][5] == "a,b"

    def test_file_has_bom(self, tmp_path):
        out = tmp_path / "r.csv"
        generate_csv_report([_finding()], output_path=out)
        assert out.read_bytes().startswith(b"\xef\xbb\xbf")


class TestHtmlWorkflow:
    def test_grouped_by_source_file(self):
        findings = [
            _finding(source_file="a.pptx", page=0, rule_id="STR-001"),
            _finding(source_file="a.pptx", page=1, rule_id="FMT-001"),
            _finding(source_file="b.docx", page=0, rule_id="TERM-001"),
        ]
        html = generate_html_report(_doc(), findings, show_thumbnails=False)
        assert html.count('class="file-group"') == 2
        assert "a.pptx" in html and "b.docx" in html
        # 分组标题带每文件计数
        assert "(2 条" in html and "(1 条" in html

    def test_no_grouping_for_single_file(self):
        findings = [_finding(source_file="a.pptx"), _finding(source_file="a.pptx")]
        html = generate_html_report(_doc(), findings, show_thumbnails=False)
        assert 'class="file-group"' not in html

    def test_thumbnails_rendered_when_geometry_present(self):
        page = Page(index=0, slide_number=1, elements=[_frame(50, 50, 200, 100)])
        html = generate_html_report(_doc(pages=[page]), [_finding()])
        assert 'class="thumbs"' in html
        assert "<svg" in html
        assert "第 1 页" in html

    def test_thumbnails_skipped_without_geometry(self):
        html = generate_html_report(_doc(pages=[Page(index=0, slide_number=1)]), [_finding()])
        assert "<svg" not in html

    def test_thumbnails_can_be_disabled(self):
        page = Page(index=0, slide_number=1, elements=[_frame(50, 50, 200, 100)])
        html = generate_html_report(_doc(pages=[page]), [_finding()], show_thumbnails=False)
        assert "<svg" not in html

    def test_thumbnail_shape_name_escaped(self):
        page = Page(index=0, slide_number=1, elements=[_frame(50, 50, 100, 50, name=XSS)])
        html = generate_html_report(_doc(pages=[page]), [_finding()])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestCliReportExport:
    """CLI -o 契约：.csv / .sarif 导出（含批量聚合语义）。"""

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

    def test_csv_export(self, tmp_path):
        src = tmp_path / "a.md"
        self._write_md(src)
        out = tmp_path / "r.csv"
        result = self._run_cli(str(src), "--rules", str(PROJECT_ROOT / "rules.md"), "-o", str(out))
        assert "CSV report saved" in result.stdout, result.stdout[-500:]
        assert out.exists()
        assert out.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_sarif_export_is_aggregated(self, tmp_path):
        for name in ("a.md", "b.md"):
            self._write_md(tmp_path / name)
        out = tmp_path / "r.sarif"
        result = self._run_cli(
            str(tmp_path), "--rules", str(PROJECT_ROOT / "rules.md"), "-o", str(out)
        )
        assert "SARIF report saved" in result.stdout, result.stdout[-800:]
        data = json.loads(out.read_text(encoding="utf-8"))
        # 批量 → 单个聚合 SARIF（不产生 _01/_02 分片）
        assert len(data["runs"]) == 1
        assert not list(tmp_path.glob("r_*.sarif"))

    def test_unsupported_suffix_exits_2(self, tmp_path):
        src = tmp_path / "a.md"
        self._write_md(src)
        result = self._run_cli(str(src), "-o", str(tmp_path / "r.txt"))
        assert result.returncode == 2
