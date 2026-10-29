"""格式审查器 — 字体/字号/颜色/对齐/母版一致性"""

import logging
import math
import re
from collections import Counter
from itertools import combinations

from src.auditors.base import BaseAuditor
from src.models.document import Document, Page
from src.models.finding import AuditFinding, FindingSeverity, FindingType
from src.text_utils import LETTERED_BULLET_RE as _LETTERED_BULLET_RE
from src.text_utils import NUMBERED_BULLET_RE as _NUMBERED_BULLET_RE
from src.text_utils import SYMBOL_BULLET_RE as _SYMBOL_BULLET_RE
from src.text_utils import is_cjk_char as _is_cjk_char

logger = logging.getLogger(__name__)


def _effective_latin_font(run) -> str | None:
    """优先使用继承解析后的 latin 字体；未解析的 +mj/+mn token 视为未知。"""
    name = run.effective_font_name or run.font_name
    if name and name.startswith("+"):
        return None
    return name


def _effective_ea_font(run) -> str | None:
    """优先使用继承解析后的 eastAsia 字体；未解析的 +mj/+mn token 视为未知。"""
    name = run.effective_font_name_east_asia or run.font_name_east_asia
    if name and name.startswith("+"):
        return None
    return name


def _effective_font_size(run) -> float | None:
    """优先使用继承解析后的字号。"""
    return run.effective_font_size if run.effective_font_size is not None else run.font_size


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


# ── 文本排版估算 (FMT-TEXT-OVERFLOW / FMT-TABLE-FIT 共用 SSOT) ──
# 说明：非渲染级估算。CJK 计 2 半角单位，半角单位宽 ≈ 0.5em，行高 ≈ 1.2em。


def _estimate_text_height(
    text: str, font_size: float, inner_w: float, line_spacing: float | None = None
) -> float:
    """估算一段文本在给定内宽下的高度 (pt)。"""
    units = 0.0
    explicit_lines = 1
    for ch in text:
        if ch == "\n":
            explicit_lines += 1
        elif _is_cjk_char(ch):
            units += 2.0
        elif ch.isspace():
            units += 0.5
        else:
            units += 1.0
    capacity = max(1.0, inner_w / (font_size * 0.5))
    lines = explicit_lines + max(0, math.ceil(units / capacity) - 1)
    if line_spacing and line_spacing > 5:
        line_height = line_spacing  # 固定行距 (pt)
    else:
        line_height = font_size * 1.2 * (line_spacing or 1.0)
    return lines * line_height


def _estimate_paragraphs_height(paragraphs, inner_w: float) -> float | None:
    """估算段落组高度 (pt)。任一段均无字号信息时返回 None (无法判定)。

    公式与 2026-10-29 FMT-TEXT-OVERFLOW 首版一致，此处收敛为单一实现。
    """
    estimated_h = 0.0
    has_size = False
    for para in paragraphs:
        text = para.text
        if not text.strip():
            continue
        sizes = [
            _effective_font_size(run) for run in para.runs if _effective_font_size(run) is not None
        ]
        if not sizes:
            continue
        has_size = True
        font_size = sum(sizes) / len(sizes)
        estimated_h += _estimate_text_height(text, font_size, inner_w, para.line_spacing)
        estimated_h += (para.space_before or 0.0) + (para.space_after or 0.0)
    return estimated_h if has_size else None


def _longest_unbreakable_token_width(text: str, font_size: float) -> float:
    """最长不可断词宽度 (pt)。CJK 可任意断行，不计入 token。"""
    best = 0.0
    current = 0.0
    for ch in text:
        if ch.isspace() or _is_cjk_char(ch):
            best = max(best, current)
            current = 0.0
        else:
            current += 1.0
    best = max(best, current)
    return best * font_size * 0.5


