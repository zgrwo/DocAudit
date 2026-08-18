"""WP-C: app.py Web UI 状态修复 + 路径沙箱安全加固测试。

覆盖:
- _apply_filters 纯函数 (严重度/规则豁免/页面豁免/单条豁免/类型过滤)
- scan_folder 路径沙箱 (存在/不存在/".." 拒绝/单层不递归)
- _batch_file_key 批量文件唯一 key (P8: 完整路径 / 同名上传加序号兜底)
- _exempt_ids 豁免整体赋值 (P10)
- _get_auditors 缓存 (P9: cache_resource 命中返回同一对象)
- html_reporter page_count 参数 (P6)
- AppTest: 冒烟 + P5 checkbox 立即生效 + P7 multiselect 显式 key 与清除同步 + 路径沙箱 UI
- .streamlit/config.toml: server.address = "localhost" (安全回归)
"""

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from src.models.document import Document, DocumentMetadata, Page  # noqa: E402
from src.models.finding import AuditFinding, FindingSeverity, FindingType  # noqa: E402
from src.reporters.html_reporter import generate_html_report  # noqa: E402

APP_FILE = str(ROOT / "app.py")


# ── 测试数据工厂 ──────────────────────────────────────────────


def _finding(
    type_: FindingType = FindingType.FORMAT,
    severity: FindingSeverity = FindingSeverity.WARNING,
    message: str = "测试发现",
    rule_id: str | None = "FMT-001",
    page_index: int | None = 0,
) -> AuditFinding:
    return AuditFinding(
        type=type_,
        severity=severity,
        message=message,
        rule_id=rule_id,
        page_index=page_index,
    )


def _doc(pages: int = 3, source: str = "测试.pptx") -> Document:
    return Document(
        source_path=source,
        format="pptx",
        metadata=DocumentMetadata(title="测试文档"),
        pages=[Page(index=i) for i in range(pages)],
    )


class _FakeUpload:
    """模拟 Streamlit UploadedFile (仅需 name + getvalue 判定)。"""

    def __init__(self, name: str):
        self.name = name

    def getvalue(self):
        return b""


# ── 安全配置回归 ──────────────────────────────────────────────


def test_streamlit_config_binds_localhost_only():
    """安全红线: [server] 必须绑定 localhost，禁止默认 0.0.0.0 未认证暴露。"""
    cfg = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    server = cfg.split("[server]", 1)[1].split("[", 1)[0]
    assert 'address = "localhost"' in server


# ── _apply_filters 纯函数 ─────────────────────────────────────


def _base_state(**kw):
    state = {
        "filter_error": True,
        "filter_warning": True,
        "filter_info": False,
        "excluded_rules": [],
        "excluded_pages": [],
        "exempted_finding_ids": set(),
        "filter_types": [],
    }
    state.update(kw)
    return state


def test_apply_filters_severity():
    findings = [
        _finding(severity=FindingSeverity.ERROR, message="严重"),
        _finding(severity=FindingSeverity.WARNING, message="警告"),
        _finding(severity=FindingSeverity.INFO, message="提示"),
    ]
    result = app._apply_filters(findings, _base_state())
    assert [f.severity.value for f in result] == ["error", "warning"]
    result = app._apply_filters(findings, _base_state(filter_error=False))
    assert [f.severity.value for f in result] == ["warning"]


def test_apply_filters_rule_exemption():
    findings = [
        _finding(rule_id="FMT-001", message="a"),
        _finding(rule_id="FMT-002", message="b"),
        _finding(rule_id=None, message="c"),
    ]
    result = app._apply_filters(findings, _base_state(excluded_rules=["FMT-001"]))
    assert [f.rule_id for f in result] == ["FMT-002", None]


def test_apply_filters_page_exemption():
    findings = [
        _finding(page_index=0, message="第1页"),
        _finding(page_index=1, message="第2页"),
        _finding(page_index=None, message="无页"),
    ]
    result = app._apply_filters(findings, _base_state(excluded_pages=["第 2 页"]))
    assert [f.message for f in result] == ["第1页", "无页"]


