"""文档审查系统 — Streamlit Web UI

本地离线文档审查工具，支持 PPTX/DOCX/PDF/Markdown。
审查维度：内容结构 · 格式规范 · 语言文字 · 事实精准 · 自定义规则
"""

import html as _html  # 别名: app.py 中 html 变量被报告字符串占用，避免遮蔽模块
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
from src.engines.exemptions import (
    DEFAULT_EXEMPTION_FILE,
    load_exemptions,
    save_exemptions,
)
from src.engines.pipeline import build_report_context, find_converter, run_auditors
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity
from src.reporters.csv_reporter import generate_csv_report
from src.reporters.html_reporter import generate_html_report
from src.reporters.json_reporter import generate_json_report
from src.reporters.sarif_reporter import generate_sarif_report

# 豁免持久化文件名 (工作目录下；可入库供团队共享)
EXEMPTION_FILE = DEFAULT_EXEMPTION_FILE


_MD_META_RE = re.compile(r"([\\`*_{}\[\]()#+!|>~<])")


def _md_safe(text) -> str:
    """中和 Markdown 元字符（2026-10-29 深度审查 P2）。

    Streamlit 的 expander 标签 / st.caption / st.info 都会按 Markdown 渲染；
    仅 html.escape 不足以阻止文档文本里的 `![x](http://外部地址)` 让浏览器
    主动外联（违反"完全离线、零上报"红线）。转义后按纯文本显示。
    """
    return _MD_META_RE.sub(r"\\\1", str(text or ""))


