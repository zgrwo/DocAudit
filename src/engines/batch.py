"""批量跨文档一致性 — 系列报告之间的口径漂移检查（2026-11 新增）。

单文档审查看不见"这一份和上一份不一致"：同一缩写在不同文件里全称不同、同一份
必含章节有的文件有、有的没有。本模块只做**跨文档比对**，不重复单文档检查。
"""

from __future__ import annotations

import re
from collections import defaultdict

from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity, FindingType
from src.text_utils import mask_prose_noise

# 缩写定义: 全称（ABBR） / 全称 (ABBR)
_ABBR_DEF_RE = re.compile(
    r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9 /·\-]{1,30})"
    r"\s*[（(]\s*([A-Z][A-Z0-9]{1,7})\s*[)）]"
)

# 常见前缀/连接词：中文无空格，全称捕获会把"本方案采用"等一并吞入；
# 跨文档比较前必须剥离，否则同一术语因前缀不同被误报为"全称不一致"
# （2026-11 max 审查 F3）。
_FILLER_PREFIXES = (
    "本方案",
    "该方案",
    "本报告",
    "该报告",
    "本流程",
    "该流程",
    "本工艺",
    "该工艺",
    "我们",
    "采用",
    "基于",
    "使用",
    "通过",
    "利用",
    "引入",
    "称为",
    "所谓",
)


def _normalize_full_name(full: str) -> str:
    """剥离"本方案采用/基于/的"等前缀，得到术语本体（用于跨文档比较）。"""
    name = full.strip(" \u3000，,、:：;；的")
    if "的" in name:
        name = name.split("的")[-1]
    changed = True
    while changed:
        changed = False
        for filler in _FILLER_PREFIXES:
            if name.startswith(filler) and len(name) > len(filler) + 1:
                name = name[len(filler) :].lstrip()
                changed = True
    return name.strip(" \u3000，,、:：;；")


def _distinct_full_names(fulls: set[str]) -> set[str]:
    """归一化并合并后缀兼容项（"原子层沉积" ⊂ "原子层沉积工艺" 视为同一名称）。"""
    normalized = {_normalize_full_name(x) for x in fulls}
    normalized = {name for name in normalized if name}
    distinct: set[str] = set()
    for name in normalized:
        if any(
            name != other and (name.endswith(other) or other.endswith(name)) for other in normalized
        ):
            continue
        distinct.add(name)
    return distinct


def _abbr_definitions(doc: Document) -> dict[str, set[str]]:
    """提取文档中的 缩写 → 全称集合（只认"全称（ABBR）"形态）。"""
    definitions: dict[str, set[str]] = defaultdict(set)
    for page in doc.pages:
        text = mask_prose_noise(page.all_text)
        for m in _ABBR_DEF_RE.finditer(text):
            full = m.group(1).strip(" ，,、:：;；")
            abbr = m.group(2)
            if len(full) >= 2:
                definitions[abbr].add(full)
    return definitions


def _has_headings(doc: Document) -> bool:
    """文档是否有可用标题（PPTX 标题占位符 / 段落 level）。"""
    for page in doc.pages:
        for elem in page.flattened_elements:
            if elem.is_title:
                return True
            if any(para.level for para in elem.paragraphs):
                return True
    return False


def _section_present(doc: Document, section: str, all_sections: list[str]) -> bool:
    """章节存在性：标题/heading 命中；无标题纯文本文档只认"独立成行"的章节名。

    2026-11 max 审查 F10 + reaudit S1/S4：
    - PPTX 只认标题占位符（正文提及章节名不算，body 的 level 是缩进级别）；
    - 非 PPTX 用段落 heading level；
    - 无标题文档的兜底行判定排除"目录行"：同一段落含 ≥2 个必含章节名 → 视为目录。
    """
    has_headings = _has_headings(doc)
    is_pptx = doc.format == "pptx"
    for page in doc.pages:
        for elem in page.flattened_elements:
            if elem.is_title:
                title = " ".join(para.text for para in elem.paragraphs)
                if section in title:
                    return True
            if is_pptx or not has_headings:
                continue
            for para in elem.paragraphs:
                if para.level and section in (para.text or ""):
                    return True
    if is_pptx or has_headings:
        return False
    for page in doc.pages:
        for elem in page.flattened_elements:
            for para in elem.paragraphs:
                text = (para.text or "").strip()
                if not text:
                    continue
                # 目录行（含 ≥2 个必含章节名）不算章节存在
                if sum(1 for sec in all_sections if sec in text) >= 2:
                    continue
                if text == section or (text.startswith(section) and len(text) <= len(section) + 10):
                    return True
    return False


def cross_document_findings(
    entries: list[tuple[str, Document]],
    required_sections: list[str] | None = None,
) -> list[AuditFinding]:
    """跨文档一致性检查。

    Args:
        entries: ``[(显示文件名, Document), ...]``（至少 2 个文件才有意义）。
        required_sections: CON-002 声明的必含章节；用于检查"有的文件缺章"。

    Returns:
        BATCH-TERM（缩写全称不一致）/ BATCH-SECTION（章节覆盖不一致）发现。
    """
    if len(entries) < 2:
        return []

    findings: list[AuditFinding] = []

    # 1) 同一缩写在不同文件中全称不一致（前缀归一化后比较）
    abbr_full: dict[str, set[str]] = defaultdict(set)
    abbr_files: dict[str, set[str]] = defaultdict(set)
    for name, doc in entries:
        for abbr, fulls in _abbr_definitions(doc).items():
            abbr_full[abbr] |= fulls
            abbr_files[abbr].add(name)
    for abbr in sorted(abbr_full):
        fulls = _distinct_full_names(abbr_full[abbr])
        if len(fulls) < 2 or len(abbr_files[abbr]) < 2:
            continue
        findings.append(
            AuditFinding(
                type=FindingType.FACTUAL,
                severity=FindingSeverity.WARNING,
                message=f"缩写在多份报告中全称不一致（{abbr}）",
                rule_id="BATCH-TERM",
                location="、".join(sorted(abbr_files[abbr])),
                context=f"{abbr}: " + " / ".join(sorted(fulls)),
                suggestion="统一缩写全称并在术语表中登记，避免跨报告口径漂移",
                metadata={"abbr": abbr, "full_names": sorted(fulls)},
            )
        )

    # 2) 必含章节覆盖不一致（有的文件有、有的没有）
    if required_sections:
        presence: dict[str, list[str]] = {sec: [] for sec in required_sections}
        for name, doc in entries:
            for sec in required_sections:
                if _section_present(doc, sec, required_sections):
                    presence[sec].append(name)
        total = len(entries)
        for sec, files in presence.items():
            if not files or len(files) == total:
                continue
            missing = [n for n, _d in entries if n not in files]
            findings.append(
                AuditFinding(
                    type=FindingType.STRUCTURE,
                    severity=FindingSeverity.WARNING,
                    message=f"章节「{sec}」仅部分报告包含（{len(files)}/{total}）",
                    rule_id="BATCH-SECTION",
                    location="、".join(missing[:3]) + ("…" if len(missing) > 3 else ""),
                    context=f"缺少: {', '.join(missing[:5])}",
                    suggestion="系列报告应保持章节结构一致；缺失章节请补齐或在目录中说明",
                    metadata={"section": sec, "missing": missing},
                )
            )

    return findings