def test_apply_filters_single_exemption():
    f1 = _finding(message="a")
    f2 = _finding(message="b")
    result = app._apply_filters([f1, f2], _base_state(exempted_finding_ids={f1.id}))
    assert [f.message for f in result] == ["b"]


def test_apply_filters_type_filter():
    findings = [
        _finding(type_=FindingType.FORMAT, message="格式"),
        _finding(type_=FindingType.STRUCTURE, message="结构"),
    ]
    result = app._apply_filters(findings, _base_state(filter_types=["format"]))
    assert [f.message for f in result] == ["格式"]


# ── scan_folder 路径沙箱 ──────────────────────────────────────


def test_scan_folder_existing_dir(tmp_path):
    (tmp_path / "a.pptx").write_bytes(b"x")
    (tmp_path / "b.md").write_text("# 标题", encoding="utf-8")
    (tmp_path / "c.txt").write_text("内容", encoding="utf-8")
    (tmp_path / "d.exe").write_bytes(b"x")
    files = app.scan_folder(str(tmp_path))
    assert [f.name for f in files] == ["a.pptx", "b.md", "c.txt"]


def test_scan_folder_missing_dir(tmp_path):
    assert app.scan_folder(str(tmp_path / "不存在")) == []


def test_scan_folder_rejects_parent_segment(tmp_path):
    # ".." 路径段 (Path.parts 判断) 必须拒绝：父目录含支持文件时若无防护会返回文件
    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "sibling.pptx").write_bytes(b"x")
    assert app.scan_folder(str(sub / "..")) == []


