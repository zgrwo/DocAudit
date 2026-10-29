"""结构审查器 — 标题层级、章节完整性、图表编号"""

import re
from collections import Counter

from src.auditors.base import BaseAuditor
from src.models.document import Document, Page
from src.models.finding import AuditFinding, FindingSeverity, FindingType
from src.text_utils import is_cjk_char as _is_cjk_char

# 标题末尾标点检测正则 (模块级预编译 — 修复 2026-08 审查 L5: 曾每页重复编译)
_TRAILING_PUNCT_RE = re.compile(r"[。，、.!,;；：…—]+$")

# 图/表编号提取 (排除章节式编号 "图1-1": 数字后跟 [-–—]数字 跳过)。
# (?!\d|-\d) 双重负向断言 (2026-09-06 审查 D-1): 旧断言 (?![-–—]\d) 挡不住
# (\d+) 的内部回溯 — "图11-2" 贪婪匹配 "11" 被拒后回溯到 "1" 误析为图1,
# 两位数章节号 (≥10 章) 全部误报重复/跳号。(?!\d) 防数字回溯, (?!-\d) 防章节式;
# "图2-图4" (编号后跟范围连字符) 中 - 后非数字, 仍正常匹配。
_FIG_NUMBER_RE = re.compile(
    r"(?:图|Fig\.?|Figure|表|Table|Tab\.?)\s*(\d+)(?!\d|-\d)",
    re.IGNORECASE,
)

# 图表标题格式指纹提取 (Fig.1: / 图1： / Figure 1 - 等)
_CAPTION_RE = re.compile(
    r"(?:Fig\.?|Figure|图|Table|Tab\.?|表)\s*(\d+)\s*[:：\-—–]\s*",
    re.IGNORECASE,
)

# 标题英文词提取 (连续字母序列，含撇号缩写如 don't)
_TITLE_EN_WORD_RE = re.compile(r"[a-zA-Z]+(?:'[a-z]+)?")


