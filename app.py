"""文档审查系统 — Streamlit Web UI

本地离线文档审查工具，支持 PPTX/DOCX/PDF/Markdown。
审查维度：内容结构 · 格式规范 · 语言文字 · 事实精准 · 自定义规则
"""

import json
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st

# 支持 `python app.py` 直接运行 (pip install 后 src/ 已在 path 中，此行冗余但无害)
sys.path.insert(0, str(Path(__file__).parent))

from src import __version__
from src.engines.pipeline import find_converter, run_auditors
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity
from src.reporters.html_reporter import generate_html_report
from src.reporters.json_reporter import generate_json_report


def _apply_filters(findings: list[AuditFinding]) -> list[AuditFinding]:
    """根据 session_state 中的过滤器设置，返回过滤后的 findings 列表。"""
    # 严重度过滤
    severity_active = []
    if st.session_state.get("filter_error", True):
        severity_active.append(FindingSeverity.ERROR)
    if st.session_state.get("filter_warning", True):
        severity_active.append(FindingSeverity.WARNING)
    if st.session_state.get("filter_info", False):
        severity_active.append(FindingSeverity.INFO)

    # 规则豁免
    excluded_rules = set(st.session_state.get("excluded_rules", []))

    # 页面豁免
    excluded_page_labels = st.session_state.get("excluded_pages", [])
    excluded_page_nums = set()
    for label in excluded_page_labels:
        m = re.search(r'\d+', label)
        if m:
            excluded_page_nums.add(int(m.group()))

    # 单条豁免
    exempted_ids = st.session_state.get("exempted_finding_ids", set())

    # 类型过滤
    type_filter = st.session_state.get("filter_types", [])

    return [
        f for f in findings
        if f.severity in severity_active
        and (not type_filter or f.type.value in type_filter)
        and (f.rule_id not in excluded_rules)
        and ((f.page_index is None) or (f.page_index + 1) not in excluded_page_nums)
        and (f.id not in exempted_ids)
    ]


# ── 页面配置 ────────────────────────────────────────────────