def test_scan_folder_single_level_no_recursion(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested.pptx").write_bytes(b"x")
    (tmp_path / "top.md").write_text("# 标题", encoding="utf-8")
    files = app.scan_folder(str(tmp_path))
    assert [f.name for f in files] == ["top.md"]


# ── P8: 批量文件唯一 key ──────────────────────────────────────


def test_batch_file_key_path_uses_full_path(tmp_path):
    p = tmp_path / "报告.pptx"
    used = set()
    key = app._batch_file_key(p, 0, used)
    assert key == str(p)
    assert key in used


def test_batch_file_key_upload_collision_gets_index():
    used = set()
    f1 = _FakeUpload("报告.pptx")
    f2 = _FakeUpload("报告.pptx")
    k1 = app._batch_file_key(f1, 0, used)
    k2 = app._batch_file_key(f2, 1, used)
    assert k1 == "报告.pptx"
    assert k2 == "报告.pptx#2"
    assert k1 != k2


# ── P10: 豁免整体赋值 ─────────────────────────────────────────


def test_exempt_ids_whole_assignment():
    import streamlit as st

    st.session_state["exempted_finding_ids"] = {"a"}
    app._exempt_ids(["b", "c"])
    assert st.session_state["exempted_finding_ids"] == {"a", "b", "c"}
    app._exempt_ids([])
    assert st.session_state["exempted_finding_ids"] == {"a", "b", "c"}
    del st.session_state["exempted_finding_ids"]


# ── P9: 审计器缓存 ────────────────────────────────────────────


def test_get_auditors_cached():
    a1 = app._get_auditors()
    a2 = app._get_auditors()
    assert a1 is a2  # cache_resource 命中返回同一对象，避免每次 rerun 重新解析


# ── P6: html_reporter page_count 参数 ─────────────────────────


def test_html_report_page_count_default_is_doc_pages():
    html = generate_html_report(_doc(pages=3), [], title="测试")
    assert "共 3 页" in html


def test_html_report_page_count_override():
    html = generate_html_report(
        _doc(pages=3), [], title="批量", file_label="批量 2 个文件", page_count=7
    )
    assert "共 7 页" in html
    assert "文件: 批量 2 个文件" in html


def test_html_report_page_count_none_backward_compat():
    html = generate_html_report(_doc(pages=5), [], title="测试", page_count=None)
    assert "共 5 页" in html


# ── AppTest ───────────────────────────────────────────────────


def _run_app_with(findings, doc=None):
    at = AppTest.from_file(APP_FILE, default_timeout=30)
    at.run()
    at.session_state["findings"] = findings
    if doc is not None:
        at.session_state["doc"] = doc
    at.run()
    assert not at.exception
    return at


def test_app_test_smoke():
    at = AppTest.from_file(APP_FILE, default_timeout=30)
    at.run()
    assert not at.exception


def test_p5_severity_checkbox_immediate_effect():
    """P5: 关闭 Warning 复选框后主区计数立即生效 (无滞后一拍)。"""
    findings = [
        _finding(severity=FindingSeverity.ERROR, message="严重问题"),
        _finding(severity=FindingSeverity.WARNING, message="警告问题"),
    ]
    at = _run_app_with(findings, doc=_doc(pages=1))
    counts = [sh.value for sh in at.subheader if "审查发现" in sh.value]
    assert counts and "审查发现 (2 项)" in counts[0]
    # 关闭 Warning 复选框 (index 1 = filter_warning) → 立即生效
    at.checkbox[1].set_value(False)
    at.run()
    counts = [sh.value for sh in at.subheader if "审查发现" in sh.value]
    assert counts and "审查发现 (1 项)" in counts[0]


def test_p7_multiselect_explicit_keys_and_clear_sync():
    """P7: 三个 multiselect 显式 key；清除全部豁免后 widget 状态与 session_state 同步。"""
    findings = [
        _finding(rule_id="R-1", message="问题A"),
        _finding(rule_id="R-2", message="问题B"),
    ]
    at = _run_app_with(findings, doc=_doc(pages=1))
    # 三个 multiselect 均有显式 key
    assert at.multiselect(key="filter_types")
    assert at.multiselect(key="excluded_rules")
    assert at.multiselect(key="excluded_pages")
    # 豁免规则 R-1 → 应用
    at.multiselect(key="excluded_rules").set_value(["R-1"])
    [b for b in at.button if "应用过滤器" in b.label][0].click()
    at.run()
    assert at.session_state["excluded_rules"] == ["R-1"]
    # 清除全部豁免 → session_state 与 widget 状态同步清空
    [b for b in at.button if "清除全部豁免" in b.label][0].click()
    at.run()
    assert at.session_state["excluded_rules"] == []
    assert at.multiselect(key="excluded_rules").value == []
    assert at.session_state["exempted_finding_ids"] == set()


def test_p6_batch_report_generation_runs():
    """P6: 批量模式下载区使用聚合元数据 (page_count=sum 页数, file_label=批量 N 个文件) 不抛异常。"""
    at = AppTest.from_file(APP_FILE, default_timeout=30)
    at.run()
    at.session_state["doc"] = _doc(pages=3)
    at.session_state["findings"] = [_finding(message="问题")]
    at.session_state["batch_mode"] = True
    at.session_state["batch_docs"] = [_doc(pages=3), _doc(pages=2)]
    at.run()
    assert not at.exception
    assert [db.label for db in at.download_button if "HTML" in db.label]


def test_folder_path_parent_segment_rejected_in_ui():
    """安全: 本地文件夹路径含 '..' 路径段 → st.error 并阻止扫描。"""
    at = AppTest.from_file(APP_FILE, default_timeout=30)
    at.run()
    at.radio[0].set_value("📂 批量/文件夹")
    at.run()
    at.text_input(key="folder_path").set_value("..\\..\\secret")
    at.run()
    errors = [e.value for e in at.error]
    assert any(".." in e for e in errors), f"expected st.error, got: {errors}"


def test_folder_path_missing_dir_rejected_in_ui():
    """安全: 不存在的目录 → st.error 并阻止扫描。"""
    at = AppTest.from_file(APP_FILE, default_timeout=30)
    at.run()
    at.radio[0].set_value("📂 批量/文件夹")
    at.run()
    at.text_input(key="folder_path").set_value("C:\\definitely_missing_dir_xyz")
    at.run()
    errors = [e.value for e in at.error]
    assert any("文件夹不存在" in e for e in errors), f"expected st.error, got: {errors}"