class StructureAuditor(BaseAuditor):
    """检查文档的内容结构"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        cfg = config or {}
        self.required_sections = cfg.get("required_sections", [])
        # P1-3: CON-002 严重度配置驱动 (默认 error，可经 rules.md 声明覆盖)
        try:
            self.required_sections_severity = FindingSeverity(
                cfg.get("required_sections_severity", "error")
            )
        except ValueError:
            self.required_sections_severity = FindingSeverity.ERROR
        if "conclusion_keywords" in cfg:
            self.keywords = cfg["conclusion_keywords"]
        elif "keywords" in cfg:
            self.keywords = cfg["keywords"]
        else:
            self.keywords = [
                "结论",
                "小结",
                "总结",
                "要点",
                "关键",
                "建议",
                "展望",
                "Summary",
                "Conclusion",
                "Key",
                "Takeaway",
                "Recommend",
            ]
        # 标题页豁免版式 (默认对齐 rules.md CON-004，可配置覆盖)。
        # 用 or 而非 .get(key, default) — 显式空列表/None 不得清空内置默认。
        self.exempt_layouts = cfg.get("exempt_layouts") or [
            "标题幻灯片",
            "Title Slide",
            "Title",
            "Titelfolie",
            "封面",
            "タイトル",
            "Cover",
        ]
        # STR-004 标题长度阈值 (从 rules.md 配置，支持动态调整)
        try:
            self.max_english_words = int(cfg.get("max_english_words", 10))
        except (ValueError, TypeError):
            self.max_english_words = 10
        try:
            self.max_chinese_chars_title = int(cfg.get("max_chinese_chars_title", 40))
        except (ValueError, TypeError):
            self.max_chinese_chars_title = 40
        # 标题检测字号阈值 (用于 _check_title_slide 方案3)
        try:
            self.min_title_font_size = int(cfg.get("min_title_font_size", 28))
        except (ValueError, TypeError):
            self.min_title_font_size = 28
        # 流水线模式: 跳过已由 CustomRulesAuditor dispatch 的检查，避免双重执行
        self._skip_checks: set[str] = set(cfg.get("_skip_checks", []))

    def audit(self, doc: Document) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        skip = self._skip_checks  # pipeline 注入时跳过 CustomRulesAuditor 已 dispatch 的检查

        # 标题页检查 (PPTX 特有)
        if doc.format == "pptx" and "title_slide" not in skip:
            findings.extend(self._check_title_slide(doc))

        # 标题层级检查
        if "heading_levels" not in skip:
            findings.extend(self._check_heading_levels(doc))

        # 图表编号连续性
        if "figure_numbering" not in skip:
            findings.extend(self._check_figure_numbering(doc))

        # 必须包含的章节
        if self.required_sections:
            findings.extend(self._check_required_sections(doc))

        # 幻灯片结构一致性 (PPTX)
        if doc.format == "pptx" and "slide_structure_consistency" not in skip:
            findings.extend(self._check_slide_structure_consistency(doc))
        if doc.format == "pptx":
            findings.extend(self._check_master_consistency(doc))

        # 每页须有结论
        if "every_slide_conclusion" not in skip:
            findings.extend(self._check_every_slide_has_conclusion(doc))

        # 标题长度限制 (inspired by intern)
        if "title_length" not in skip:
            findings.extend(self._check_title_length(doc))

        # 图表标题格式一致性 (inspired by deepPPT + PerfectIt)
        if "figure_caption_format" not in skip:
            findings.extend(self._check_figure_caption_format(doc))

        # 标题尾随标点检测 (inspired by intern's TRAILING_PUNCTUATION)
        if "title_trailing_punctuation" not in skip:
            for page in doc.pages:
                findings.extend(self._check_title_trailing_punctuation(page, doc))

        # 重复标题检测 (inspired by intern)
        if "duplicate_title" not in skip:
            findings.extend(self._check_duplicate_title(doc))

        return findings

    def _check_title_slide(self, doc: Document) -> list[AuditFinding]:
        """检查第一页是否为标题页"""
        findings: list[AuditFinding] = []
        if not doc.pages:
            return findings

        first_page = doc.pages[0]

        # 方案1: 检查版式名称
        if first_page.layout_name and "标题" in first_page.layout_name:
            return findings

        # 方案2: 检查是否有标题占位符
        has_title_placeholder = any(elem.is_title for elem in first_page.flattened_elements)
        if has_title_placeholder:
            return findings

        # 方案3: 检查是否有一个明显的大标题
        for elem in first_page.flattened_elements:
            if elem.type != "text_frame":
                continue
            for para in elem.paragraphs:
                if not para.text.strip():
                    continue
                # 检查是否有大字号 Run
                for run in para.runs:
                    # is not None (falsy 约定): 字号 0 虽非正常值, 数值判断不作 truthy 短路
                    if run.font_size is not None and run.font_size >= self.min_title_font_size:
                        return findings  # 找到大号文本 = 算标题

        # 都没找到 → 告警 (严重度对齐 rules.md STR-001: error)
        findings.append(
            AuditFinding(
                type=FindingType.STRUCTURE,
                severity=FindingSeverity.ERROR,
                message='未检测到标题页（第一页版式不是"标题幻灯片"，也无标题占位符或大号标题文本）',
                rule_id="STR-001",
                page_index=0,
                location=f"第 1 页 [{first_page.layout_name or '未知版式'}]",
                suggestion='建议第一页使用"标题幻灯片"版式，包含文档标题和作者信息',
            )
        )
        return findings

    def _check_heading_levels(self, doc: Document) -> list[AuditFinding]:
        """检查标题层级是否逐级递进 (不跳级)。

        仅非 PPTX 适用 (修复 2026-08: PPTX 的 para.level 是缩进级别,
        被当作标题层级导致 bullet 缩进 0→2 误报 "H0→H2 跳级")。
        """
        findings: list[AuditFinding] = []
        if doc.format == "pptx":
            return findings

        for page in doc.pages:
            prev_level: int | None = None  # None = 页内首个标题, 不参与跳级比较
            for elem in page.flattened_elements:
                if elem.type != "text_frame":
                    continue
                for para in elem.paragraphs:
                    if para.level is None:
                        continue
                    current_level = para.level
                    if prev_level is not None and current_level > prev_level + 1:
                        findings.append(
                            AuditFinding(
                                type=FindingType.STRUCTURE,
                                severity=FindingSeverity.WARNING,
                                message=f"标题层级跳级: 从 H{prev_level} 跳到 H{current_level}",
                                rule_id="STR-003",
                                page_index=page.index,
                                location=f"第 {page.slide_number or page.index + 1} 页",
                                context=para.text[:100],
                                suggestion=f"建议在 H{prev_level} 和 H{current_level} 之间插入 H{prev_level + 1} 级别的标题",
                            )
                        )
                    prev_level = current_level

        return findings

    def _check_figure_numbering(self, doc: Document) -> list[AuditFinding]:
        """检查图/表编号是否连续"""
        findings: list[AuditFinding] = []

        # 提取所有图/表编号 (排除章节式编号 "图1-1": 数字后跟 [-–—]数字 跳过,
        # 避免 "图1-1/图1-2" 被误解析为重复的 "图1")
        all_numbers: list[tuple[int, int, str]] = []  # (page_index, number, match_text)

        for page in doc.pages:
            text = page.all_text
            for m in _FIG_NUMBER_RE.finditer(text):
                num = int(m.group(1))
                all_numbers.append((page.index, num, m.group(0)))

        if not all_numbers:
            return findings

        # 分别检查 "图" 和 "表" 的编号连续性
        fig_nums = [(p, n, t) for p, n, t in all_numbers if re.match(r"图|Fig", t, re.IGNORECASE)]
        tab_nums = [
            (p, n, t) for p, n, t in all_numbers if re.match(r"表|Table|Tab", t, re.IGNORECASE)
        ]

        findings.extend(self._validate_sequence(fig_nums, "图", doc))
        findings.extend(self._validate_sequence(tab_nums, "表", doc))

        return findings

    def _validate_sequence(
        self, items: list[tuple[int, int, str]], label: str, doc: Document
    ) -> list[AuditFinding]:
        """验证编号序列连续性，同时检测重复和倒退"""
        findings: list[AuditFinding] = []
        if len(items) < 2:
            return findings

        # 按出现顺序排序 (防御性: 跨页按 page 归组, 同页内保持出现次序 —
        # 按编号重排会掩盖页内倒退, 如 "图3 与图1" 被误报为跳过图2)
        ordered = [(p, n, t, i) for i, (p, n, t) in enumerate(items)]
        ordered.sort(key=lambda x: (x[0], x[3]))
        prev_num = ordered[0][1] - 1  # 从第一个编号减一开始
        seen_numbers: set[int] = set()

        for page_idx, num, text, _ in ordered:
            # 检测重复编号
            if num in seen_numbers:
                findings.append(
                    AuditFinding(
                        type=FindingType.STRUCTURE,
                        severity=FindingSeverity.WARNING,
                        message=f"{label}编号重复: {text} 出现多次",
                        rule_id="STR-002",
                        page_index=page_idx,
                        location=f"第 {doc.pages[page_idx].slide_number or page_idx + 1} 页",
                        context=text[:150],
                    )
                )
                prev_num = num
                continue
            seen_numbers.add(num)

            expected = prev_num + 1
            if num != expected:
                if num > expected:
                    findings.append(
                        AuditFinding(
                            type=FindingType.STRUCTURE,
                            severity=FindingSeverity.ERROR,
                            message=f"{label}编号不连续: 期望 {label}{expected}，实际 {text}（跳过了 {num - expected} 个编号）",
                            rule_id="STR-002",
                            page_index=page_idx,
                            location=f"第 {doc.pages[page_idx].slide_number or page_idx + 1} 页",
                            context=text[:150],
                        )
                    )
                else:
                    # num < expected: 编号倒退
                    findings.append(
                        AuditFinding(
                            type=FindingType.STRUCTURE,
                            severity=FindingSeverity.ERROR,
                            message=f"{label}编号倒退: 期望 ≥ {label}{expected}，实际 {text}",
                            rule_id="STR-002",
                            page_index=page_idx,
                            location=f"第 {doc.pages[page_idx].slide_number or page_idx + 1} 页",
                            context=text[:150],
                        )
                    )
                prev_num = num  # 继续用实际值
            else:
                prev_num = num

        return findings

    def _check_figure_caption_format(self, doc: Document) -> list[AuditFinding]:
        """检查图表标题格式一致性 (inspired by deepPPT + PerfectIt figure/table labels)。

        检测全文中是否混用了多种图表标题格式（如 Fig.1: / 图1： / Figure 1 -）。
        """
        findings: list[AuditFinding] = []

        # 图表标题格式指纹提取
        # 匹配模式并生成格式指纹（如 "Fig.N:", "图N：", "Figure N -"）

        fingerprints: dict[str, list[str]] = {}  # fingerprint → [example captions]

        for page in doc.pages:
            text = page.all_text
            for m in _CAPTION_RE.finditer(text):
                full_match = m.group(0)
                # 生成格式指纹: 将数字替换为 N，统一标点
                fp = re.sub(r"\d+", "N", full_match)
                # 统一化分隔符
                fp = re.sub(r"[：:]", ":", fp)
                fp = re.sub(r"[—–\-]", "-", fp)
                # 折叠空白: "Fig. 1:" 与 "Fig.1:" 视为同一种格式 (2026-08 审查 P3)
                fp = re.sub(r"\s+", "", fp)
                fp = fp.strip()
                if fp not in fingerprints:
                    fingerprints[fp] = []
                if len(fingerprints[fp]) < 3:
                    fingerprints[fp].append(full_match.strip())

        # 如果存在多种格式 → 报告
        if len(fingerprints) >= 2:
            fp_list = sorted(fingerprints.keys())
            examples = " | ".join(fingerprints[fp][0] for fp in fp_list)
            findings.append(
                AuditFinding(
                    type=FindingType.STRUCTURE,
                    severity=FindingSeverity.WARNING,
                    message=f"检测到 {len(fingerprints)} 种不同的图表标题格式: {', '.join(fp_list)}",
                    rule_id="STR-007",
                    location="全文",
                    context=examples[:150],
                    suggestion="建议统一图表标题格式，全文使用同一种格式（如'图N：'或'Fig. N: '）",
                    metadata={"format_count": len(fingerprints), "formats": fp_list},
                )
            )

        return findings

    def _check_required_sections(self, doc: Document) -> list[AuditFinding]:
        """检查是否包含必须的章节。

        检测策略（避免正文中偶然提及导致误判）：
        1. 优先在标题元素 (is_title / heading level) 中查找
        2. 回退到全文子串匹配（兼容无明确标题的文档格式）
        """
        findings: list[AuditFinding] = []

        # 提取所有标题文本（is_title 元素 + 有 heading level 的段落）
        title_texts: list[str] = []
        for page in doc.pages:
            for elem in page.flattened_elements:
                if elem.type != "text_frame":
                    continue
                if elem.is_title:
                    for para in elem.paragraphs:
                        if para.text.strip():
                            title_texts.append(para.text.strip().lower())
                else:
                    for para in elem.paragraphs:
                        if para.level is not None and para.text.strip():
                            title_texts.append(para.text.strip().lower())

        all_text_lower = doc.all_text.lower()

        for section in self.required_sections:
            section_lower = section.lower()
            # 策略 1: 标题级匹配（高置信度）
            found_in_title = any(section_lower in t for t in title_texts)
            if found_in_title:
                continue
            # 策略 2: 全文回退（兼容无标题结构的文档）
            if section_lower in all_text_lower:
                continue
            findings.append(
                AuditFinding(
                    type=FindingType.STRUCTURE,
                    severity=self.required_sections_severity,
                    message=f"缺少必须的章节: {section}",
                    rule_id="CON-002",
                    location="全文",
                    suggestion=f"建议添加「{section}」章节",
                )
            )

        return findings

    def _check_slide_structure_consistency(self, doc: Document) -> list[AuditFinding]:
        """检查幻灯片结构一致性"""
        findings: list[AuditFinding] = []

        # 统计版式使用分布
        layout_counter = Counter()
        for page in doc.pages:
            layout_counter[page.layout_name or "未知"] += 1

        # 检查版式使用是否合理
        if len(layout_counter) == 1 and "未知" not in layout_counter:
            # 所有幻灯片使用同一版式 → 不太合理
            findings.append(
                AuditFinding(
                    type=FindingType.STRUCTURE,
                    severity=FindingSeverity.INFO,
                    message=f"所有幻灯片使用同一版式「{list(layout_counter.keys())[0]}」，建议根据内容类型使用不同版式",
                    rule_id="STR-008",
                    location="全文",
                    context=f"共 {len(doc.pages)} 页，版式: {list(layout_counter.keys())[0]}",
                    suggestion="建议根据内容类型使用不同版式（如标题页、内容页、章节页等）",
                )
            )

        return findings

    def _check_master_consistency(self, doc: Document) -> list[AuditFinding]:
        """检查 PPTX 是否混用多个母版 (2026-10-29)。

        多母版本身不一定是错误（集团模板可能有意合并），但会导致字体/
        版式/页脚风格漂移，因此以 INFO 提示人工确认。
        """
        findings: list[AuditFinding] = []
        masters = sorted({p.master_name for p in doc.pages if p.master_name})
        if len(masters) <= 1:
            return findings
        findings.append(
            AuditFinding(
                type=FindingType.STRUCTURE,
                severity=FindingSeverity.INFO,
                message=f"检测到 {len(masters)} 个幻灯片母版，可能造成版式不一致",
                rule_id="STR-MASTER",
                location="全文",
                context="、".join(masters[:6])[:150],
                suggestion="确认是否确实需要多母版；否则统一为一个母版并复用版式",
                metadata={"masters": masters},
            )
        )
        return findings

    def _is_exempt_layout(self, layout_name: str | None) -> bool:
        """判断版式是否为标题/封面页。

        2026-10-28 修复：旧实现用 ``pattern in layout`` 做子串匹配，
        ``exempt_layouts`` 中的通用词 "Title" 会把 "Title and Content"
        等所有内容页一起豁免，导致 CON-004 在英文模板中完全失效。
        现改为：
        - 精确匹配（大小写不敏感）；
        - 仅对明确的封面短语允许前缀/包含匹配（"Title Slide"、"封面" 等），
          不允许通用词 "Title"/"标题" 单独做子串匹配。
        """
        if not layout_name:
            return False
        layout = layout_name.strip().casefold()
        if not layout:
            return False

        # 允许做前缀/包含匹配的封面专用短语；通用词不在此列。
        cover_phrases = {
            "title slide",
            "标题幻灯片",
            "封面",
            "封面页",
            "titelfolie",
            "タイトル",
            "cover",
            "cover page",
        }

        for pattern in self.exempt_layouts:
            candidate = str(pattern).strip().casefold()
            if not candidate:
                continue
            if layout == candidate:
                return True
            # 只对明确的封面短语允许前缀/包含，避免 "Title" 误伤内容页。
            if candidate in cover_phrases and (layout.startswith(candidate) or candidate in layout):
                return True
        return False

    def _page_content_text(self, page: Page) -> str:
        """返回页面的非标题正文（含表格），用于结论关键词判断。

        2026-10-28 修复：旧实现把标题也纳入关键词匹配，标题 "关键参数"
        会因包含 "关键" 而被误判为有结论。结论证据只应来自正文/表格。
        """
        texts: list[str] = []
        for elem in page.flattened_elements:
            if elem.type == "text_frame":
                if elem.is_title:
                    continue
                texts.extend(para.text.strip() for para in elem.paragraphs if para.text.strip())
            elif elem.type == "table":
                for row in elem.tables:
                    texts.extend(cell.text.strip() for cell in row if cell.text.strip())
        return "\n".join(texts)

    def _check_every_slide_has_conclusion(self, doc: Document) -> list[AuditFinding]:
        """检查每页是否有结论或关键要点。

        判断标准（满足任一即认为有结论）：
        1. 正文/表格中包含结论关键词（标题不计入）
        2. 除标题外有 >= 3 个有内容的段落（确保足够实质性内容）
        标题页和封面页自动豁免。

        2026-10-28 修复：
        - 版式豁免不再用通用子串 "Title"/"标题"；
        - 结论关键词只扫描非标题正文，避免 "关键参数" 等标题误通过；
        - 演讲者备注不再单独作为"页面有结论"的证据（备注不是观众可见内容）。

        仅 PPTX 适用 (修复 2026-08: DOCX/PDF/MD 每页误报 error —
        "每页结论" 是幻灯片语义，非分页文档无意义)。
        """
        findings: list[AuditFinding] = []
        if doc.format != "pptx":
            return findings
        keywords = self.keywords

        for page in doc.pages:
            page_label = f"第 {page.slide_number or page.index + 1} 页"

            # 标题/封面页豁免：精确匹配 + 封面专用短语匹配
            if self._is_exempt_layout(page.layout_name):
                continue

            has_conclusion = False

            # 判断1: 正文/表格中包含结论关键词（标题不计入）
            content_text = self._page_content_text(page).lower()
            if any(kw.lower() in content_text for kw in keywords):
                has_conclusion = True

            # 判断2: 除标题外有 >= 3 个有内容的段落（确保足够实质性内容）
            if not has_conclusion:
                content_para_count = sum(
                    sum(1 for p in e.paragraphs if p.text.strip())
                    for e in page.flattened_elements
                    if e.type == "text_frame" and not e.is_title
                )
                if content_para_count >= 3:
                    has_conclusion = True

            if not has_conclusion:
                findings.append(
                    AuditFinding(
                        type=FindingType.STRUCTURE,
                        severity=FindingSeverity.ERROR,
                        message="该页缺少结论或关键要点",
                        rule_id="CON-004",
                        page_index=page.index,
                        location=page_label,
                        context=page.all_text[:100] if page.all_text.strip() else "(空白页)",
                        suggestion="每页应包含明确的结论句或 Key Takeaway，或确保有足够的内容元素",
                    )
                )

        return findings

    def _check_title_length(self, doc: Document) -> list[AuditFinding]:
        """检查标题长度 (inspired by intern's TITLE_LENGTH rule)。

        阈值从 self.config 读取（由 rules.md STR-004 配置），
        默认: 英文 <= 10 词, 中文 <= 40 字。
        中英混合标题分别计算英文词数和中文字数，各自独立判断。
        """
        findings: list[AuditFinding] = []
        max_en = self.max_english_words
        max_zh = self.max_chinese_chars_title

        for page in doc.pages:
            page_label = f"第 {page.slide_number or page.index + 1} 页"
            for elem in page.flattened_elements:
                if not elem.is_title and not (
                    elem.shape_name and "title" in str(elem.shape_name).lower()
                ):
                    continue
                for para in elem.paragraphs:
                    title_text = para.text.strip()
                    if not title_text:
                        continue
                    # 英文词数: 仅统计拉丁字母序列 (排除中文干扰)
                    english_words = len(_TITLE_EN_WORD_RE.findall(title_text))
                    chinese_count = sum(1 for c in title_text if _is_cjk_char(c))

                    if english_words > max_en or chinese_count > max_zh:
                        findings.append(
                            AuditFinding(
                                type=FindingType.STRUCTURE,
                                severity=FindingSeverity.WARNING,
                                message=f"标题过长: {english_words} 英文词 / {chinese_count} 中文字",
                                rule_id="STR-004",
                                page_index=page.index,
                                location=page_label,
                                context=title_text[:100],
                                suggestion=f"建议标题控制在 {max_en} 英文词或 {max_zh} 中文字以内",
                                metadata={
                                    "english_words": english_words,
                                    "chinese_chars": chinese_count,
                                },
                            )
                        )

        return findings

    def _check_title_trailing_punctuation(self, page: Page, doc: Document) -> list[AuditFinding]:
        """检查标题末尾是否有多余标点 (inspired by intern's TRAILING_PUNCTUATION rule)。

        标题不应以句号、逗号等标点结尾。
        """
        findings: list[AuditFinding] = []
        page_label = f"第 {page.slide_number or page.index + 1} 页"

        for elem in page.flattened_elements:
            if not elem.is_title and not (
                elem.shape_name and "title" in str(elem.shape_name).lower()
            ):
                continue
            for para in elem.paragraphs:
                title_text = para.text.strip()
                if not title_text:
                    continue
                match = _TRAILING_PUNCT_RE.search(title_text)
                if match:
                    punct = match.group(0)
                    findings.append(
                        AuditFinding(
                            type=FindingType.STRUCTURE,
                            severity=FindingSeverity.INFO,
                            message=f"标题末尾含有多余标点: 「{punct}」",
                            rule_id="STR-006",
                            page_index=page.index,
                            location=page_label,
                            context=title_text[:100],
                            suggestion="标题末尾不应使用标点符号，建议删除末尾的标点",
                            metadata={"trailing_punctuation": punct},
                        )
                    )

        return findings

    def _check_duplicate_title(self, doc: Document) -> list[AuditFinding]:
        """检查重复标题 (inspired by intern's DUPLICATE_TITLE rule)。"""
        findings: list[AuditFinding] = []
        title_pages: dict[str, list[int]] = {}  # title_text → [page_index, ...]

        for page in doc.pages:
            for elem in page.flattened_elements:
                if not elem.is_title:
                    continue
                for para in elem.paragraphs:
                    title = para.text.strip().lower()
                    if title:
                        title_pages.setdefault(title, []).append(page.index)

        for title, page_indices in title_pages.items():
            if len(page_indices) > 1:
                pages_str = ", ".join(
                    f"第 {doc.pages[i].slide_number or i + 1} 页" for i in page_indices
                )
                findings.append(
                    AuditFinding(
                        type=FindingType.STRUCTURE,
                        severity=FindingSeverity.ERROR,
                        message=f"重复标题: 「{title[:50]}」在 {len(page_indices)} 张幻灯片中出现",
                        rule_id="STR-005",
                        page_index=page_indices[0],
                        location=pages_str,
                        context=title[:80],
                        suggestion="每张幻灯片的标题应独一无二，建议添加副标题或编号加以区分",
                        metadata={"pages": page_indices},
                    )
                )

        return findings
