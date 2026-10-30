"""报告工作流测试 — HTML 分组/缩略图、CSV、SARIF、CLI 导出接线。

2026-10-29: 补齐 handoff「报告工作流」待办：按文件分组、SVG 线框、SARIF/CSV。
"""

import csv
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.models.document import Document, DocumentMetadata, Page, PageElement, Paragraph
from src.models.finding import AuditFinding, FindingSeverity, FindingType
from src.reporters.csv_reporter import generate_csv_report
from src.reporters.html_reporter import generate_html_report
from src.reporters.json_reporter import generate_json_report
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
    finding_type=FindingType.FORMAT,
):
    meta = {"source_file": source_file} if source_file else {}
    return AuditFinding(
        type=finding_type,
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


@pytest.mark.slow  # 子进程 CLI 用例：pre-commit 快测跳过
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

    def test_batch_sarif_attributes_each_finding_to_its_file(self, tmp_path):
        """回归 (2026-10-29): 聚合 SARIF 曾把所有 finding 归到最后一个文件。"""
        for name in ("a.md", "b.md"):
            self._write_md(tmp_path / name)
        out = tmp_path / "r.sarif"
        self._run_cli(str(tmp_path), "--rules", str(PROJECT_ROOT / "rules.md"), "-o", str(out))
        data = json.loads(out.read_text(encoding="utf-8"))
        uris = {
            r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
            for r in data["runs"][0]["results"]
        }
        assert len(uris) >= 2, f"批量 finding 应归属各自文件，实际 {uris}"

    def test_batch_sarif_uri_base_relative(self, tmp_path):
        """--sarif-base → 仓库相对 URI（Code Scanning 关联文件的前提）。"""
        for name in ("a.md", "b.md"):
            self._write_md(tmp_path / name)
        out = tmp_path / "r.sarif"
        self._run_cli(
            str(tmp_path),
            "--rules",
            str(PROJECT_ROOT / "rules.md"),
            "-o",
            str(out),
            "--sarif-base",
            str(tmp_path),
        )
        data = json.loads(out.read_text(encoding="utf-8"))
        uris = {
            r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
            for r in data["runs"][0]["results"]
        }
        assert uris and all(not u.startswith("file://") for u in uris), uris
        assert uris == {"a.md", "b.md"}

    def test_unsupported_suffix_exits_2(self, tmp_path):
        src = tmp_path / "a.md"
        self._write_md(src)
        result = self._run_cli(str(src), "-o", str(tmp_path / "r.txt"))
        assert result.returncode == 2


class TestExemptionKeyExport:
    """2026-10-29: 报告带出稳定 exemption_key，CLI 用户可据此构造 .docauditignore。"""

    def test_csv_last_column_is_exemption_key(self):
        f = _finding()
        rows = list(csv.reader(io.StringIO(generate_csv_report([f]))))
        assert rows[0][-1] == "exemption_key"
        assert rows[1][-1] == f.exemption_key

    def test_json_findings_include_exemption_key(self):
        from src.reporters.json_reporter import generate_json_report

        f = _finding()
        report = generate_json_report(_doc(), [f])
        assert report["findings"][0]["exemption_key"] == f.exemption_key

    def test_csv_key_roundtrips_to_docauditignore(self, tmp_path):
        """从 CSV 取 key → 写入 .docauditignore → apply 后该 finding 被过滤。"""
        from src.engines.exemptions import apply_exemptions, load_exemptions, save_exemptions

        f = _finding()
        rows = list(csv.reader(io.StringIO(generate_csv_report([f]))))
        key = rows[1][-1]
        path = tmp_path / ".docauditignore"
        save_exemptions(path, {key}, [f])
        kept, exempted = apply_exemptions([f], load_exemptions(path))
        assert exempted == 1
        assert kept == []

    def test_type_breakdown_rendered(self):
        """按摘要类型分布（2026-10-29）：结构/格式等计数出现在统计行。"""
        findings = [
            _finding(rule_id="STR-001", finding_type=FindingType.STRUCTURE),
            _finding(message="格式问题", rule_id="FMT-001"),
        ]
        html = generate_html_report(_doc(), findings, show_thumbnails=False)
        assert 'class="type-stats"' in html
        assert "格式 1" in html and "结构 1" in html

    def test_no_type_breakdown_when_clean(self):
        html = generate_html_report(_doc(), [], show_thumbnails=False)
        assert 'class="type-stats"' not in html

    def test_thumbnail_elements_capped_per_page(self):
        page = Page(
            index=0,
            slide_number=1,
            elements=[_frame(10 + i, 10, 20, 20) for i in range(250)],
        )
        html = generate_html_report(_doc(pages=[page]), [_finding()])
        assert html.count('class="el-text_frame"') == 200

    def test_thumbnail_elements_capped_in_total(self):
        pages = [
            Page(
                index=i,
                slide_number=i + 1,
                elements=[_frame(10, 10, 20, 20) for _ in range(200)],
            )
            for i in range(20)
        ]
        html = generate_html_report(_doc(pages=pages), [_finding()])
        assert html.count('class="el-text_frame"') <= 3000

    def test_uri_base_makes_paths_relative(self, tmp_path):
        """2026-10-29: --sarif-base 输出仓库相对 URI（GitHub Code Scanning 需要）。"""
        doc_path = tmp_path / "docs" / "a.pptx"
        doc_path.parent.mkdir()
        doc = _doc()
        doc.source_path = str(doc_path)
        result = json.loads(generate_sarif_report(doc, [_finding()], uri_base=tmp_path))["runs"][0][
            "results"
        ][0]
        uri = result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        assert uri == "docs/a.pptx"

    def test_uri_base_outside_falls_back_to_file_uri(self, tmp_path):
        doc = _doc()  # source_path="deck.pptx" 相对路径解析到项目根，不在 tmp 下
        doc.source_path = str(tmp_path.parent / "elsewhere" / "x.pptx")
        uri = json.loads(generate_sarif_report(doc, [_finding()], uri_base=tmp_path))["runs"][0][
            "results"
        ][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        assert uri.startswith("file://")

    def test_batch_findings_file_scoped_exemption_keys(self, tmp_path):
        """批量 finding 的 location 带文件名前缀 → 豁免键按文件区分（跨文件不误豁免）。"""
        import subprocess
        import sys

        for name in ("a.md", "b.md"):
            (tmp_path / name).write_text("# 概述\n\n正文内容。\n", encoding="utf-8")
        out = tmp_path / "r.json"
        subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "src" / "cli.py"),
                str(tmp_path),
                "--rules",
                str(PROJECT_ROOT / "rules.md"),
                "-o",
                str(out),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT_ROOT),
            encoding="utf-8",
            errors="replace",
        )
        reports = sorted(tmp_path.glob("r_*.json"))
        assert len(reports) == 2
        keys = set()
        sources = set()
        for report in reports:
            data = json.loads(report.read_text(encoding="utf-8"))
            for finding in data["findings"]:
                keys.add(finding["exemption_key"])
                sources.add(finding["metadata"]["source_file"])
        assert len(keys) >= 2, f"两文件的同文 finding 应有不同豁免键，实际 {keys}"
        assert {Path(s).name for s in sources} == {"a.md", "b.md"}


