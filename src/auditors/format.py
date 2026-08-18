"""格式审查器 — 字体/字号/颜色/对齐/母版一致性"""

import re
from collections import Counter

from src.auditors.base import BaseAuditor
from src.models.document import Document, Page, PageElement
from src.models.finding import AuditFinding, FindingSeverity, FindingType
from src.text_utils import is_cjk_char as _is_cjk_char

# ── 项目符号分类正则 (模块级预编译，避免每页重复编译) ──
# 符号类: • ◦ ▪ ▸ ◆ - *
_SYMBOL_BULLET_RE = re.compile(r"^\s*[•◦▪▸◆\-*]\s")
# 数字类: 1. 2) (1) ①
_NUMBERED_BULLET_RE = re.compile(r"^\s*(?:\d+[\.\)]\s|\(\d+\)\s|[①②③④⑤⑥⑦⑧⑨⑩]\s)")
# 字母类: a) A. i. (a)
_LETTERED_BULLET_RE = re.compile(r"^\s*(?:[a-zA-Z][\.\)]\s|\([a-zA-Z]\)\s)")


# ── WCAG 对比度 (FMT-008 表格底色 vs 字体色) ────────────────────────────
# 纯函数，无依赖，便于单元测试与配置驱动。


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """'#RRGGBB' 或 'RRGGBB' → (r, g, b) 整数元组。非法输入抛 ValueError。"""
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        raise ValueError(f"非法颜色值: {hex_color!r} (应为 6 位 hex)")
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        raise ValueError(f"非法颜色值: {hex_color!r} (应为 6 位 hex)") from None


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2.x 相对亮度 (0-1)。https://www.w3.org/TR/WCAG21/#dfn-relative-luminance"""

    def channel(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast_ratio(color_a: str, color_b: str) -> float:
    """两颜色 WCAG 对比度 (1-21)。参数顺序无关。"""
    lum_a = _relative_luminance(_hex_to_rgb(color_a))
    lum_b = _relative_luminance(_hex_to_rgb(color_b))
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


class FormatAuditor(BaseAuditor):
    """检查文档的格式规范"""

    # 默认配置 (对齐 rules.md FMT-001/FMT-002/FMT-003/FMT-004)
    DEFAULT_ALLOWED_FONTS = ["微软雅黑", "Arial", "Calibri", "Noto Sans SC"]
    DEFAULT_TITLE_SIZE_RANGE = (28, 40)  # pt  (rules.md FMT-002: 标题 28-40pt)
    DEFAULT_BODY_SIZE_RANGE = (12, 22)  # pt  (rules.md FMT-002: 正文 12-22pt)
    DEFAULT_ALIGNMENT_TOLERANCE = 5.0  # pt — 位置偏差容忍度
    DEFAULT_MAX_CHINESE_CHARS = 150  # 单段中文字数上限 (~3行×50字/行)
    DEFAULT_MAX_ENGLISH_CHARS = 300  # 单段英文字符上限 (~3行×100字符/行)
    DEFAULT_MAX_EXPLICIT_NEWLINES = 3  # 单段显式换行上限
    DEFAULT_MAX_CHARS_PER_PAGE = 200  # 单页总字数上限
    DEFAULT_MIN_CONTRAST = 4.5  # FMT-008 正文对比度阈值 (WCAG AA)
    DEFAULT_LARGE_TEXT_MIN_CONTRAST = 3.0  # FMT-008 大字对比度阈值 (WCAG AA 大字)
    DEFAULT_LARGE_TEXT_THRESHOLD = 18  # FMT-008 大字字号阈值 (pt)

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        cfg = config or {}
        self.allowed_fonts = cfg.get("allowed_fonts", self.DEFAULT_ALLOWED_FONTS)
        self.title_size_range = cfg.get("title_size_range", self.DEFAULT_TITLE_SIZE_RANGE)
        self.body_size_range = cfg.get("body_size_range", self.DEFAULT_BODY_SIZE_RANGE)
        self.alignment_tolerance = self.DEFAULT_ALIGNMENT_TOLERANCE
        try:
            self.max_font_types = int(cfg.get("max_font_types", 3))
        except (ValueError, TypeError):
            self.max_font_types = 3
        self.max_chinese_chars = cfg.get("max_chinese_chars", self.DEFAULT_MAX_CHINESE_CHARS)
        self.max_english_chars = cfg.get("max_english_chars", self.DEFAULT_MAX_ENGLISH_CHARS)
        self.max_explicit_newlines = cfg.get(
            "max_explicit_newlines", self.DEFAULT_MAX_EXPLICIT_NEWLINES
        )
        self.max_chars_per_page = cfg.get("max_chars_per_page", self.DEFAULT_MAX_CHARS_PER_PAGE)
        try:
            self.min_contrast = float(cfg.get("min_contrast", self.DEFAULT_MIN_CONTRAST))
        except (ValueError, TypeError):
            self.min_contrast = self.DEFAULT_MIN_CONTRAST
        try:
            self.large_text_min_contrast = float(
                cfg.get("large_text_min_contrast", self.DEFAULT_LARGE_TEXT_MIN_CONTRAST)
            )
        except (ValueError, TypeError):
            self.large_text_min_contrast = self.DEFAULT_LARGE_TEXT_MIN_CONTRAST
        try:
            self.large_text_threshold = float(
                cfg.get("large_text_threshold", self.DEFAULT_LARGE_TEXT_THRESHOLD)
            )
        except (ValueError, TypeError):
            self.large_text_threshold = self.DEFAULT_LARGE_TEXT_THRESHOLD
        # 流水线模式: 跳过已由 CustomRulesAuditor dispatch 的检查
        self._skip_checks: set[str] = set(cfg.get("_skip_checks", []))

    def audit(self, doc: Document) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        skip = self._skip_checks

        for page in doc.pages:
            findings.extend(self._check_font_consistency(page))
            findings.extend(self._check_font_size(page))
            findings.extend(self._check_alignment(page))
            findings.extend(self._check_paragraph_length(page))
            if "empty_placeholder" not in skip and doc.format == "pptx":
                findings.extend(self._check_empty_placeholders(page, doc))
            if "bullet_consistency" not in skip:
                findings.extend(self._check_bullet_consistency(page, doc))
            if "element_overflow" not in skip:
                findings.extend(self._check_element_overflow(page, doc))
            if "per_page_char_limit" not in skip:
                findings.extend(self._check_per_page_char_limit(page))
            if "table_contrast" not in skip:
                findings.extend(self._check_table_contrast(page, doc))

        # 全局字体统计
        findings.extend(self._check_global_font_consistency(doc))

        # PPTX 特有: 母版/版式合规检查
        if doc.format == "pptx":
            findings.extend(self._check_layout_consistency(doc))

        return findings

    # ── 字体检查 ─────────────────────────────────────────────

    def _check_font_consistency(self, page: Page) -> list[AuditFinding]:
        """检查每页字体是否在允许列表中。

        西文 (font_name / w:ascii / a:latin) 与中文 (font_name_east_asia /
        w:eastAsia / a:ea) 分别判定，避免中文正文字体检查半盲。
        按页+字体+作用域聚合，避免对每个 Run 产生独立 finding 导致报告泛滥。
        """
        findings: list[AuditFinding] = []
        # 按 (字体, 作用域) 聚合: → list of (run_text, shape_name)
        violations: dict[tuple[str, str], list[tuple[str, str | None]]] = {}

        for elem in page.flattened_elements:
            if elem.type != "text_frame":
                continue
            for para in elem.paragraphs:
                for run in para.runs:
                    if run.font_name and run.font_name not in self.allowed_fonts:
                        violations.setdefault((run.font_name, "latin"), []).append(
                            (run.text[:50], elem.shape_name)
                        )
                    # eastAsia 为 None 时跳过 (纯西文 run)
                    if (
                        run.font_name_east_asia
                        and run.font_name_east_asia not in self.allowed_fonts
                    ):
                        violations.setdefault((run.font_name_east_asia, "east_asia"), []).append(
                            (run.text[:50], elem.shape_name)
                        )

        for (font_name, scope), examples in violations.items():
            # 取前 3 个示例
            example_texts = [t for t, _ in examples[:3]]
            ctx = " | ".join(example_texts)
            scope_label = "中文（eastAsia）字体" if scope == "east_asia" else "西文（latin）字体"
            findings.append(
                AuditFinding(
                    type=FindingType.FORMAT,
                    severity=FindingSeverity.WARNING,
                    message=f"使用了非标准{scope_label}「{font_name}」({len(examples)} 处)",
                    rule_id="FMT-001",
                    page_index=page.index,
                    location=f"第 {page.slide_number or page.index + 1} 页",
                    context=f'"{ctx[:145]}"',
                    suggestion=f"建议使用标准字体: {', '.join(self.allowed_fonts[:4])}",
                    metadata={"font": font_name, "count": len(examples), "font_scope": scope},
                )
            )

        return findings

    def _check_global_font_consistency(self, doc: Document) -> list[AuditFinding]:
        """全局字体一致性统计"""
        findings: list[AuditFinding] = []
        font_counter: Counter = Counter()

        for page in doc.pages:
            for elem in page.flattened_elements:
                if elem.type != "text_frame":
                    continue
                for para in elem.paragraphs:
                    for run in para.runs:
                        if run.font_name:
                            font_counter[run.font_name] += 1

        if not font_counter:
            return findings

        max_fonts = self.max_font_types
        if len(font_counter) > max_fonts:
            top_fonts = font_counter.most_common(3)
            findings.append(
                AuditFinding(
                    type=FindingType.FORMAT,
                    severity=FindingSeverity.WARNING,
                    message=f"全文使用了 {len(font_counter)} 种不同字体，建议统一为 2-3 种",
                    rule_id="FMT-001",
                    location="全文",
                    suggestion=f"最常用的字体: {', '.join(f'{f}({c}次)' for f, c in top_fonts)}",
                    metadata={"font_distribution": dict(font_counter.most_common())},
                )
            )

        return findings

    # ── 字号检查 ─────────────────────────────────────────────

    def _check_font_size(self, page: Page) -> list[AuditFinding]:
        """检查字号是否在合理范围内"""
        findings: list[AuditFinding] = []
        for elem in page.flattened_elements:
            if elem.type != "text_frame":
                continue
            for para in elem.paragraphs:
                for run in para.runs:
                    if run.font_size is None:
                        continue
                    sz = run.font_size

                    if elem.is_title:
                        if sz < self.title_size_range[0]:
                            findings.append(
                                AuditFinding(
                                    type=FindingType.FORMAT,
                                    severity=FindingSeverity.WARNING,
                                    message=f"标题字号过小: {sz}pt（建议 {self.title_size_range[0]}-{self.title_size_range[1]}pt）",
                                    rule_id="FMT-002",
                                    page_index=page.index,
                                    location=f"第 {page.slide_number or page.index + 1} 页",
                                    context=f'"{run.text[:40]}" ({sz}pt)',
                                    suggestion=f"建议标题字号 ≥ {self.title_size_range[0]}pt",
                                )
                            )
                        elif sz > self.title_size_range[1]:
                            findings.append(
                                AuditFinding(
                                    type=FindingType.FORMAT,
                                    severity=FindingSeverity.WARNING,
                                    message=f"标题字号过大: {sz}pt（建议 {self.title_size_range[0]}-{self.title_size_range[1]}pt）",
                                    rule_id="FMT-002",
                                    page_index=page.index,
                                    location=f"第 {page.slide_number or page.index + 1} 页",
                                    context=f'"{run.text[:40]}" ({sz}pt)',
                                    suggestion=f"建议标题字号 ≤ {self.title_size_range[1]}pt",
                                )
                            )
                    else:
                        if sz < self.body_size_range[0]:
                            findings.append(
                                AuditFinding(
                                    type=FindingType.FORMAT,
                                    severity=FindingSeverity.WARNING,
                                    message=f"正文字号偏小: {sz}pt（建议 ≥ {self.body_size_range[0]}pt）",
                                    rule_id="FMT-002",
                                    page_index=page.index,
                                    location=f"第 {page.slide_number or page.index + 1} 页",
                                    context=f'"{run.text[:40]}" ({sz}pt)',
                                    suggestion=f"建议正文字号 ≥ {self.body_size_range[0]}pt",
                                )
                            )
                        elif sz > self.body_size_range[1]:
                            findings.append(
                                AuditFinding(
                                    type=FindingType.FORMAT,
                                    severity=FindingSeverity.WARNING,
                                    message=f"正文字号过大: {sz}pt（建议 ≤ {self.body_size_range[1]}pt）",
                                    rule_id="FMT-002",
                                    page_index=page.index,
                                    location=f"第 {page.slide_number or page.index + 1} 页",
                                    context=f'"{run.text[:40]}" ({sz}pt)',
                                    suggestion=f"建议正文字号 ≤ {self.body_size_range[1]}pt",
                                )
                            )

        return findings

    # ── 对齐检查 ─────────────────────────────────────────────

    def _check_alignment(self, page: Page) -> list[AuditFinding]:
        """检查同列文本框是否对齐"""
        findings: list[AuditFinding] = []

        # 按 left 位置聚类 (已过滤 left=None，避免 None 与 0 混淆)
        text_frames = [
            e for e in page.flattened_elements if e.type == "text_frame" and e.left is not None
        ]
        if len(text_frames) < 2:
            return findings

        sorted_frames = sorted(text_frames, key=lambda e: e.left)

        # 检查相近 left 值的文本框
        clustered: list[list[PageElement]] = []
        current_cluster = [sorted_frames[0]]

        for frame in sorted_frames[1:]:
            prev_left = current_cluster[-1].left
            curr_left = frame.left
            if abs(curr_left - prev_left) <= self.alignment_tolerance:
                current_cluster.append(frame)
            else:
                if len(current_cluster) >= 2:
                    clustered.append(current_cluster)
                current_cluster = [frame]

        if len(current_cluster) >= 2:
            clustered.append(current_cluster)

        # 检查每个聚类中的 top 对齐
        for cluster in clustered:
            tops = [f.top for f in cluster if f.top is not None]
            if len(tops) >= 2:
                avg_top = sum(tops) / len(tops)
                for i, f in enumerate(cluster):
                    if f.top is not None and abs(f.top - avg_top) > self.alignment_tolerance * 2:
                        findings.append(
                            AuditFinding(
                                type=FindingType.FORMAT,
                                severity=FindingSeverity.INFO,
                                message="文本框垂直位置不一致，建议对齐",
                                rule_id=None,  # 无对应 rules.md 规则，仅供参考
                                page_index=page.index,
                                location=f"第 {page.slide_number or page.index + 1} 页",
                                context=f'"{f.shape_name or "文本框"}" top={f.top:.0f}pt (同列其他 ~{avg_top:.0f}pt)',
                                suggestion="调整文本框 top 值使其与同列其他元素对齐",
                            )
                        )

        return findings

    # ── PPTX 版式合规 ────────────────────────────────────────

    def _check_layout_consistency(self, doc: Document) -> list[AuditFinding]:
        """检查幻灯片版式使用是否合理"""
        findings: list[AuditFinding] = []

        layout_usage: Counter = Counter()
        for page in doc.pages:
            layout_usage[page.layout_name or "未知版式"] += 1

        # 检查是否存在内容页使用了标题版式的情况
        # (简化: 如果标题版式被使用了多次 → 告警)
        title_layouts = [name for name in layout_usage if "标题" in name]
        for name in title_layouts:
            if layout_usage[name] > 1:
                findings.append(
                    AuditFinding(
                        type=FindingType.FORMAT,
                        severity=FindingSeverity.INFO,
                        message=f"标题版式「{name}」被使用了 {layout_usage[name]} 次，建议只用于封面",
                        location="全文",
                        suggestion="内容页请使用「标题和内容」或「仅内容」版式",
                    )
                )

        return findings

    # ── 段落长度检查 ─────────────────────────────────────────

    def _check_paragraph_length(self, page: Page) -> list[AuditFinding]:
        """检查单段是否超过 3 行。

        判断依据（任一超标即告警）：
        1. 显式换行符 >= max_explicit_newlines
        2. 中文字符数 >= max_chinese_chars
        3. 英文段落总字符数 >= max_english_chars
        """
        findings: list[AuditFinding] = []
        page_label = f"第 {page.slide_number or page.index + 1} 页"

        for elem in page.flattened_elements:
            if elem.type != "text_frame":
                continue
            for para in elem.paragraphs:
                text = para.text
                if not text.strip():
                    continue

                newline_count = text.count("\n")
                chinese_chars = sum(1 for c in text if _is_cjk_char(c))
                total_len = len(text)
                english_chars = total_len - chinese_chars
                reasons: list[str] = []

                if newline_count >= self.max_explicit_newlines:
                    reasons.append(
                        f"显式换行 {newline_count} 行 (上限 {self.max_explicit_newlines})"
                    )
                if chinese_chars >= self.max_chinese_chars:
                    reasons.append(f"中文字 {chinese_chars} 个 (上限 {self.max_chinese_chars})")
                if english_chars >= self.max_english_chars:
                    reasons.append(f"英文字符 {english_chars} 个 (上限 {self.max_english_chars})")

                if reasons:
                    preview = text[:80].replace("\n", "\\n")
                    findings.append(
                        AuditFinding(
                            type=FindingType.FORMAT,
                            severity=FindingSeverity.WARNING,
                            message=f"段落过长 (超过3行): {'; '.join(reasons)}",
                            rule_id="FMT-004",
                            page_index=page.index,
                            location=page_label,
                            context=preview + ("..." if len(text) > 80 else ""),
                            suggestion="将长段落拆分为多个短段落或精简为要点列表 (bullet points)",
                            metadata={
                                "newline_count": newline_count,
                                "chinese_chars": chinese_chars,
                                "total_length": total_len,
                            },
                        )
                    )

        return findings

    def _check_element_overflow(self, page: Page, doc: Document) -> list[AuditFinding]:
        """检查元素是否超出幻灯片边界 (inspired by intern's ELEMENT_OVERFLOW)。

        幻灯片尺寸优先从 PPTX 元数据获取，否则使用默认 16:9 widescreen (960pt x 540pt)。
        容差 5pt。
        """
        findings: list[AuditFinding] = []
        page_label = f"第 {page.slide_number or page.index + 1} 页"
        TOL = 5.0
        SW = doc.metadata.custom_properties.get("slide_width", 960) or 960
        SH = doc.metadata.custom_properties.get("slide_height", 540) or 540

        for elem in page.flattened_elements:
            if elem.left is None or elem.top is None:
                continue
            # 宽度/高度未知时跳过对应方向的溢出检测，避免误报
            r = elem.left + elem.width if elem.width is not None else None
            b = elem.top + elem.height if elem.height is not None else None
            issues = []
            if elem.left < -TOL:
                issues.append(f"left={elem.left:.0f}pt")
            if r is not None and r > SW + TOL:
                issues.append(f"right={r:.0f}pt > {SW}pt")
            if elem.top < -TOL:
                issues.append(f"top={elem.top:.0f}pt")
            if b is not None and b > SH + TOL:
                issues.append(f"bottom={b:.0f}pt > {SH}pt")

            if issues:
                w_str = f"{elem.width:.0f}" if elem.width is not None else "?"
                h_str = f"{elem.height:.0f}" if elem.height is not None else "?"
                findings.append(
                    AuditFinding(
                        type=FindingType.FORMAT,
                        severity=FindingSeverity.ERROR,
                        message=f"元素超出页面边界: {'; '.join(issues)}",
                        rule_id="FMT-005",
                        page_index=page.index,
                        location=page_label,
                        context=f"{elem.shape_name or elem.type} ({elem.left:.0f},{elem.top:.0f},{w_str}x{h_str})"[
                            :150
                        ],
                        suggestion="调整元素位置或大小，使其适应幻灯片边界",
                    )
                )

        return findings

    def _check_per_page_char_limit(
        self, page: Page, doc: Document | None = None
    ) -> list[AuditFinding]:
        """检查单页文本量是否超过上限 (FMT-003)。
        doc 参数仅为 CustomRulesAuditor per-page dispatch 接口一致性保留，未使用。
        """
        findings: list[AuditFinding] = []
        page_label = f"第 {page.slide_number or page.index + 1} 页"

        total_chars = sum(
            len(p.text)
            for e in page.flattened_elements
            if e.type == "text_frame"
            for p in e.paragraphs
        )
        # 也计入表格中的文本
        total_chars += sum(
            len(cell.text)
            for e in page.flattened_elements
            if e.type == "table"
            for row in e.tables
            for cell in row
        )

        if total_chars > self.max_chars_per_page:
            findings.append(
                AuditFinding(
                    type=FindingType.FORMAT,
                    severity=FindingSeverity.WARNING,
                    message=f"单页文本量过大: {total_chars} 字 (上限 {self.max_chars_per_page})",
                    rule_id="FMT-003",
                    page_index=page.index,
                    location=page_label,
                    context=f"共 {total_chars} 个字符",
                    suggestion="精简文本内容或拆分为多页，确保每页信息密度合理",
                    metadata={"total_chars": total_chars, "limit": self.max_chars_per_page},
                )
            )

        return findings

    def _check_table_contrast(self, page: Page, doc: Document | None = None) -> list[AuditFinding]:
        """检查表格单元格底色与字体颜色对比度 (FMT-008)。

        规则: 深色底色配浅色文字、浅色底色配深色文字 (WCAG AA)。
        判定: 底色 vs 字体色对比度 < 阈值 → 违规
          - 正文 (字号 < large_text_threshold): 4.5:1
          - 大字 (字号 >= large_text_threshold): 3.0:1
        降级: 底色/字体色缺失 (无填充/主题色/未提取到) 或空单元格 → 跳过，不误报。
        doc 参数仅为 CustomRulesAuditor per-page dispatch 接口一致性保留。
        """
        findings: list[AuditFinding] = []
        page_label = f"第 {page.slide_number or page.index + 1} 页"

        for elem in page.flattened_elements:
            if elem.type != "table":
                continue
            for row in elem.tables:
                for cell in row:
                    text = (cell.text or "").strip()
                    if not text:
                        continue  # 空单元格无对比度问题
                    if not cell.fill_color or not cell.font_color:
                        continue  # 缺色降级: 无填充/主题色/未提取到
                    try:
                        ratio = _contrast_ratio(cell.fill_color, cell.font_color)
                    except ValueError:
                        continue  # 非法颜色值 (转换器异常数据) — 跳过
                    if cell.font_size is not None and cell.font_size >= self.large_text_threshold:
                        threshold = self.large_text_min_contrast
                    else:
                        threshold = self.min_contrast
                    if ratio >= threshold:
                        continue

                    findings.append(
                        AuditFinding(
                            type=FindingType.FORMAT,
                            severity=FindingSeverity.WARNING,
                            message=(
                                f"表格单元格文字与底色对比度不足: {ratio:.1f}:1 "
                                f"(阈值 {threshold}:1)"
                            ),
                            rule_id="FMT-008",
                            page_index=page.index,
                            location=f"{page_label} [表格 第{cell.row + 1}行 第{cell.col + 1}列]",
                            # 前缀含行列坐标: dedup_key 用 context 哈希, 同页同文本的
                            # 不同单元格必须互异, 否则 deduplicate 折叠为一条 (信息丢失)
                            context=f"[{cell.row + 1}行 {cell.col + 1}列] {text[:85]}",
                            suggestion=(
                                "深色底色配浅色文字、浅色底色配深色文字，"
                                f"确保对比度不低于 {threshold}:1"
                            ),
                            metadata={
                                "cell": (cell.row, cell.col),
                                "fill_color": cell.fill_color,
                                "font_color": cell.font_color,
                                "ratio": round(ratio, 2),
                                "threshold": threshold,
                            },
                        )
                    )

        return findings

    def _check_empty_placeholders(self, page: Page, doc: Document) -> list[AuditFinding]:
        """检查空占位符/空白文本框 (inspired by intern's EMPTY_TEXT_BOX rule + UpSlide)。

        检测 PPTX 中未填充内容的占位符，避免残留空白模板区域。
        """
        findings: list[AuditFinding] = []
        page_label = f"第 {page.slide_number or page.index + 1} 页"

        for elem in page.flattened_elements:
            if elem.type != "text_frame":
                continue
            if not elem.is_placeholder:
                continue
            # 检查是否所有段落都为空
            has_content = any(p.text.strip() for p in elem.paragraphs)
            if has_content:
                continue

            placeholder_type = ""
            if elem.is_title:
                placeholder_type = "标题"
            elif elem.is_body:
                placeholder_type = "正文"
            else:
                placeholder_type = "通用"

            findings.append(
                AuditFinding(
                    type=FindingType.FORMAT,
                    severity=FindingSeverity.WARNING,
                    message=f"检测到空的{placeholder_type}占位符，建议填入内容或删除",
                    rule_id="FMT-006",
                    page_index=page.index,
                    location=page_label,
                    context=f"{elem.shape_name or '占位符'} ({placeholder_type})",
                    suggestion="在该占位符中填入相应内容，或从幻灯片版式中删除此占位符",
                    metadata={"shape_name": elem.shape_name, "placeholder_type": placeholder_type},
                )
            )

        return findings

    def _check_bullet_consistency(self, page: Page, doc: Document) -> list[AuditFinding]:
        """检查项目符号样式一致性 (inspired by intern's BULLET rules)。

        检测同一页内是否混用了不同类型的项目符号（如实心圆点 + 数字编号 + 字母编号）。
        """
        findings: list[AuditFinding] = []
        page_label = f"第 {page.slide_number or page.index + 1} 页"

        categories_found: set[str] = set()
        example_texts: dict[str, str] = {}

        for elem in page.flattened_elements:
            if elem.type != "text_frame":
                continue
            for para in elem.paragraphs:
                text = para.text
                if not text.strip():
                    continue
                if _SYMBOL_BULLET_RE.match(text):
                    if "symbol" not in example_texts:
                        example_texts["symbol"] = text[:50].strip()
                    categories_found.add("symbol")
                elif _NUMBERED_BULLET_RE.match(text):
                    if "numbered" not in example_texts:
                        example_texts["numbered"] = text[:50].strip()
                    categories_found.add("numbered")
                elif _LETTERED_BULLET_RE.match(text):
                    if "lettered" not in example_texts:
                        example_texts["lettered"] = text[:50].strip()
                    categories_found.add("lettered")

        # 如果同一页内出现了多种类型的项目符号 → 报告
        if len(categories_found) >= 2:
            cat_names = {
                "symbol": "符号(•-*)",
                "numbered": "数字(1. 2.)",
                "lettered": "字母(a) i.)",
            }
            found_names = [cat_names.get(c, c) for c in sorted(categories_found)]
            examples = " | ".join(example_texts.get(c, "") for c in sorted(categories_found))
            findings.append(
                AuditFinding(
                    type=FindingType.FORMAT,
                    severity=FindingSeverity.INFO,
                    message=f"该页混用了多种项目符号样式: {', '.join(found_names)}",
                    rule_id="FMT-007",
                    page_index=page.index,
                    location=page_label,
                    context=examples[:150],
                    suggestion="建议统一该页的项目符号样式，选择一种并全文保持一致",
                    metadata={"bullet_categories": sorted(categories_found)},
                )
            )

        return findings