st.set_page_config(
    page_title="DocAudit — 文档审查系统",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 全局状态初始化 ──────────────────────────────────────────

if "doc" not in st.session_state:
    st.session_state.doc = None
if "findings" not in st.session_state:
    st.session_state.findings = []
if "audit_run" not in st.session_state:
    st.session_state.audit_run = False
if "audit_progress" not in st.session_state:
    st.session_state.audit_progress = {}
if "exempted_finding_ids" not in st.session_state:
    st.session_state.exempted_finding_ids = set()
# 批量模式
if "batch_mode" not in st.session_state:
    st.session_state.batch_mode = False
if "batch_docs" not in st.session_state:
    st.session_state.batch_docs = []
if "batch_findings" not in st.session_state:
    st.session_state.batch_findings = {}  # filename → list[findings]

# ── 预计算过滤结果 (sidebar + main area 共享，避免双次计算) ──
if st.session_state.get("findings"):
    _filtered_cache = _apply_filters(st.session_state.findings)
else:
    _filtered_cache = []


def convert_file(uploaded_file) -> Document | None:
    """将 Streamlit UploadedFile 写入临时文件后委托 convert_file_path 转换。"""
    suffix = Path(uploaded_file.name).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    try:
        doc = convert_file_path(tmp_path)
        if doc is None:
            st.error(f"不支持的文件格式: {suffix}")
        return doc
    except Exception as e:
        st.error(f"转换失败: {e}")
        import traceback
        st.code(traceback.format_exc())
        return None
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def convert_file_path(file_path: str | Path) -> Document | None:
    """将本地文件路径转换为 Document 模型。"""
    path = Path(file_path)
    converter = find_converter(str(path))
    if converter is None:
        return None
    return converter.convert(str(path))


def scan_folder(folder_path: str) -> list[Path]:
    """扫描文件夹，返回所有支持的文件路径。"""
    from src.engines.pipeline import SUPPORTED_EXTENSIONS
    folder = Path(folder_path)
    if not folder.is_dir():
        return []
    # 先过滤再排序，避免对非文档条目排序
    files = sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    return files


def _reset_batch_state() -> None:
    """重置审查状态和过滤器（新文件上传时调用）。"""
    st.session_state.findings = []
    st.session_state.doc = None
    st.session_state.audit_progress = {}
    st.session_state.exempted_finding_ids = set()
    st.session_state.batch_docs = []
    st.session_state.batch_findings = {}
    # 清除过滤器状态，避免旧规则/页面排除被应用到新文件
    st.session_state.excluded_rules = []
    st.session_state.excluded_pages = []
    st.session_state.filter_types = []


def _get_auditors():
    """构建全部审计器 (app.py 和批量审查共用)。"""
    from src.engines.pipeline import build_auditors

    base = Path(__file__).parent
    return build_auditors(
        str(base / "rules.md"),
        str(base / "glossary"),
        str(base / "vocab"),
    )


def _run_batch_audit(files: list) -> None:
    """批量审查：转换 + 审查所有文件。支持 StreamlitUploadedFile 和 Path。"""
    from src.engines.pipeline import run_auditors

    auditors = _get_auditors()

    progress_bar = st.empty().progress(0, "批量审查中...")
    docs = []
    all_findings_dict: dict[str, list] = {}

    for i, f in enumerate(files):
        # 获取文件名
        if hasattr(f, 'name'):
            fname = f.name
        else:
            fname = Path(f).name

        progress_bar.progress(
            (i + 0.3) / len(files),
            f"解析: {fname} ({i+1}/{len(files)})"
        )

        # 转换
        try:
            if hasattr(f, 'getvalue'):
                doc = convert_file(f)
            else:
                doc = convert_file_path(f)
        except Exception as e:
            st.warning(f"转换失败: {fname} — {e}")
            continue

        if doc is None:
            st.warning(f"不支持的文件: {fname}")
            continue

        docs.append(doc)

        # 审查
        progress_bar.progress(
            (i + 0.6) / len(files),
            f"审查: {fname} ({i+1}/{len(files)})"
        )
        try:
            findings = run_auditors(doc, auditors)
            all_findings_dict[fname] = findings
        except Exception as e:
            st.warning(f"审查失败: {fname} — {e}")
            all_findings_dict[fname] = []

        progress_bar.progress((i + 1) / len(files))

    progress_bar.empty()
    st.session_state.batch_docs = docs
    st.session_state.batch_findings = all_findings_dict

    # 汇总所有 findings 到一个列表（主视图使用）
    # 使用 dataclasses.replace 创建新实例，避免共享可变状态
    from dataclasses import replace as _dc_replace
    combined = []
    for fname, findings in all_findings_dict.items():
        for fd in findings:
            new_location = f"[{fname}] {fd.location}" if fd.location else f"[{fname}]"
            combined.append(_dc_replace(fd, location=new_location))
    st.session_state.findings = combined
    st.session_state.doc = docs[0] if docs else None


# ── 审查执行 ────────────────────────────────────────────────

def run_audit(doc: Document) -> list[AuditFinding]:
    """执行全部审查器，返回发现列表"""
    auditors = _get_auditors()
    progress_bar = st.empty().progress(0, "开始审查...")

    def on_progress(name, i, total):
        if name == "完成":
            progress_bar.progress(1.0, "审查完成 ✓")
        else:
            progress_bar.progress((i + 0.5) / total, f"正在执行: {name} ({i+1}/{total})")

    findings = run_auditors(doc, auditors, on_progress=on_progress)
    progress_bar.empty()  # 清除进度条

    return findings


# ── 侧边栏 ──────────────────────────────────────────────────

with st.sidebar:
    st.title("📄 DocAudit")
    st.caption("本地离线文档审查系统")

    st.divider()

    # ── 模式切换 ──────────────────────────────────────────
    mode_tab = st.radio(
        "审查模式",
        ["📄 单文件", "📂 批量/文件夹"],
        horizontal=True,
    )

    if mode_tab == "📄 单文件":
        st.subheader("📤 上传文档")
        uploaded_file = st.file_uploader(
            "拖拽或选择文件",
            type=["pptx", "ppt", "docx", "doc", "pdf", "md", "markdown", "txt"],
            help="支持 PPTX, DOCX, PDF, Markdown 格式",
            key="file_uploader",
        )

        if uploaded_file and st.button("🔍 开始审查", use_container_width=True, type="primary"):
            _reset_batch_state()
            with st.spinner("正在解析文档..."):
                st.session_state.doc = convert_file(uploaded_file)
            if st.session_state.doc:
                st.session_state.audit_run = True
                st.session_state.batch_mode = False
                st.rerun()

    else:
        st.subheader("📂 批量审查")

        # ── 方式1: 本地文件夹路径 ──
        folder_path = st.text_input(
            "📁 本地文件夹路径",
            placeholder="例如: D:\\docs\\reports",
            help="输入包含文档的文件夹路径，将审查其中所有支持的文件",
        )
        if folder_path:
            # 安全提示: 本地离线使用，如需部署为内网服务请添加路径沙箱
            if ".." in folder_path:
                st.warning("路径包含 '..'，请确认要访问的目录")
            folder_files = scan_folder(folder_path)
            if folder_files:
                st.caption(f"发现 {len(folder_files)} 个文件:")
                for f in folder_files[:20]:
                    st.caption(f"  • {f.name}")
                if len(folder_files) > 20:
                    st.caption(f"  ... 还有 {len(folder_files) - 20} 个")
            else:
                st.caption("未找到支持的文档文件")

        st.divider()
        st.caption("或")

        # ── 方式2: 多文件上传 ──
        uploaded_files = st.file_uploader(
            "📤 拖拽或选择多个文件",
            type=["pptx", "ppt", "docx", "doc", "pdf", "md", "markdown", "txt"],
            accept_multiple_files=True,
            help="可一次选择多个文件",
            key="multi_file_uploader",
        )

        # ── 合并文件列表 ──
        batch_files: list = []
        if folder_path and folder_files:
            batch_files.extend(folder_files)
        if uploaded_files:
            batch_files.extend(uploaded_files)

        if batch_files:
            st.caption(f"共 {len(batch_files)} 个待审查文件")
            if st.button("🔍 开始批量审查", use_container_width=True, type="primary"):
                _reset_batch_state()
                st.session_state.batch_mode = True
                _run_batch_audit(batch_files)
                st.rerun()

    st.divider()

    if st.session_state.findings:
        st.subheader("📊 审查结果")
        errors = sum(1 for f in st.session_state.findings if f.severity == FindingSeverity.ERROR)
        warnings = sum(1 for f in st.session_state.findings if f.severity == FindingSeverity.WARNING)
        infos = sum(1 for f in st.session_state.findings if f.severity == FindingSeverity.INFO)

        st.metric("🔴 严重问题", errors)
        st.metric("🟡 警告", warnings)
        st.metric("🔵 提示", infos)

        st.divider()

        st.subheader("🎛️ 过滤器")
        # 严重度 — 即时生效 (checkbox 体验好)
        for key, label, default in [
            ("filter_error", "严重 (Error)", True),
            ("filter_warning", "警告 (Warning)", True),
            ("filter_info", "提示 (Info)", False),
        ]:
            if key not in st.session_state:
                st.session_state[key] = default
            st.session_state[key] = st.checkbox(label, value=st.session_state[key])

        # ── 豁免设置 (表单批量提交) ──────────────────────
        st.divider()
        st.subheader("🛡️ 豁免")
        st.caption("选择后点击「应用」生效，避免反复刷新")

        all_rule_ids = sorted(set(
            f.rule_id for f in st.session_state.findings if f.rule_id
        ))
        all_page_nums = sorted(set(
            (f.page_index + 1) for f in st.session_state.findings
            if f.page_index is not None
        ))
        all_types = sorted(set(f.type.value for f in st.session_state.findings))
        page_labels = [f"第 {p} 页" for p in all_page_nums]

        if "excluded_rules" not in st.session_state:
            st.session_state.excluded_rules = []
        if "excluded_pages" not in st.session_state:
            st.session_state.excluded_pages = []
        if "filter_types" not in st.session_state:
            st.session_state.filter_types = all_types

        with st.form("exemption_form", clear_on_submit=False):
            # 类型过滤
            type_selection = st.multiselect(
                "按类型筛选",
                all_types,
                default=st.session_state.filter_types,
                placeholder="选择要显示的类型...",
            )
            # 规则豁免
            rule_selection = st.multiselect(
                "排除规则",
                all_rule_ids,
                default=st.session_state.excluded_rules,
                help="选中规则的结果将被隐藏",
                placeholder="选择要排除的规则...",
            )
            # 页面豁免
            page_selection = st.multiselect(
                "排除页面",
                page_labels,
                default=st.session_state.excluded_pages,
                help="选中页面的所有问题将被隐藏",
                placeholder="选择要排除的页面...",
            )

            applied = st.form_submit_button("✅ 应用过滤器", use_container_width=True)
            if applied:
                st.session_state.filter_types = type_selection
                st.session_state.excluded_rules = rule_selection
                st.session_state.excluded_pages = page_selection
                st.rerun()

        st.divider()

        # ── 下载报告 (使用当前过滤器) ──────────────────────
        filtered_download = _filtered_cache
        # 防御性守卫: doc 为 None 时跳过报告生成 (正常流不可达，防止 session_state 异常)
        if st.session_state.doc is None:
            st.warning("文档对象不可用，无法生成报告")
        else:
            # 批量模式使用专用标题，避免仅显示第一个文件的元数据
            if st.session_state.get("batch_mode") and st.session_state.get("batch_docs"):
                n_docs = len(st.session_state.batch_docs)
                report_title = f"批量文档审查报告 ({n_docs} 个文件)"
            else:
                report_title = "文档审查报告"
            html = generate_html_report(
                st.session_state.doc,
                filtered_download,
                title=report_title,
            )
            st.download_button(
                "📥 下载 HTML 报告",
                html,
                file_name=f"audit_report_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                mime="text/html",
                use_container_width=True,
            )

            report = generate_json_report(
                st.session_state.doc,
                filtered_download,
            )
            st.download_button(
                "📋 下载 JSON 报告",
                json.dumps(report, ensure_ascii=False, indent=2),
                file_name=f"audit_report_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                mime="application/json",
                use_container_width=True,
            )

        # ── 清除豁免 ─────────────────────────────────────
        if st.button("🔄 清除全部豁免", use_container_width=True,
                     help="恢复所有被豁免的规则、页面和问题"):
            st.session_state.excluded_rules = []
            st.session_state.excluded_pages = []
            st.session_state.exempted_finding_ids = set()
            st.rerun()

    st.divider()
    st.caption(f"v{__version__} · Python · 完全离线")

# ── 主内容区 ────────────────────────────────────────────────

st.title("📄 文档审查系统")

# ── 空状态 ──
# 用 sentinel 安全判断是否已上传文件 (替代 locals().get 隐式行为)
_has_upload = st.session_state.get("doc") is not None or st.session_state.get("batch_docs")
if not _has_upload:
    st.info("👈 请从左侧上传文档开始审查", icon="📤")
    with st.expander("📋 审查能力一览", expanded=True):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("""
            ### 内容结构
            - ✅ 标题页检测
            - ✅ 标题层级链路 (H1→H2→H3)
            - ✅ 图表编号连续性
            - ✅ 必含章节检查
            - ✅ 母版使用一致性
            """)
        with col_b:
            st.markdown("""
            ### 格式规范
            - ✅ 字体一致性 (Run 级检查)
            - ✅ 字号范围校验
            - ✅ 文本框对齐
            - ✅ 中英文混排空格
            - ✅ 母版/版式合规
            """)

        col_c, col_d = st.columns(2)
        with col_c:
            st.markdown("""
            ### 语言文字
            - ✅ LanguageTool 语法拼写 (三层自动降级)
            - ✅ 中英混合智能分段
            - ✅ 半导体术语一致性 (3 本术语表)
            - ✅ 中英标点检查
            """)
        with col_d:
            st.markdown("""
            ### 事实精准
            - ✅ 数值跨页一致性
            - ✅ 名称/缩写一致性
            - ✅ 缩写首次定义检查
            - ✅ rules.md 自定义规则引擎
            """)

# ── 首次加载后执行审查 ──
if st.session_state.audit_run and st.session_state.doc and not st.session_state.findings:
    with st.spinner("正在执行审查..."):
        st.session_state.findings = run_audit(st.session_state.doc)
    st.session_state.audit_run = False
    st.rerun()

# ── 显示结果 ──
if st.session_state.doc and st.session_state.findings:
    doc = st.session_state.doc

    # ── 过滤逻辑 ──
    filtered = _filtered_cache

    # 文档概览
    # ── 文档概览 ──
    if st.session_state.get("batch_mode"):
        batch_docs = st.session_state.get("batch_docs", [])
        total_pages = sum(len(d.pages) for d in batch_docs)
        st.subheader(f"📂 批量审查 — {len(batch_docs)} 个文件")
        st.caption(" | ".join(Path(d.source_path).name for d in batch_docs[:10]))
        if len(batch_docs) > 10:
            st.caption(f"... 还有 {len(batch_docs) - 10} 个")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("文件数", len(batch_docs))
        with c2:
            st.metric("总页数", total_pages)
        with c3:
            errors = sum(1 for f in filtered if f.severity == FindingSeverity.ERROR)
            st.metric("🔴 严重", errors)
        with c4:
            st.metric("📋 总计", len(filtered))
    else:
        st.subheader(f"📋 {Path(doc.source_path).name}")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("格式", doc.format.upper())
        with c2:
            st.metric("页数", len(doc.pages))
        with c3:
            errors = sum(1 for f in filtered if f.severity == FindingSeverity.ERROR)
            st.metric("🔴 严重", errors)
        with c4:
            st.metric("📋 总计", len(filtered))

    # ── 仪表盘 ──
    st.divider()
    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        st.caption("按严重度分布")
        sev_data = {
            "严重": sum(1 for f in filtered if f.severity == FindingSeverity.ERROR),
            "警告": sum(1 for f in filtered if f.severity == FindingSeverity.WARNING),
            "提示": sum(1 for f in filtered if f.severity == FindingSeverity.INFO),
        }
        st.bar_chart(sev_data, horizontal=True)

    with col_chart2:
        st.caption("按 Slide 分布")
        page_data = {}
        for f in filtered:
            label = f"p{f.page_index + 1}" if f.page_index is not None else "?"
            page_data[label] = page_data.get(label, 0) + 1
        if page_data:
            st.bar_chart(page_data, horizontal=True)

    # 按类型统计
    type_data = {}
    for f in filtered:
        t = f.type.value
        type_data[t] = type_data.get(t, 0) + 1
    if len(type_data) > 1:
        st.caption("按类型分布")
        cols = st.columns(len(type_data))
        for i, (t, count) in enumerate(sorted(type_data.items())):
            cols[i].metric(t, count)

    st.divider()

    # ── 审查发现列表 ──

    # 批量模式: 按文件汇总
    if st.session_state.get("batch_mode") and st.session_state.get("batch_findings"):
        st.divider()
        st.subheader("📊 按文件汇总")
        batch_data = []
        for fname, findings in st.session_state.batch_findings.items():
            batch_data.append({
                "文件": fname,
                "🔴 Error": sum(1 for f in findings if f.severity == FindingSeverity.ERROR),
                "🟡 Warning": sum(1 for f in findings if f.severity == FindingSeverity.WARNING),
                "🔵 Info": sum(1 for f in findings if f.severity == FindingSeverity.INFO),
                "总计": len(findings),
            })
        if batch_data:
            st.dataframe(
                batch_data,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "文件": st.column_config.TextColumn(width="large"),
                },
            )

    st.subheader(f"🔍 审查发现 ({len(filtered)} 项)")

    if not filtered:
        st.success("🎉 未发现任何问题！文档质量良好。")
    else:
        # ── 批量豁免按钮 ───────────────────────────────────
        info_ids = [f.id for f in filtered if f.severity == FindingSeverity.INFO]
        warning_ids = [f.id for f in filtered if f.severity == FindingSeverity.WARNING]

        bc1, bc2, bc3, bc4 = st.columns(4)
        with bc1:
            if info_ids and st.button(f"🟢 豁免全部 Info ({len(info_ids)})",
                                       use_container_width=True):
                st.session_state.exempted_finding_ids.update(info_ids)
                st.rerun()
        with bc2:
            if warning_ids and st.button(f"🟡 豁免全部 Warning ({len(warning_ids)})",
                                          use_container_width=True):
                st.session_state.exempted_finding_ids.update(warning_ids)
                st.rerun()
        with bc3:
            all_visible = [f.id for f in filtered]
            if all_visible and st.button(f"📋 豁免全部可见 ({len(all_visible)})",
                                          use_container_width=True):
                st.session_state.exempted_finding_ids.update(all_visible)
                st.rerun()
        with bc4:
            # 按类型批量豁免
            type_ids: dict[str, list[str]] = {}
            for f in filtered:
                type_ids.setdefault(f.type.value, []).append(f.id)
            # 使用 key 避免 selectbox 值在 rerun 后残留导致无限循环
            n_exempted = len(st.session_state.get("exempted_finding_ids", set()))
            type_choice = st.selectbox(
                "按类型豁免",
                ["—"] + [f"{t} ({len(ids)})" for t, ids in type_ids.items()],
                key=f"type_exempt_{n_exempted}",
                label_visibility="collapsed",
            )
            if type_choice != "—":
                chosen_type = type_choice.split(" (")[0]
                chosen_ids = type_ids.get(chosen_type, [])
                if chosen_ids:
                    st.session_state.exempted_finding_ids.update(chosen_ids)
                    st.rerun()

        # 按严重度排序: error → warning → info
        sev_order = {FindingSeverity.ERROR: 0, FindingSeverity.WARNING: 1, FindingSeverity.INFO: 2}
        sorted_findings = sorted(filtered, key=lambda f: sev_order.get(f.severity, 3))

        for finding in sorted_findings:
            sev_icon = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(
                finding.severity.value, "⚪"
            )
            type_label = {
                "structure": "结构", "format": "格式", "language": "语言",
                "terminology": "术语", "factual": "事实", "custom": "自定义",
            }.get(finding.type.value, finding.type.value)

            with st.expander(
                f"{sev_icon} [{type_label}] {finding.message[:80]}"
                f"{'...' if len(finding.message) > 80 else ''}",
                expanded=(finding.severity == FindingSeverity.ERROR),
            ):
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    if finding.location:
                        st.caption(f"📍 {finding.location}")
                    if finding.context:
                        st.code(finding.context, language=None)
                    if finding.suggestion:
                        st.info(f"💡 {finding.suggestion}")
                with col_b:
                    if finding.rule_id:
                        st.caption(f"规则: {finding.rule_id}")
                    st.caption(f"类型: {type_label}")
                    st.caption(f"严重度: {finding.severity.value}")
                    # 单条豁免按钮
                    if st.button("🚫 豁免", key=f"exempt_{finding.id}",
                                 help="从结果中隐藏此问题"):
                        exempted = st.session_state.exempted_finding_ids
                        exempted.add(finding.id)
                        st.session_state.exempted_finding_ids = exempted
                        st.rerun()

        # 豁免计数（循环外统一显示一次）
        exempted_from_display = sum(
            1 for f in st.session_state.findings
            if f.id in st.session_state.get("exempted_finding_ids", set())
        )
        if exempted_from_display > 0:
            st.caption(
                f"🛡️ 已豁免 {exempted_from_display} 个问题 | "
                f"显示 {len(filtered)} / {len(st.session_state.findings)}"
            )

    st.divider()
    st.caption(f"审查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
               f"格式: {doc.format.upper()} | "
               f"工具: DocAudit v{__version__}")