class TestReviewReportRegressions:
    """2026-10-29 深度审查回归：CSV 落盘 / SARIF 指纹。"""

    def test_csv_file_has_no_double_cr(self, tmp_path):
        out = tmp_path / "r.csv"
        generate_csv_report([_finding()], out)
        raw = out.read_bytes()
        assert b"\r\r\n" not in raw, "文本模式写盘会把 \r\n 再翻成 \r\r\n"
        with out.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        assert len(rows) == 2  # 表头 + 1 条，且无空行记录

    def test_sarif_fingerprint_differs_per_source_file(self):
        from dataclasses import replace

        a = replace(_finding(), metadata={"source_file": "a.pptx"})
        b = replace(_finding(), metadata={"source_file": "b.pptx"})
        fa = json.loads(generate_sarif_report(_doc(), [a]))["runs"][0]["results"][0][
            "partialFingerprints"
        ]
        fb = json.loads(generate_sarif_report(_doc(), [b]))["runs"][0]["results"][0][
            "partialFingerprints"
        ]
        assert fa != fb, "不同文件同一发现的 SARIF 指纹不得相同（否则 Code Scanning 合并告警）"


class TestSarifUriEncoding:
    """2026-10-29 深度审查 P2 回归：相对 URI 必须百分号编码。"""

    def test_relative_uri_percent_encoded(self, tmp_path):
        weird = tmp_path / "报告 v2 #1%.pptx"
        weird.write_bytes(b"x")
        doc = _doc()
        doc.source_path = str(weird)
        uri = json.loads(generate_sarif_report(doc, [_finding()], uri_base=tmp_path))["runs"][0][
            "results"
        ][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        assert "#" not in uri, f"未编码的 # 会被当片段标识: {uri}"
        assert "%23" in uri
        assert " " not in uri
        assert uri == "%E6%8A%A5%E5%91%8A%20v2%20%231%25.pptx"


class TestScoreAndCoverageInReports:
    """2026-11: 质量分与覆盖声明进入 HTML/JSON/SARIF 报告。"""

    SCORE = {
        "score": 78,
        "grade": "B",
        "penalty": 9.0,
        "penalty_per_page": 1.5,
        "penalty_cap": 20.0,
        "pages": 6,
        "counts": {"error": 1, "warning": 0, "info": 0},
        "dimensions": {"格式": {"score": 80, "count": 1, "penalty": 3.0}},
        "system_errors": 0,
        "estimated": 0,
    }
    COVERAGE = {
        "format": "pptx",
        "pages": 6,
        "language_backend": "python",
        "language_available": True,
        "geometry": True,
        "font_metadata": True,
        "not_applicable_checks": [],
        "failed_auditors": [],
        "estimated_findings": 0,
        "estimated_rule_ids": [],
        "complete": True,
        "notes": ["语言检查后端: 纯 Python 降级"],
    }

    def test_json_report_includes_score_and_coverage(self):
        doc = _doc()
        report = generate_json_report(doc, [_finding()], score=self.SCORE, coverage=self.COVERAGE)
        assert report["summary"]["score"] == 78
        assert report["summary"]["grade"] == "B"
        assert report["score"]["dimensions"]["格式"]["score"] == 80
        assert report["coverage"]["language_backend"] == "python"

    def test_json_report_omits_when_not_provided(self):
        doc = _doc()
        report = generate_json_report(doc, [_finding()])
        assert report["summary"]["score"] is None
        assert "coverage" not in report

    def test_html_report_renders_score_card_and_coverage(self):
        doc = _doc()
        html = generate_html_report(doc, [_finding()], score=self.SCORE, coverage=self.COVERAGE)
        assert "78" in html and "/100" in html
        assert "等级 B" in html
        assert "审查范围与可信度" in html
        assert "纯 Python 降级" in html

    def test_html_report_without_score_has_no_card(self):
        html = generate_html_report(_doc(), [_finding()])
        assert 'class="score-card' not in html
        assert "审查范围与可信度" not in html

    def test_sarif_run_properties_carry_score_and_coverage(self):
        doc = _doc()
        text = generate_sarif_report(doc, [_finding()], score=self.SCORE, coverage=self.COVERAGE)
        run = json.loads(text)["runs"][0]
        assert run["properties"]["docAuditScore"] == 78
        assert run["properties"]["docAuditGrade"] == "B"
        assert run["properties"]["docAuditCoverageComplete"] is True
