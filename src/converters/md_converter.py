"""Markdown 转换器 — 直接解析 Markdown 文件"""

from pathlib import Path
import re
import logging

from src.converters.base import BaseConverter
from src.models.document import (
    Document,
    DocumentMetadata,
    Page,
    PageElement,
    Paragraph,
    Run,
    TableCell,
)

logger = logging.getLogger(__name__)

# 常用 Markdown 标题正则
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# 编码回退顺序 (UTF-8 优先，然后是常见中文编码，最后 Latin-1 兜底)
_FALLBACK_ENCODINGS = ("utf-8", "utf-8-sig", "utf-16", "gbk", "gb2312", "shift-jis", "latin-1")


class MarkdownConverter(BaseConverter):
    """将 Markdown 文件转换为统一 Document 模型。

    解析策略：
    - 按一段空白行(两个以上换行)视为"页面"分隔
    - 按 ## / ### 识别标题层级
    - 列表/代码块作为普通段落保留
    - 无格式元数据（Markdown 为纯文本格式）
    """

    def can_handle(self, source_path: str | Path) -> bool:
        ext = Path(source_path).suffix.lower().lstrip(".")
        return ext in ("md", "markdown", "txt")

    def convert(self, source_path: str | Path) -> Document:
        source_path = Path(source_path)
        text = _read_with_fallback(source_path)

        # --- 解析 YAML frontmatter (可选) ---
        frontmatter: dict = {}
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                try:
                    import yaml
                    frontmatter = yaml.safe_load(parts[1]) or {}
                except Exception:
                    pass
                body = parts[2]

        # --- 元数据 (优先使用 frontmatter 中的 title/author) ---
        metadata = DocumentMetadata(
            title=frontmatter.get("title") or source_path.stem,
            author=frontmatter.get("author"),
            created=str(frontmatter["date"]) if frontmatter.get("date") else None,
            word_count=len(body.split()),
        )

        # --- 按 "页面" 分割 ---
        # 用三级标题 (###) 或连续的空白行作为页面分隔
        pages = self._split_into_pages(body)

        return Document(
            source_path=str(source_path),
            format="md",
            metadata=metadata,
            pages=pages,
        )

    def _split_into_pages(self, text: str) -> list[Page]:
        """将 Markdown 文本拆分为逻辑页"""
        # 用 ## 或 ### 标题作为页面边界（模拟 Slide）
        page_texts = re.split(r"\n(?=\s{0,3}#{1,3}\s)", text.strip())

        pages: list[Page] = []
        for idx, page_text in enumerate(page_texts):
            if not page_text.strip():
                continue

            elements = self._parse_elements(page_text)
            if elements:
                pages.append(Page(
                    index=idx,
                    elements=elements,
                    slide_number=idx + 1,
                ))

        if not pages:
            pages.append(Page(
                index=0,
                elements=[PageElement(
                    type="text_frame",
                    paragraphs=[Paragraph(text=text.strip(), runs=[])],
                )],
                slide_number=1,
            ))

        return pages

    def _parse_elements(self, text: str) -> list[PageElement]:
        """解析一段 Markdown 文本"""
        elements: list[PageElement] = []
        lines = text.strip().split("\n")
        current_type = None
        current_lines: list[str] = []
        in_code_block = False

        for line in lines:
            # ── 围栏代码块: ``` ... ``` 或 ~~~ ... ~~~ ─────
            if line.startswith("```") or line.startswith("~~~"):
                if in_code_block:
                    # 代码块结束
                    current_lines.append(line)
                    elements.append(PageElement(
                        type="text_frame",
                        paragraphs=[Paragraph(text="\n".join(current_lines), runs=[])],
                    ))
                    current_lines = []
                    in_code_block = False
                else:
                    # 代码块开始: 先刷新当前缓冲
                    if current_lines:
                        elements.append(self._make_element(current_lines, current_type))
                        current_lines = []
                        current_type = None
                    current_lines.append(line)
                    in_code_block = True
                continue

            # ── 代码块内容 — 原样保留 ──────────────────
            if in_code_block:
                current_lines.append(line)
                continue

            m = HEADING_RE.match(line)
            if m:
                if current_lines:
                    elements.append(self._make_element(current_lines, current_type))
                    current_lines = []
                level = len(m.group(1))
                heading_text = m.group(2)
                elements.append(PageElement(
                    type="text_frame",
                    paragraphs=[Paragraph(text=heading_text.strip(), runs=[], level=level)],
                    is_title=(level == 1),
                ))
                current_type = None
                continue

            # 普通段落行
            if line.strip() == "":
                if current_lines:
                    elements.append(self._make_element(current_lines, current_type))
                    current_lines = []
                    current_type = None
                continue

            # 表格行 (支持可选前导 | 的 GFM 语法: "Name | Age" 和 "| Name | Age |" 均可)
            stripped = line.strip()
            if "|" in stripped and not re.match(r"^[\-*_]{3,}\s*$", stripped):
                if current_type != "table":
                    if current_lines:
                        elements.append(self._make_element(current_lines, current_type))
                        current_lines = []
                    current_type = "table"
                current_lines.append(line)
                continue

            # 列表行 (排除水平分隔线: ---, ***, ___)
            stripped = line.strip()
            if stripped and (re.match(r"^[\-*+]\s", stripped) or re.match(r"^\d+\.\s", stripped)):
                # 跳过水平分隔线 (仅由 - * _ 组成，长度 ≥ 3)
                if re.match(r"^[\-*_]{3,}\s*$", stripped):
                    continue
                if current_type != "text":
                    if current_lines:
                        elements.append(self._make_element(current_lines, current_type))
                        current_lines = []
                    current_type = "text"
                current_lines.append(line)
                continue

            # 默认：文本
            if current_type != "text" and current_type is not None:
                if current_lines:
                    elements.append(self._make_element(current_lines, current_type))
                    current_lines = []
            current_type = "text"
            current_lines.append(line)

        # 处理最后的缓冲
        if current_lines:
            if in_code_block:
                # 未闭合的代码块 — 仍作为代码块保留
                elements.append(PageElement(
                    type="text_frame",
                    paragraphs=[Paragraph(text="\n".join(current_lines), runs=[])],
                ))
            else:
                elements.append(self._make_element(current_lines, current_type))

        return [e for e in elements if e is not None]

    def _make_element(self, lines: list[str], elem_type: str | None) -> PageElement | None:
        """将一组行转换为 PageElement"""
        text = "\n".join(lines).strip()
        if not text:
            return None  # 空文本不产生元素，调用方已在 _parse_elements 中过滤

        if elem_type == "table":
            # Markdown 表格 → 简单解析
            rows = self._parse_markdown_table(lines)
            return PageElement(type="table", tables=rows)

        # 检测该段是否为标题
        m = HEADING_RE.match(lines[0]) if lines else None
        level = len(m.group(1)) if m else None

        return PageElement(
            type="text_frame",
            paragraphs=[Paragraph(text=text, runs=[], level=level)],
            is_title=(level == 1),
        )

    def _parse_markdown_table(self, lines: list[str]) -> list[list[TableCell]]:
        """解析 Markdown 表格"""
        rows: list[list[TableCell]] = []
        for row_idx, line in enumerate(lines):
            line = line.strip()
            # 跳过分隔行 (|---|---|)
            if re.match(r"^[\|\s\-:]+$", line):
                continue
            cells = [c.strip() for c in line.split("|")]
            # 去掉首尾空元素
            if cells and cells[0] == "":
                cells = cells[1:]
            if cells and cells[-1] == "":
                cells = cells[:-1]
            row_cells = [
                TableCell(text=c, row=row_idx, col=col_idx)
                for col_idx, c in enumerate(cells)
            ]
            if row_cells:
                rows.append(row_cells)
        return rows


def _read_with_fallback(path: Path) -> str:
    """读取文本文件，依次尝试多种编码 (UTF-8 → GBK → GB2312 → Latin-1)。

    Latin-1 作为最终回退永远不会失败（单字节全覆盖），但会用替换字符标记无法解码的字节。
    """
    for encoding in _FALLBACK_ENCODINGS:
        try:
            content = path.read_text(encoding=encoding)
            if encoding != "utf-8":
                logger.info("使用 %s 编码读取: %s", encoding, path.name)
            return content
        except (UnicodeDecodeError, UnicodeError):
            continue
    # 最终回退 (理论上不会到达，因为 Latin-1 不会抛出解码错误)
    logger.warning("所有编码回退失败，使用 Latin-1 + replace: %s", path.name)
    return path.read_text(encoding="latin-1", errors="replace")