def _apply_filters(findings: list[AuditFinding], state=None) -> list[AuditFinding]:
    """根据会话状态中的过滤器设置，返回过滤后的 findings 列表。

    state: 可选状态字典 (便于单测)；为 None 时读取 st.session_state。
    """
    ss = st.session_state if state is None else state

    # 严重度过滤
    severity_active = []
    if ss.get("filter_error", True):
        severity_active.append(FindingSeverity.ERROR)
    if ss.get("filter_warning", True):
        severity_active.append(FindingSeverity.WARNING)
    if ss.get("filter_info", False):
        severity_active.append(FindingSeverity.INFO)

    # 规则豁免
    excluded_rules = set(ss.get("excluded_rules", []))

    # 页面豁免
    excluded_page_labels = ss.get("excluded_pages", [])
    # 批量模式: 标签可带 "[文件] 第 N 页"；单文件模式保持 "第 N 页"。
    excluded_page_keys: set[tuple[str | None, int]] = set()
    for label in excluded_page_labels:
        m = re.search(r"第\s*(\d+)\s*页", str(label))
        if not m:
            m = re.search(r"\d+", str(label))
        if not m:
            continue
        page_no = int(m.group(1) if m.lastindex else m.group(0))
        source = None
        if str(label).startswith("[") and "]" in str(label):
            source = str(label)[1 : str(label).index("]")]
        excluded_page_keys.add((source, page_no))

    # 单条豁免
    exempted_ids = ss.get("exempted_finding_ids", set())

    # 类型过滤
    type_filter = ss.get("filter_types", [])

    return [
        f
        for f in findings
        if f.severity in severity_active
        and (not type_filter or f.type.value in type_filter)
        and (f.rule_id not in excluded_rules)
        and not (
            f.page_index is not None
            and (
                (None, f.page_index + 1) in excluded_page_keys
                or (
                    (f.metadata or {}).get("source_file"),
                    f.page_index + 1,
                )
                in excluded_page_keys
            )
        )
        and (f.exemption_key not in exempted_ids)
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
if "audit_completed" not in st.session_state:
    # 与 audit_run 分离: 审查完成后即使 findings=[] (干净文档) 也必须渲染结果页。
    st.session_state.audit_completed = False
if "audit_progress" not in st.session_state:
    st.session_state.audit_progress = {}
if "audit_context" not in st.session_state:
    # 质量分 + 覆盖/降级声明（build_report_context 结果）；无审查结果时为 None
    st.session_state.audit_context = None
if "exempted_finding_ids" not in st.session_state:
    # 启动时自动载入工作目录的 .docauditignore（跨会话复用误报豁免）
    st.session_state.exempted_finding_ids = load_exemptions(EXEMPTION_FILE)
# 批量模式
if "batch_mode" not in st.session_state:
    st.session_state.batch_mode = False
if "batch_docs" not in st.session_state:
    st.session_state.batch_docs = []
if "batch_findings" not in st.session_state:
    st.session_state.batch_findings = {}  # filename → list[findings]

# 注: 过滤结果在 sidebar 过滤器 widget 渲染完成后计算并存入 session_state["_filtered_cache"]
# (P5 修复: 预计算会导致 checkbox 勾选"滞后一拍"，主区显示旧结果)


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
        else:
            # L2: 临时文件名不应进入 UI/报告 — 覆写为原始上传文件名
            doc.source_path = uploaded_file.name
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


def _safe_folder_path(folder_path: str) -> Path | None:
    """把用户输入的文件夹路径解析为绝对路径；非法/越界路径返回 None。

    安全（路径沙箱 + CodeQL py/path-injection 硬化）：
    - 先拒绝含 ``..`` 的路径段（Path.parts 判断，非子串）；
    - ``expanduser().resolve()`` 归一化（符号链接/相对路径/``~``）；
    - 解析后仍必须是已存在的目录，否则返回 None。
    返回值是**已归一化的绝对路径**，后续文件系统操作只使用它。
    """
    raw = Path(folder_path)
    if ".." in raw.parts or not str(folder_path).strip():
        return None
    try:
        resolved = raw.expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    return resolved if resolved.is_dir() else None


def scan_folder(folder_path: str) -> list[Path]:
    """扫描文件夹，返回所有支持的文件路径。

    安全 (路径沙箱): 拒绝包含 ".." 路径段 (Path.parts 判断) 与非目录路径；
    仅扫描单层，不递归子目录。
    """
    from src.engines.pipeline import SUPPORTED_EXTENSIONS

    folder = _safe_folder_path(folder_path)
    if folder is None:
        return []
    # 先过滤再排序，避免对非文档条目排序
    files = sorted(
        f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    return files


def _paginate(items: list, page: int, page_size: int = 100) -> tuple[list, int, int]:
    """分页切片 — 返回 (当前页条目, 收敛后的页码(1-based), 总页数)。

    把页码收敛进有效范围 (上传新文件/豁免后条目变少时不越界)。
    """
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    current = min(max(1, page), total_pages)
    start = (current - 1) * page_size
    return items[start : start + page_size], current, total_pages


def _reset_batch_state() -> None:
    """重置审查状态和过滤器（新文件上传时调用）。

    豁免键（exempted_finding_ids）不重置为空集合：它由 finding 内容派生、跨审查
    稳定，且启动时已从 `.docauditignore` 载入团队基线。旧实现一律置空，导致
    "启动自动载入豁免" 在上传后立即失效 —— Web UI 永远用不上该文件
    （2026-11 审查）。这里改为重新从文件载入，语义等价于"沿用基线"。
    """
    st.session_state.findings = []
    st.session_state.doc = None
    st.session_state.audit_completed = False
    st.session_state.audit_progress = {}
    st.session_state.audit_context = None
    st.session_state.exempted_finding_ids = load_exemptions(EXEMPTION_FILE)
    st.session_state.findings_page = 1  # 新文件从第 1 页开始
    st.session_state.batch_docs = []
    st.session_state.batch_findings = {}
    # 清除过滤器状态，避免旧规则/页面排除被应用到新文件
    st.session_state.excluded_rules = []
    st.session_state.excluded_pages = []
    st.session_state.filter_types = []


def _exempt_ids(ids) -> None:
    """豁免指定 finding id 列表 — 整体赋值 session_state (保持一致风格，避免原地 update)。"""
    st.session_state.exempted_finding_ids = set(
        st.session_state.get("exempted_finding_ids", set())
    ) | set(ids)


def _config_mtime() -> float:
    """rules.md + glossary/*.yaml + vocab/*.txt 的最大 mtime（审计器缓存键）。"""
    base = Path(__file__).parent
    paths = [base / "rules.md"]
    paths += list((base / "glossary").glob("*.yaml"))
    paths += list((base / "vocab").glob("*.txt"))
    mtimes = [p.stat().st_mtime for p in paths if p.exists()]
    return max(mtimes) if mtimes else 0.0


def _rules_mtime() -> float:
    """向后兼容别名（旧测试/调用）；实际用 _config_mtime。"""
    return _config_mtime()


@st.cache_resource(show_spinner=False)
def _get_auditors(rules_mtime: float | None = None):
    """构建全部审计器 (app.py 和批量审查共用)。

    使用 @st.cache_resource 缓存 (key 含 rules_mtime 参数)。
    rules.md 修改后 mtime 变化 → 自动重建审计器 (配置热更新 M7)。
    rules_mtime 为 None 时在函数内计算 (便于显式传值/测试注入)。
    """
    from src.engines.pipeline import build_auditors

    base = Path(__file__).parent
    if rules_mtime is None:
        rules_mtime = _rules_mtime()
    return build_auditors(
        str(base / "rules.md"),
        str(base / "glossary"),
        str(base / "vocab"),
    )


def _batch_file_key(f, index: int, used_keys: set[str]) -> str:
    """生成批量文件的唯一字典 key (P8 防同名覆盖)。

    - Path 对象: 用完整路径 str(path)
    - 上传文件: 用文件名，同名冲突时加序号兜底 (name#index)
    used_keys: 已使用 key 集合 (调用方维护，用于同名检测)。
    """
    if hasattr(f, "getvalue"):
        base = getattr(f, "name", f"上传文件{index + 1}")
        key = base if base not in used_keys else f"{base}#{index + 1}"
    else:
        key = str(Path(f))
    used_keys.add(key)
    return key


def _batch_context(docs: list, file_count: int, findings: list) -> dict:
    """批量聚合的 score/coverage context（与单文件 build_report_context 同源口径）。

    ``complete`` 反映是否有文件转换/审查失败：批量结果不完整时必须如实声明，
    否则 Web UI 会把"部分文件没审"显示成"审查完整"（2026-11 reaudit S9）。
    """
    from src.engines.scoring import compute_score

    pages = sum(len(getattr(d, "pages", []) or []) for d in docs)
    return {
        "score": compute_score(findings, pages),
        "coverage": {
            "format": "batch",
            "pages": pages,
            "complete": len(docs) == file_count,
            "language_backend": None,
            "notes": [
                f"批量模式: {len(docs)} 个文件 / {pages} 页",
                "语言检查后端与格式能力因文件而异，详见各文件审查报告",
            ],
        },
    }


def _run_batch_audit(files: list) -> None:
    """批量审查：转换 + 审查所有文件。支持 StreamlitUploadedFile 和 Path。"""
    from src.engines.pipeline import run_auditors

    auditors = _get_auditors(_config_mtime())

    progress_bar = st.empty().progress(0, "批量审查中...")
    docs = []
    all_findings_dict: dict[str, list] = {}
    used_keys: set[str] = set()

    for i, f in enumerate(files):
        # 文件唯一 key: Path 用完整路径，上传文件用 name+序号兜底 (P8 防同名覆盖)
        fkey = _batch_file_key(f, i, used_keys)
        display_name = Path(fkey).name

        progress_bar.progress(
            (i + 0.3) / len(files), f"解析: {display_name} ({i + 1}/{len(files)})"
        )

        # 转换
        try:
            if hasattr(f, "getvalue"):
                doc = convert_file(f)
            else:
                doc = convert_file_path(f)
        except Exception as e:
            st.warning(f"转换失败: {display_name} — {e}")
            continue

        if doc is None:
            st.warning(f"不支持的文件: {display_name}")
            continue

        docs.append(doc)

        # 审查
        progress_bar.progress(
            (i + 0.6) / len(files), f"审查: {display_name} ({i + 1}/{len(files)})"
        )
        try:
            findings = run_auditors(doc, auditors)
            all_findings_dict[fkey] = findings
        except Exception as e:
            st.warning(f"审查失败: {display_name} — {e}")
            all_findings_dict[fkey] = []

        progress_bar.progress((i + 1) / len(files))

    progress_bar.empty()
    st.session_state.batch_docs = docs
    st.session_state.batch_findings = all_findings_dict

    # 汇总所有 findings 到一个列表（主视图使用）
    # 使用 dataclasses.replace 创建新实例，避免共享可变状态
    from dataclasses import replace as _dc_replace

    combined = []
    for fkey, findings in all_findings_dict.items():
        for fd in findings:
            # 来源只写 metadata：exemption_key 已含来源，location 保持原始文本
            # （否则 UI/CLI 因 location 改写方式不同而键不一致，2026-10-29 审查）
            new_metadata = dict(fd.metadata or {})
            new_metadata["source_file"] = fkey
            combined.append(_dc_replace(fd, metadata=new_metadata))
    st.session_state.findings = combined
    # 批量聚合质量分 + 覆盖声明（缺失时 Web UI 批量模式没有 I 维度显示 — reaudit S9）
    st.session_state.audit_context = _batch_context(docs, len(files), combined)
    st.session_state.findings_page = 1  # 批量审查结果从第 1 页开始
    st.session_state.doc = docs[0] if docs else None
    # 批量审查完成标记: docs 为空 (全部失败) 时不进入结果页, 由调用方提示错误。
    st.session_state.audit_completed = bool(docs)


# ── 审查执行 ────────────────────────────────────────────────


def run_audit(doc: Document) -> list[AuditFinding]:
    """执行全部审查器，返回发现列表"""
    auditors = _get_auditors(_config_mtime())
    progress_bar = st.empty().progress(0, "开始审查...")

    def on_progress(name, i, total):
        if name == "完成":
            progress_bar.progress(1.0, "审查完成 ✓")
        else:
            progress_bar.progress((i + 0.5) / total, f"正在执行: {name} ({i + 1}/{total})")

    findings = run_auditors(doc, auditors, on_progress=on_progress)
    # 质量分 + 覆盖/降级声明（与 CLI/HTML/JSON 同一 build_report_context）
    st.session_state.audit_context = build_report_context(doc, auditors, findings)
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
            key="folder_path",
        )
        if folder_path:
            # 路径沙箱: 统一经 _safe_folder_path 归一化（拒绝 '..'、非目录、空串），
            # 后续只使用归一化后的绝对路径（CodeQL py/path-injection 硬化，2026-11）
            folder_files: list = []
            safe_folder = _safe_folder_path(folder_path)
            if safe_folder is None:
                st.error("文件夹不存在、不是目录或路径非法（不允许 '..' 跳转）。")
            else:
                folder_files = scan_folder(str(safe_folder))
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

    if st.session_state.get("audit_completed") and st.session_state.get("doc") is not None:
        st.subheader("📊 审查结果")
        errors = sum(1 for f in st.session_state.findings if f.severity == FindingSeverity.ERROR)
        warnings = sum(
            1 for f in st.session_state.findings if f.severity == FindingSeverity.WARNING
        )
        infos = sum(1 for f in st.session_state.findings if f.severity == FindingSeverity.INFO)

        st.metric("🔴 严重问题", errors)
        st.metric("🟡 警告", warnings)
        st.metric("🔵 提示", infos)

        st.divider()

        st.subheader("🎛️ 过滤器")
        # 严重度 — 即时生效 (checkbox 体验好)；显式 key: 用户勾选后 session_state 立即同步
        for key, label, default in [
            ("filter_error", "严重 (Error)", True),
            ("filter_warning", "警告 (Warning)", True),
            ("filter_info", "提示 (Info)", False),
        ]:
            if key not in st.session_state:
                st.session_state[key] = default
            st.checkbox(label, key=key)

        # ── 豁免设置 (表单批量提交) ──────────────────────
        st.divider()
        st.subheader("🛡️ 豁免")
        st.caption("选择后点击「应用」生效，避免反复刷新")

        all_rule_ids = sorted(set(f.rule_id for f in st.session_state.findings if f.rule_id))
        all_types = sorted(set(f.type.value for f in st.session_state.findings))
        # 批量模式按 (文件, 页码) 生成标签，避免"排除第 2 页"误伤所有文件。
        page_labels = sorted(
            {
                (
                    f"[{(f.metadata or {}).get('source_file')}] 第 {f.page_index + 1} 页"
                    if (f.metadata or {}).get("source_file")
                    else f"第 {f.page_index + 1} 页"
                )
                for f in st.session_state.findings
                if f.page_index is not None
            }
        )

        if "excluded_rules" not in st.session_state:
            st.session_state.excluded_rules = []
        if "excluded_pages" not in st.session_state:
            st.session_state.excluded_pages = []
        if "filter_types" not in st.session_state:
            st.session_state.filter_types = all_types

        with st.form("exemption_form", clear_on_submit=False):
            # 显式 key (P7): 提交时自动同步 session_state，清除按钮可重置 widget 状态；
            # 初始值由上方 state-init 经 session_state 提供 (传 default 会与 key 冲突告警)
            st.multiselect(
                "按类型筛选",
                all_types,
                placeholder="选择要显示的类型...",
                key="filter_types",
            )
            st.multiselect(
                "排除规则",
                all_rule_ids,
                help="选中规则的结果将被隐藏",
                placeholder="选择要排除的规则...",
                key="excluded_rules",
            )
            st.multiselect(
                "排除页面",
                page_labels,
                help="选中页面的所有问题将被隐藏",
                placeholder="选择要排除的页面...",
                key="excluded_pages",
            )

            st.form_submit_button("✅ 应用过滤器", use_container_width=True)
            # 表单提交自动触发 rerun，无需显式 st.rerun() (L4)；
            # 显式 key 的 form widget 提交时自动同步 session_state，无需手动赋值
            # (手动赋值会触发 "cannot be modified after the widget is instantiated" 异常)

        # ── 过滤计算 (widget 渲染之后，勾选/提交立即生效；结果存 session_state 避免重复计算) ──
        st.session_state["_filtered_cache"] = (
            _apply_filters(st.session_state.findings) if st.session_state.get("findings") else []
        )

        st.divider()

        # ── 下载报告 (使用当前过滤器) ──────────────────────
        filtered_download = st.session_state.get("_filtered_cache", [])
        # 防御性守卫: doc 为 None 时跳过报告生成 (正常流不可达，防止 session_state 异常)
        if st.session_state.doc is None:
            st.warning("文档对象不可用，无法生成报告")
        else:
            # 批量模式使用聚合元数据: 页数=sum(len(d.pages))，file_label=批量汇总
            # (P6 修复: 原实现取 docs[0] 的页数与 source，与合并 findings 不符)
            if st.session_state.get("batch_mode") and st.session_state.get("batch_docs"):
                n_docs = len(st.session_state.batch_docs)
                report_title = f"批量文档审查报告 ({n_docs} 个文件)"
                page_count = sum(len(d.pages) for d in st.session_state.batch_docs)
                file_label = f"批量 {n_docs} 个文件"
            else:
                report_title = "文档审查报告"
                page_count = None
                file_label = None
            html = generate_html_report(
                st.session_state.doc,
                filtered_download,
                title=report_title,
                file_label=file_label,
                page_count=page_count,
                # 批量聚合报告不含单一文件的页面几何 → 关闭缩略图避免误导
                show_thumbnails=not st.session_state.get("batch_mode"),
                score=(st.session_state.get("audit_context") or {}).get("score"),
                coverage=(st.session_state.get("audit_context") or {}).get("coverage"),
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
                score=(st.session_state.get("audit_context") or {}).get("score"),
                coverage=(st.session_state.get("audit_context") or {}).get("coverage"),
            )
            st.download_button(
                "📋 下载 JSON 报告",
                json.dumps(report, ensure_ascii=False, indent=2),
                file_name=f"audit_report_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                mime="application/json",
                use_container_width=True,
            )

            csv_text = generate_csv_report(filtered_download)
            st.download_button(
                "📊 下载 CSV 报告",
                # utf-8-sig BOM: Excel 直接打开不乱码
                "\ufeff" + csv_text,
                file_name=f"audit_report_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

            sarif_text = generate_sarif_report(
                st.session_state.doc,
                filtered_download,
            )
            st.download_button(
                "🔧 下载 SARIF 报告",
                sarif_text,
                file_name=f"audit_report_{datetime.now().strftime('%Y%m%d_%H%M')}.sarif",
                mime="application/sarif+json",
                use_container_width=True,
            )

        # ── 持久化豁免 (.docauditignore) ──────────────────
        _exempt_keys = st.session_state.get("exempted_finding_ids") or set()
        st.caption(f"💾 豁免: {len(_exempt_keys)} 条 · 文件 `{EXEMPTION_FILE}`")
        if st.button(
            "💾 保存豁免到 .docauditignore",
            use_container_width=True,
            help="把当前豁免写入工作目录的 .docauditignore，下次启动/CLI --exempt-file 自动生效",
        ):
            _saved = save_exemptions(
                EXEMPTION_FILE,
                _exempt_keys,
                st.session_state.get("findings") or [],
            )
            if _saved:
                st.success(f"已保存 {len(_exempt_keys)} 条豁免到 {EXEMPTION_FILE}")
            else:
                st.error(f"保存失败：无法写入 {EXEMPTION_FILE}（检查目录权限/磁盘空间）")

        # ── 清除豁免 ─────────────────────────────────────
        if st.button(
            "🔄 清除全部豁免",
            use_container_width=True,
            help="恢复所有被豁免的规则、页面和问题，并重置类型筛选",
        ):
            # 与 _reset_batch_state 同步重置对应 session_state key (含多选 widget 显式 key)。
            # 注意: 显式 key 的 widget 已实例化后不可用赋值重置 (会抛异常)，
            # 改用 del 使其回落到 state-init 的默认值 (空/全部类型)。
            for _k in ("excluded_rules", "excluded_pages", "filter_types"):
                if _k in st.session_state:
                    del st.session_state[_k]
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
            - ✅ 版式多样性检查
            """)
        with col_b:
            st.markdown("""
            ### 格式规范
            - ✅ 字体一致性 (Run 级检查)
            - ✅ 字号范围校验
            - ✅ 文本框对齐
            - ✅ 中英文混排空格
            - ✅ 版式使用合理性
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
            - ✅ 缩写首次定义 / 重复定义 / 先用后定义
            - ✅ 缩写定义后未再使用
            - ✅ rules.md 自定义规则引擎
            """)

# ── 首次加载后执行审查 ──
if (
    st.session_state.audit_run
    and st.session_state.doc
    and not st.session_state.get("audit_completed")
):
    with st.spinner("正在执行审查..."):
        st.session_state.findings = run_audit(st.session_state.doc)
    st.session_state.audit_completed = True
    st.session_state.audit_run = False
    st.session_state.findings_page = 1  # 新审查结果从第 1 页开始
    st.rerun()

# ── 显示结果 ──
# 注意: 不能用 findings 真值判断 — 干净文档 findings=[] 时也必须展示
# 0 问题摘要、过滤器和报告下载，否则用户会误以为审查没有执行。
if st.session_state.doc and st.session_state.get("audit_completed"):
    doc = st.session_state.doc

    # ── 过滤逻辑 (结果由 sidebar 计算并存入 session_state，P5 修复) ──
    filtered = st.session_state.get("_filtered_cache", [])

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

    # ── 质量分 + 审查范围声明（2026-11: 让"没问题"与"没查"可区分）──
    _ctx = st.session_state.get("audit_context") or {}
    _score = _ctx.get("score")
    _cov = _ctx.get("coverage")
    if _score:
        sc1, sc2 = st.columns([1, 2])
        with sc1:
            st.metric("质量分", f"{_score.get('score', '-')} / 100", f"等级 {_score.get('grade')}")
        with sc2:
            dims = " · ".join(
                f"{name} {info['score']}" for name, info in (_score.get("dimensions") or {}).items()
            )
            st.caption(f"分维度: {dims or '—'}")
    if _cov:
        status = "完整" if _cov.get("complete", True) else "不完整（有检查执行失败）"
        with st.expander(f"审查范围与可信度：{status}", expanded=False):
            for _note in _cov.get("notes", []):
                st.write(f"- {_note}")

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
            batch_data.append(
                {
                    "文件": fname,
                    "🔴 Error": sum(1 for f in findings if f.severity == FindingSeverity.ERROR),
                    "🟡 Warning": sum(1 for f in findings if f.severity == FindingSeverity.WARNING),
                    "🔵 Info": sum(1 for f in findings if f.severity == FindingSeverity.INFO),
                    "总计": len(findings),
                }
            )
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
        if st.session_state.findings:
            st.info("当前筛选/豁免条件下没有问题可显示；可调整左侧过滤器查看其余发现。")
        else:
            st.success("🎉 未发现任何问题！文档质量良好。")
    else:
        # ── 批量豁免按钮 ───────────────────────────────────
        info_ids = [f.exemption_key for f in filtered if f.severity == FindingSeverity.INFO]
        warning_ids = [f.exemption_key for f in filtered if f.severity == FindingSeverity.WARNING]

        bc1, bc2, bc3, bc4 = st.columns(4)
        with bc1:
            if info_ids and st.button(
                f"🟢 豁免全部 Info ({len(info_ids)})", use_container_width=True
            ):
                _exempt_ids(info_ids)
                st.rerun()
        with bc2:
            if warning_ids and st.button(
                f"🟡 豁免全部 Warning ({len(warning_ids)})", use_container_width=True
            ):
                _exempt_ids(warning_ids)
                st.rerun()
        with bc3:
            all_visible = [f.exemption_key for f in filtered]
            if all_visible and st.button(
                f"📋 豁免全部可见 ({len(all_visible)})", use_container_width=True
            ):
                _exempt_ids(all_visible)
                st.rerun()
        with bc4:
            # 按类型批量豁免
            type_ids: dict[str, list[str]] = {}
            for f in filtered:
                type_ids.setdefault(f.type.value, []).append(f.exemption_key)
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
                    _exempt_ids(chosen_ids)
                    st.rerun()

        # 按严重度排序: error → warning → info
        sev_order = {FindingSeverity.ERROR: 0, FindingSeverity.WARNING: 1, FindingSeverity.INFO: 2}
        sorted_findings = sorted(filtered, key=lambda f: sev_order.get(f.severity, 3))

        # 分页渲染 (2026-10-29): 数百条 finding 时一次渲染全部 expander 会显著拖慢页面
        page_size = 100
        visible_page, current_page, total_pages = _paginate(
            sorted_findings, st.session_state.get("findings_page", 1), page_size
        )
        start = (current_page - 1) * page_size
        if total_pages > 1:
            pcol1, pcol2, pcol3 = st.columns([1, 2, 1])
            with pcol1:
                if st.button(
                    "⬅️ 上一页",
                    disabled=current_page <= 1,
                    key="findings_prev_page",
                    use_container_width=True,
                ):
                    st.session_state.findings_page = current_page - 1
                    st.rerun()
            with pcol2:
                st.caption(
                    f"第 {current_page}/{total_pages} 页 · 每页 {page_size} 条 · "
                    f"共 {len(sorted_findings)} 条"
                )
            with pcol3:
                if st.button(
                    "下一页 ➡️",
                    disabled=current_page >= total_pages,
                    key="findings_next_page",
                    use_container_width=True,
                ):
                    st.session_state.findings_page = current_page + 1
                    st.rerun()

        for _idx, finding in enumerate(visible_page, start + 1):
            sev_icon = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(
                finding.severity.value, "⚪"
            )
            type_label = {
                "structure": "结构",
                "format": "格式",
                "language": "语言",
                "terminology": "术语",
                "factual": "事实",
                "custom": "自定义",
                "system": "系统",
            }.get(finding.type.value, finding.type.value)

            # 用户文本渲染前必须转义 (红线 #2) — Streamlit 默认转义 HTML，此处防御性转义
            _msg = _md_safe(_html.escape(finding.message or ""))
            with st.expander(
                f"{sev_icon} [{type_label}] {_msg[:80]}{'...' if len(_msg) > 80 else ''}",
                expanded=(finding.severity == FindingSeverity.ERROR),
            ):
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    _source = (finding.metadata or {}).get("source_file")
                    _loc = finding.location or ""
                    _display_loc = f"[{Path(_source).name}] {_loc}".strip() if _source else _loc
                    if _display_loc:
                        st.caption(f"📍 {_md_safe(_display_loc)}")
                    if finding.context:
                        st.code(finding.context, language=None)
                    if finding.suggestion:
                        st.info(f"💡 {_md_safe(finding.suggestion)}")
                with col_b:
                    if finding.rule_id:
                        st.caption(f"规则: {_md_safe(finding.rule_id)}")
                    st.caption(f"类型: {type_label}")
                    st.caption(f"严重度: {finding.severity.value}")
                    # 单条豁免按钮
                    if st.button(
                        "🚫 豁免",
                        key=f"exempt_{finding.exemption_key}_{_idx}",
                        help="从结果中隐藏此问题",
                    ):
                        _exempt_ids([finding.exemption_key])
                        st.rerun()

        # 豁免计数（循环外统一显示一次）
        exempted_from_display = sum(
            1
            for f in st.session_state.findings
            if f.exemption_key in st.session_state.get("exempted_finding_ids", set())
        )
        if exempted_from_display > 0:
            st.caption(
                f"🛡️ 已豁免 {exempted_from_display} 个问题 | "
                f"显示 {len(filtered)} / {len(st.session_state.findings)}"
            )

    st.divider()
    st.caption(
        f"审查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
        f"格式: {doc.format.upper()} | "
        f"工具: DocAudit v{__version__}"
    )