class FormatAuditor(BaseAuditor):
    """检查文档的格式规范"""

    # 默认配置 (对齐 rules.md FMT-001/FMT-002/FMT-003/FMT-004)
    DEFAULT_ALLOWED_FONTS = ["微软雅黑", "Arial", "Calibri", "Noto Sans SC"]
    DEFAULT_TITLE_SIZE_RANGE = (28, 44)  # pt  (rules.md FMT-002: 标题 28-44pt)
    DEFAULT_BODY_SIZE_RANGE = (12, 32)  # pt  (rules.md FMT-002: 正文 12-32pt)
    DEFAULT_ALIGNMENT_TOLERANCE = 5.0  # pt — 位置偏差容忍度
    # 表格 fit 估算默认字号 (单元格未写显式字号时)：PowerPoint 表格默认 18pt，
    # Word 正文默认 10.5pt。仅用于 FMT-TABLE-FIT 估算，不改写模型数据。
    DEFAULT_TABLE_FONT_SIZE_PPTX = 18.0
    DEFAULT_TABLE_FONT_SIZE_DOCX = 10.5
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
        # 2026-10-28: FMT-001/002/004 没有 check_type, 旧实现无条件执行 —
        # 即使用户从 rules.md 删除规则，仍会用默认值报错，违反"rules.md 是唯一入口"。
        # enabled_rule_ids=None 表示独立使用/未注入配置，保持全部检查 (向后兼容)。
        enabled = cfg.get("enabled_rule_ids")
        self.enabled_rule_ids: set[str] | None = set(enabled) if enabled is not None else None
        # rules.md 严重度声明驱动 (2026-09-06 审查 C-1): 无 check_type 的 format
        # 规则 (FMT-001/002/004) 不经 dispatch 严重度覆盖通道, 由 audit() 按
        # rule_id 统一覆盖 — rules.md 是严重度的唯一来源, 硬编码值仅为兜底。
        self.rule_severities: dict[str, FindingSeverity] = {}
        for _rid, _sev in (cfg.get("rule_severities") or {}).items():
            try:
                self.rule_severities[_rid] = FindingSeverity(str(_sev).lower())
            except ValueError:
                logger.warning("rule_severities 中 %s 的严重度无效: %s，忽略", _rid, _sev)

    def _rule_enabled(self, rule_id: str) -> bool:
        return self.enabled_rule_ids is None or rule_id in self.enabled_rule_ids

    def audit(self, doc: Document) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        skip = self._skip_checks
        # 2026-10-28: FMT-001/002/003 的阈值是幻灯片语义（标题 28-44pt、
        # 单页 200 字、品牌字体列表），不能直接套到 DOCX/PDF/MD。
        # 例：Word 的 Heading 1 通常 16pt、一页 300+ 字、宋体正文都是正常的。
        # PPTX 专属检查在 audit() 入口统一收敛；dispatch 型检查由
        # _DISPATCH 的 pptx_only 标志拦截。
        is_pptx = doc.format == "pptx"

        for page in doc.pages:
            if is_pptx:
                if self._rule_enabled("FMT-001"):
                    findings.extend(self._check_font_consistency(page))
                if self._rule_enabled("FMT-002"):
                    findings.extend(self._check_font_size(page))
                findings.extend(self._check_alignment(page))
                findings.extend(self._check_element_overlap(page, doc))
                findings.extend(self._check_safe_margin(page, doc))
                findings.extend(self._check_text_overflow(page, doc))
                findings.extend(self._check_image_quality(page, doc))
                findings.extend(self._check_chart_labeling(page, doc))
            if self._rule_enabled("FMT-004"):
                findings.extend(self._check_paragraph_length(page))
            if "empty_placeholder" not in skip and is_pptx:
                findings.extend(self._check_empty_placeholders(page, doc))
            if "bullet_consistency" not in skip:
                findings.extend(self._check_bullet_consistency(page, doc))
            if "element_overflow" not in skip and is_pptx:
                findings.extend(self._check_element_overflow(page, doc))
            if "per_page_char_limit" not in skip and is_pptx:
                findings.extend(self._check_per_page_char_limit(page))
            if "table_contrast" not in skip:
                findings.extend(self._check_table_contrast(page, doc))
            findings.extend(self._check_table_fit(page, doc))

        # 全局字体统计（PPTX 品牌字体语义）
        if is_pptx and self._rule_enabled("FMT-001"):
            findings.extend(self._check_global_font_consistency(doc))

        # PPTX 特有: 母版/版式/页脚合规检查 (内置提示，暂不占 26 条规则计数)
        if is_pptx:
            findings.extend(self._check_footer_consistency(doc))
            findings.extend(self._check_layout_consistency(doc))

        # rules.md 严重度统一覆盖 (2026-09-06 审查 C-1): FMT-001/002/004 等
        # 无 check_type 规则的 findings 严重度以 rules.md 声明为唯一来源
        if self.rule_severities:
            for f in findings:
                if f.rule_id in self.rule_severities:
                    f.severity = self.rule_severities[f.rule_id]

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
                    latin_font = _effective_latin_font(run)
                    if latin_font and latin_font not in self.allowed_fonts:
                        violations.setdefault((latin_font, "latin"), []).append(
                            (run.text[:50], elem.shape_name)
                        )
                    # eastAsia 为 None 时跳过 (纯西文 run)
                    ea_font = _effective_ea_font(run)
                    if ea_font and ea_font not in self.allowed_fonts:
                        violations.setdefault((ea_font, "east_asia"), []).append(
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
        """全局字体一致性统计。

        修复 (2026-08 审查 M4): 曾只统计 font_name (西文 latin)，忽略
        font_name_east_asia (中文 eastAsia) → 1 种 latin + N 种中文不触发。
        现以复合键 (font, scope) 统计，latin 与 eastAsia 分别计数。
        """
        findings: list[AuditFinding] = []
        # 复合键 (font, scope) → 计数 (latin 与 eastAsia 同名字体互不混淆)
        font_counter: Counter = Counter()

        for page in doc.pages:
            for elem in page.flattened_elements:
                if elem.type != "text_frame":
                    continue
                for para in elem.paragraphs:
                    for run in para.runs:
                        latin_font = _effective_latin_font(run)
                        ea_font = _effective_ea_font(run)
                        if latin_font:
                            font_counter[(latin_font, "latin")] += 1
                        if ea_font:
                            font_counter[(ea_font, "east_asia")] += 1

        if not font_counter:
            return findings

        max_fonts = self.max_font_types
        if len(font_counter) > max_fonts:
            top_fonts = font_counter.most_common(3)

            def _label(item: tuple[tuple[str, str], int]) -> str:
                (font, scope), count = item
                scope_label = "中文" if scope == "east_asia" else "西文"
                return f"{font}({scope_label})({count}次)"

            # 复合键 → "font/scope" 字符串键 (JSON 序列化安全)
            distribution = {
                f"{font}/{scope}": count for (font, scope), count in font_counter.items()
            }
            findings.append(
                AuditFinding(
                    type=FindingType.FORMAT,
                    severity=FindingSeverity.WARNING,
                    message=(
                        f"全文使用了 {len(font_counter)} 种不同字体（含中英文作用域），"
                        "建议统一为 2-3 种"
                    ),
                    rule_id="FMT-001",
                    location="全文",
                    suggestion="最常用的字体: " + ", ".join(_label(t) for t in top_fonts),
                    metadata={"font_distribution": distribution},
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
                    sz = _effective_font_size(run)
                    if sz is None:
                        continue

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
        """检查同页文本框的行/列对齐。

        2026-10-28 修复：旧实现按 left 聚类后直接比较 top，把标题
        (top=22) 与正文 (top=126) 当成"同列未对齐"，样例每页产生 2 条
        误报。现改为角色感知 + 成对判断：

        - 标题与正文是不同角色，禁止互比；
        - 同一行（水平分离、垂直重叠）比较 top 是否一致；
        - 同一列（左边界接近）比较宽度/右边界，不比较 top
          （上下堆叠的标题与正文 top 本来就应该不同）。
        """
        findings: list[AuditFinding] = []
        tol = self.alignment_tolerance

        # 已过滤 left/top=None，避免 None 与 0 混淆
        text_frames = [
            e
            for e in page.flattened_elements
            if e.type == "text_frame" and e.left is not None and e.top is not None
        ]
        if len(text_frames) < 2:
            return findings

        page_label = f"第 {page.slide_number or page.index + 1} 页"

        for first, second in combinations(text_frames, 2):
            # 标题与正文属于不同角色：它们的 top/height 本来就不同，
            # 不能作为"未对齐"证据。
            if bool(first.is_title) != bool(second.is_title):
                continue

            left_gap = abs(first.left - second.left)
            top_gap = abs(first.top - second.top)

            # ── 同一行：水平分离 + 垂直重叠 → 检查 top 是否一致 ──
            if left_gap > tol and top_gap > tol:
                first_h = first.height or 0.0
                second_h = second.height or 0.0
                min_h = min(first_h, second_h)
                if min_h <= 0:
                    continue
                # 水平方向也大幅重叠 → 更像"嵌套/覆盖"而非并排两栏，
                # 不作为"同一行未对齐"证据（样例中 TextBox 覆盖在
                # Content Placeholder 上即此形态）。
                if first.width is not None and second.width is not None:
                    h_overlap = min(first.left + first.width, second.left + second.width) - max(
                        first.left, second.left
                    )
                    min_w = min(first.width, second.width)
                    if min_w > 0 and h_overlap / min_w > 0.2:
                        continue
                overlap = min(first.top + first_h, second.top + second_h) - max(
                    first.top, second.top
                )
                if overlap / min_h < 0.5:
                    continue
                findings.append(
                    AuditFinding(
                        type=FindingType.FORMAT,
                        severity=FindingSeverity.INFO,
                        message="同一行文本框垂直位置不一致，建议对齐",
                        rule_id="FMT-ALIGN",
                        page_index=page.index,
                        location=page_label,
                        context=(
                            f'"{first.shape_name or "文本框"}" top={first.top:.0f}pt, '
                            f'"{second.shape_name or "文本框"}" top={second.top:.0f}pt'
                        ),
                        suggestion="将同一行文本框的 top 调整为一致，形成水平基线",
                        metadata={"tolerance": tol},
                    )
                )

            # ── 同一列：左边界接近 → 检查宽度/右边界是否一致 ──
            elif left_gap <= tol and top_gap > tol:
                if first.width is None or second.width is None:
                    continue
                width_gap = abs(first.width - second.width)
                right_gap = abs((first.left + first.width) - (second.left + second.width))
                if width_gap <= tol and right_gap <= tol:
                    continue
                findings.append(
                    AuditFinding(
                        type=FindingType.FORMAT,
                        severity=FindingSeverity.INFO,
                        message="同列文本框宽度或右边界不一致，建议对齐",
                        rule_id="FMT-ALIGN",
                        page_index=page.index,
                        location=page_label,
                        context=(
                            f'"{first.shape_name or "文本框"}" '
                            f"width={first.width:.0f}pt right={first.left + first.width:.0f}pt, "
                            f'"{second.shape_name or "文本框"}" '
                            f"width={second.width:.0f}pt right={second.left + second.width:.0f}pt"
                        ),
                        suggestion="统一同列文本框的宽度或右边界",
                        metadata={"tolerance": tol},
                    )
                )

        return findings

    @staticmethod
    def _bbox_contains(outer, inner, tol: float = 1.0) -> bool:
        """outer 是否包含 inner（容差 tol）。"""
        if None in (outer.left, outer.top, outer.width, outer.height):
            return False
        if None in (inner.left, inner.top, inner.width, inner.height):
            return False
        return (
            outer.left <= inner.left + tol
            and outer.top <= inner.top + tol
            and outer.left + outer.width >= inner.left + inner.width - tol
            and outer.top + outer.height >= inner.top + inner.height - tol
        )

    def _check_element_overlap(self, page: Page, doc: Document) -> list[AuditFinding]:
        """检查 PPTX 元素重叠 (2026-10-28)。

        保守策略:
        - 只比较高置信度的叶子元素 (文本框/图片/表格/图表)，不比较 group 容器；
        - 排除全屏背景 (面积 >= 80% 页面)；
        - 一个元素包含另一个 → 视为嵌套/叠加纹理，不报；
        - 交集面积 >= 较小元素 25% 才报，避免边缘擦碰误报。
        """
        findings: list[AuditFinding] = []
        page_label = f"第 {page.slide_number or page.index + 1} 页"
        SW = doc.metadata.custom_properties.get("slide_width", 960) or 960
        SH = doc.metadata.custom_properties.get("slide_height", 540) or 540
        slide_area = SW * SH

        def _has_content(e) -> bool:
            if e.type == "text_frame":
                return any(p.text.strip() for p in e.paragraphs)
            if e.type == "table":
                return any(cell.text.strip() for row in e.tables for cell in row)
            return True  # image/chart 视为有内容

        elements = [
            e
            for e in page.flattened_elements
            if e.type in ("text_frame", "table", "image", "chart")
            and _has_content(e)
            and e.left is not None
            and e.top is not None
            and e.width is not None
            and e.height is not None
            and e.width > 0
            and e.height > 0
        ]

        for first, second in combinations(elements, 2):
            first_area = first.width * first.height
            second_area = second.width * second.height
            if first_area >= slide_area * 0.8 or second_area >= slide_area * 0.8:
                continue
            if self._bbox_contains(first, second) or self._bbox_contains(second, first):
                continue

            x_overlap = min(first.left + first.width, second.left + second.width) - max(
                first.left, second.left
            )
            y_overlap = min(first.top + first.height, second.top + second.height) - max(
                first.top, second.top
            )
            if x_overlap <= 0 or y_overlap <= 0:
                continue
            overlap_area = x_overlap * y_overlap
            min_area = min(first_area, second_area)
            if min_area <= 0 or overlap_area / min_area < 0.25:
                continue

            findings.append(
                AuditFinding(
                    type=FindingType.FORMAT,
                    severity=FindingSeverity.INFO,
                    message="检测到元素重叠，可能影响可读性",
                    rule_id="FMT-OVERLAP",
                    page_index=page.index,
                    location=page_label,
                    context=(
                        f'"{first.shape_name or first.type}" 与 '
                        f'"{second.shape_name or second.type}" 重叠 '
                        f"{overlap_area / min_area:.0%}"
                    )[:150],
                    suggestion="调整元素位置/尺寸，或确认重叠是否为有意设计",
                    metadata={
                        "overlap_ratio": round(overlap_area / min_area, 3),
                        "first": first.shape_name or first.type,
                        "second": second.shape_name or second.type,
                    },
                )
            )

        return findings

    def _check_safe_margin(self, page: Page, doc: Document) -> list[AuditFinding]:
        """检查 PPTX 文本/表格是否过于贴近页面边缘 (2026-10-28)。

        仅检查文本框/表格，排除全屏背景；默认安全边距为页面宽高的 1%。
        """
        findings: list[AuditFinding] = []
        page_label = f"第 {page.slide_number or page.index + 1} 页"
        SW = doc.metadata.custom_properties.get("slide_width", 960) or 960
        SH = doc.metadata.custom_properties.get("slide_height", 540) or 540
        margin_x = SW * 0.01
        margin_y = SH * 0.01
        slide_area = SW * SH

        for elem in page.flattened_elements:
            if elem.type not in ("text_frame", "table"):
                continue
            if None in (elem.left, elem.top, elem.width, elem.height):
                continue
            if elem.width * elem.height >= slide_area * 0.8:
                continue
            issues = []
            if elem.left < margin_x:
                issues.append(f"left={elem.left:.0f}pt")
            if elem.top < margin_y:
                issues.append(f"top={elem.top:.0f}pt")
            if elem.left + elem.width > SW - margin_x:
                issues.append(f"right={elem.left + elem.width:.0f}pt")
            if elem.top + elem.height > SH - margin_y:
                issues.append(f"bottom={elem.top + elem.height:.0f}pt")
            if not issues:
                continue
            findings.append(
                AuditFinding(
                    type=FindingType.FORMAT,
                    severity=FindingSeverity.INFO,
                    message="元素过于贴近页面边缘，建议留出安全边距",
                    rule_id="FMT-SAFE-MARGIN",
                    page_index=page.index,
                    location=page_label,
                    context=f"{elem.shape_name or elem.type}: {', '.join(issues)}"[:150],
                    suggestion=f"建议保留至少 {margin_x:.0f}×{margin_y:.0f}pt 的页面边距",
                    metadata={"issues": issues},
                )
            )
        return findings

    def _check_text_overflow(self, page: Page, doc: Document) -> list[AuditFinding]:
        """估算文本框内容是否可能溢出 (2026-10-29)。

        说明：这是**估算**，不是像素级渲染。只对显式文本框/正文占位符，
        且 auto_size 不是 SHAPE_TO_FIT_TEXT/TEXT_TO_FIT_SHAPE 时检查；
        估算行高 = 字号 × 1.2，CJK 字符按 2 个半角单位计。
        """
        findings: list[AuditFinding] = []
        page_label = f"第 {page.slide_number or page.index + 1} 页"

        for elem in page.flattened_elements:
            if elem.type != "text_frame":
                continue
            if elem.placeholder_type in ("slide_number", "footer", "date", "header"):
                continue
            if elem.auto_size in ("SHAPE_TO_FIT_TEXT", "TEXT_TO_FIT_SHAPE"):
                continue
            if elem.width is None or elem.height is None:
                continue
            para_texts = [p.text.strip() for p in elem.paragraphs if p.text.strip()]
            if not para_texts:
                continue

            margin_l = elem.margin_left if elem.margin_left is not None else 7.2
            margin_r = elem.margin_right if elem.margin_right is not None else 7.2
            margin_t = elem.margin_top if elem.margin_top is not None else 3.6
            margin_b = elem.margin_bottom if elem.margin_bottom is not None else 3.6
            inner_w = max(1.0, elem.width - margin_l - margin_r)
            inner_h = max(1.0, elem.height - margin_t - margin_b)

            estimated_h = _estimate_paragraphs_height(elem.paragraphs, inner_w)
            if estimated_h is None or estimated_h <= inner_h * 1.15:
                continue
            if estimated_h - inner_h < 8.0:
                continue

            findings.append(
                AuditFinding(
                    type=FindingType.FORMAT,
                    severity=FindingSeverity.INFO,
                    message="文本框内容可能溢出（估算）",
                    rule_id="FMT-TEXT-OVERFLOW",
                    page_index=page.index,
                    location=page_label,
                    context=(
                        f"{elem.shape_name or '文本框'}: "
                        f"估算高度 {estimated_h:.0f}pt > 可用 {inner_h:.0f}pt"
                    )[:150],
                    suggestion="缩短文本、增大文本框、减小字号，或启用自动缩放",
                    metadata={
                        "estimated_height": round(estimated_h, 1),
                        "available_height": round(inner_h, 1),
                        "estimated": True,
                    },
                )
            )
        return findings

    def _check_footer_consistency(self, doc: Document) -> list[AuditFinding]:
        """检查页脚/页码/日期占位符是否全 deck 一致 (2026-10-29)。

        只在"部分页面有、部分页面没有"时提示；整套都没有视为模板选择，
        不误报。封面页 (第 1 页) 不参与。
        """
        findings: list[AuditFinding] = []
        content_pages = doc.pages[1:] if len(doc.pages) > 1 else []
        if not content_pages:
            return findings

        def _has_footer(page: Page) -> bool:
            return any(
                e.placeholder_type in ("footer", "slide_number", "date")
                for e in page.flattened_elements
            )

        states = [(_has_footer(page), page) for page in content_pages]
        with_footer = [page for has, page in states if has]
        if not with_footer or len(with_footer) == len(states):
            return findings

        missing = [
            f"第 {page.slide_number or page.index + 1} 页" for has, page in states if not has
        ]
        findings.append(
            AuditFinding(
                type=FindingType.FORMAT,
                severity=FindingSeverity.INFO,
                message="页脚/页码/日期占位符在部分页面缺失",
                rule_id="FMT-FOOTER",
                location="全文",
                context=f"缺失页面: {', '.join(missing[:8])}",
                suggestion="统一为所有内容页显示页脚/页码，或统一移除",
                metadata={"missing_pages": missing},
            )
        )
        return findings

    def _check_image_quality(self, page: Page, doc: Document) -> list[AuditFinding]:
        """检查图片宽高比失真/低 DPI/缺 alt text (2026-10-29)。"""
        findings: list[AuditFinding] = []
        page_label = f"第 {page.slide_number or page.index + 1} 页"

        for elem in page.flattened_elements:
            if elem.type != "image":
                continue
            if elem.width is None or elem.height is None or elem.width <= 0 or elem.height <= 0:
                continue
            display_ratio = elem.width / elem.height
            if elem.image_px_width and elem.image_px_height:
                intrinsic_ratio = elem.image_px_width / elem.image_px_height
                if intrinsic_ratio > 0:
                    distortion = abs(display_ratio - intrinsic_ratio) / intrinsic_ratio
                    if distortion > 0.02:
                        findings.append(
                            AuditFinding(
                                type=FindingType.FORMAT,
                                severity=FindingSeverity.WARNING,
                                message=f"图片宽高比失真 {distortion:.0%}",
                                rule_id="FMT-IMAGE",
                                page_index=page.index,
                                location=page_label,
                                context=f"{elem.shape_name or '图片'} 显示比例 {display_ratio:.2f}",
                                suggestion="保持图片原始宽高比，避免拉伸变形",
                                metadata={"distortion": round(distortion, 3)},
                            )
                        )

                dpi_x = elem.image_px_width / (elem.width / 72.0)
                dpi_y = elem.image_px_height / (elem.height / 72.0)
                min_dpi = min(dpi_x, dpi_y)
                if min_dpi < 150:
                    findings.append(
                        AuditFinding(
                            type=FindingType.FORMAT,
                            severity=FindingSeverity.INFO,
                            message=f"图片分辨率偏低（约 {min_dpi:.0f} DPI）",
                            rule_id="FMT-IMAGE",
                            page_index=page.index,
                            location=page_label,
                            context=f"{elem.shape_name or '图片'} ({elem.image_px_width}×{elem.image_px_height}px)",
                            suggestion="使用更高分辨率原图，避免投影/打印模糊",
                            metadata={"dpi": round(min_dpi, 1)},
                        )
                    )

            if not elem.image_alt_text:
                findings.append(
                    AuditFinding(
                        type=FindingType.FORMAT,
                        severity=FindingSeverity.INFO,
                        message="图片缺少替代文本 (alt text)",
                        rule_id="FMT-IMAGE",
                        page_index=page.index,
                        location=page_label,
                        context=elem.shape_name or "图片",
                        suggestion="为图片添加替代文本，提升无障碍与可检索性",
                    )
                )
        return findings

    def _check_chart_labeling(self, page: Page, doc: Document) -> list[AuditFinding]:
        """检查图表是否缺少标题 (2026-10-29)。"""
        findings: list[AuditFinding] = []
        page_label = f"第 {page.slide_number or page.index + 1} 页"
        for elem in page.flattened_elements:
            if elem.type != "chart":
                continue
            if elem.chart_has_title is False:
                findings.append(
                    AuditFinding(
                        type=FindingType.FORMAT,
                        severity=FindingSeverity.INFO,
                        message="图表缺少标题",
                        rule_id="FMT-CHART",
                        page_index=page.index,
                        location=page_label,
                        context=elem.shape_name or "图表",
                        suggestion="为图表添加说明性标题，明确指标与口径",
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
                # 修复 (2026-08 审查 L12): 英文计数曾为 总长-中文字数 (数字/标点/空格
                # 全部计入, "1"*300 误报 300 英文字符); 现改为纯字母计数,
                # 与 FMT-004 "英文约 300 字符" 语义一致。
                english_chars = len(re.findall(r"[a-zA-Z]", text))
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

    def _check_table_fit(self, page: Page, doc: Document | None = None) -> list[AuditFinding]:
        """估算表格行高/列宽是否容纳内容 (FMT-TABLE-FIT, 2026-10-29)。

        说明：几何估算，非渲染级。仅当转换器提取到行高/列宽 (>0) 时判定：
          - 行高小于单元格内容估算高度 → INFO（表格会自动增高、易错位）
          - 最长不可断词宽于可用列宽 → INFO（会被强制断行，排版难看）
          - 估算表格高度越过页面底部 → WARNING（真实越界风险）
        每个表格的同类问题聚合为一条 finding，避免逐行刷屏。
        """
        findings: list[AuditFinding] = []
        page_label = f"第 {page.slide_number or page.index + 1} 页"
        if doc is not None:
            sh = doc.metadata.custom_properties.get("slide_height", 540) or 540
        else:
            sh = 540
        is_pptx = doc is not None and doc.format == "pptx"
        default_margin = 7.2 if is_pptx else 5.4  # PPTX 0.1in / Word 约 0.075in
        # 单元格通常不写显式字号（继承表格样式）：估算时用应用默认值，
        # 否则真实文件会整表静默跳过。values 见 rules.md「不可配阈值」表。
        default_size = (
            self.DEFAULT_TABLE_FONT_SIZE_PPTX if is_pptx else self.DEFAULT_TABLE_FONT_SIZE_DOCX
        )

        for elem in page.flattened_elements:
            if elem.type != "table":
                continue
            row_heights = elem.table_row_heights or []
            col_widths = elem.table_col_widths or []
            if not row_heights and not col_widths:
                continue  # 无几何信息 → 降级跳过，不误报

            bad_rows: list[tuple[int, float, float]] = []
            narrow_cols: dict[int, tuple[float, float]] = {}
            estimated_total = 0.0

            for row_idx, row in enumerate(elem.tables):
                avail_h = row_heights[row_idx] if row_idx < len(row_heights) else 0.0
                needed_h = 0.0
                for cell in row:
                    if cell.col >= len(col_widths):
                        continue
                    col_w = col_widths[cell.col]
                    if col_w <= 0:
                        continue
                    margin_l = cell.margin_left if cell.margin_left is not None else default_margin
                    margin_r = (
                        cell.margin_right if cell.margin_right is not None else default_margin
                    )
                    inner_w = max(1.0, col_w - margin_l - margin_r)
                    text = (cell.text or "").strip()
                    if not text:
                        continue
                    font_size = float(cell.font_size) if cell.font_size else default_size
                    needed_h = max(
                        needed_h,
                        _estimate_text_height(text, font_size, inner_w),
                    )
                    token_w = _longest_unbreakable_token_width(text, font_size)
                    if token_w > inner_w * 1.05 and token_w - inner_w >= 2.0:
                        prev = narrow_cols.get(cell.col)
                        if prev is None or token_w > prev[0]:
                            narrow_cols[cell.col] = (token_w, inner_w)

                if avail_h > 0:
                    estimated_total += max(avail_h, needed_h)
                    if needed_h > avail_h * 1.15 and needed_h - avail_h >= 6.0:
                        bad_rows.append((row_idx, needed_h, avail_h))
                else:
                    estimated_total += needed_h

            if bad_rows:
                rows_str = "/".join(f"第{r + 1}行" for r, _n, _a in bad_rows[:5])
                worst_needed, worst_avail = max((n, a) for _r, n, a in bad_rows)
                findings.append(
                    AuditFinding(
                        type=FindingType.FORMAT,
                        severity=FindingSeverity.INFO,
                        message="表格行高小于内容估算高度（表格会自动增高，可能错位或顶出边界）",
                        rule_id="FMT-TABLE-FIT",
                        page_index=page.index,
                        location=f"{page_label} [表格] {rows_str}",
                        context=(
                            f"{rows_str} 行高 {worst_avail:.0f}pt < 估算内容 {worst_needed:.0f}pt"
                        )[:150],
                        suggestion="增大行高、精简单元格文字或减小字号",
                        metadata={
                            "kind": "row_height",
                            "rows": [r for r, _n, _a in bad_rows],
                            "estimated": True,
                        },
                    )
                )

            if narrow_cols:
                cols_str = "、".join(f"第{c + 1}列" for c in sorted(narrow_cols)[:5])
                widest = max(w for w, _i in narrow_cols.values())
                findings.append(
                    AuditFinding(
                        type=FindingType.FORMAT,
                        severity=FindingSeverity.INFO,
                        message="表格列宽小于最长不可断词宽度（文字将被强制断行）",
                        rule_id="FMT-TABLE-FIT",
                        page_index=page.index,
                        location=f"{page_label} [表格] {cols_str}",
                        context=f"{cols_str} 最长词约 {widest:.0f}pt，超出可用列宽"[:150],
                        suggestion="加宽列、缩小字号或为长词添加断行/空格",
                        metadata={
                            "kind": "col_width",
                            "cols": sorted(narrow_cols),
                            "estimated": True,
                        },
                    )
                )

            if elem.top is not None and elem.top + estimated_total > sh + 5.0:
                findings.append(
                    AuditFinding(
                        type=FindingType.FORMAT,
                        severity=FindingSeverity.WARNING,
                        message="表格内容估算高度越过页面底部（表格将超出显示区域）",
                        rule_id="FMT-TABLE-FIT",
                        page_index=page.index,
                        location=f"{page_label} [表格]",
                        context=(
                            f"top={elem.top:.0f}pt + 估算高度 {estimated_total:.0f}pt > 页高 {sh}pt"
                        )[:150],
                        suggestion="缩小表格（减少行数/字号）或移动到新页",
                        metadata={"kind": "page_overflow", "estimated": True},
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

                # 优先使用 Converter 从 a:pPr 提取的真实项目符号格式。
                # 文本前缀仅作为 MD/DOCX/旧数据的回退。
                bullet_type = getattr(para, "bullet_type", None)
                if bullet_type == "none":
                    continue
                if bullet_type == "char":
                    if "symbol" not in example_texts:
                        example_texts["symbol"] = text[:50].strip()
                    categories_found.add("symbol")
                    continue
                if bullet_type == "number":
                    if "numbered" not in example_texts:
                        example_texts["numbered"] = text[:50].strip()
                    categories_found.add("numbered")
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
