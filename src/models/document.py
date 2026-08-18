"""统一文档模型 — 所有格式转换后统一使用此结构"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Run:
    """最小文本单元 — 一段连续格式属性的文本"""

    text: str
    font_name: str | None = None
    # 中文字体 (DOCX w:eastAsia / PPTX a:ea typeface)；中文显示字体由此决定，
    # 未提取到 (纯西文 run 或无显式 ea 设置) 为 None
    font_name_east_asia: str | None = None
    font_size: float | None = None  # pt
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    color: str | None = None  # hex RGB (e.g. "FF0000")
    strikethrough: bool | None = None


@dataclass
class Paragraph:
    """段落 — 一组 Run 组成一个逻辑段落"""

    text: str  # 完整文本 (拼接所有 Run)
    runs: list[Run] = field(default_factory=list)
    level: int | None = (
        None  # 层级 (三格式语义不同，0-based): DOCX=outlineLvl (0=H1), MD=标题深度-1 (H1→0), PPTX=缩进级别 (0=无缩进)
    )
    alignment: str | None = None  # "left" | "center" | "right" | "justify"
    space_before: float | None = None  # 段前间距 (pt)
    space_after: float | None = None  # 段后间距 (pt)
    line_spacing: float | None = None  # 行距倍数


@dataclass
class TableCell:
    """表格单元格"""

    text: str
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1
    font_name: str | None = None
    font_size: float | None = None
    fill_color: str | None = None  # 单元格底色 hex RGB (e.g. "1E3A5F")，无填充为 None
    font_color: str | None = None  # 首 run 字体色 hex RGB (e.g. "FFFFFF")，未提取到为 None


@dataclass
class PageElement:
    """页面上的一类元素 — 文本框、表格、图片、图表等"""

    ELEMENT_TYPES = ("text_frame", "table", "image", "chart", "group")

    type: str  # "text_frame" | "table" | "image" | "chart" | "group"
    paragraphs: list[Paragraph] = field(default_factory=list)
    tables: list[list[TableCell]] = field(default_factory=list)  # 按行分组
    children: list["PageElement"] = field(default_factory=list)  # Group 子元素 (PageElement 列表)

    # 位置与尺寸 (pt — 所有 Converter 已统一转换)
    left: float | None = None
    top: float | None = None
    width: float | None = None
    height: float | None = None

    # 形态标签
    shape_name: str | None = None  # PPTX shape name (DOCX 为 None)
    style_name: str | None = None  # DOCX 段落样式名 (如 "Heading 1")；PPTX 为 None
    is_title: bool = False  # 是否为标题占位符
    is_body: bool = False  # 是否为正文占位符
    is_placeholder: bool = False  # 是否为占位符

    # 图片特有
    image_blob: bytes | None = None
    image_ext: str | None = None  # "png" | "jpg" | "emf"

    # 图表特有
    chart_type: str | None = None  # "bar" | "line" | "pie" | "scatter" | ...
    chart_data: dict | None = None  # 结构化图表数据

    # 备注
    notes: str | None = None  # PPTX 演讲者备注

    def iter_flat(self):
        """递归展开：yield 自身 + group 内所有子孙元素"""
        yield self
        for child in self.children:
            yield from child.iter_flat()


@dataclass
class Page:
    """一页 / 一张幻灯片 / 一页 PDF"""

    index: int
    elements: list[PageElement] = field(default_factory=list)
    layout_name: str | None = None  # PPTX 母版/版式名称
    slide_number: int | None = None  # 幻灯片编号 (1-indexed)
    notes: str | None = None  # 演讲者备注 (PPTX)
    image_blob: bytes | None = None  # 幻灯片缩略图

    def invalidate_cache(self) -> None:
        """清除 flattened_elements / all_text 缓存（当 elements 被修改后调用）"""
        object.__setattr__(self, "_cached_flattened", None)
        object.__setattr__(self, "_cached_all_text", None)

    @property
    def flattened_elements(self) -> list:
        """返回所有元素的扁平列表（含 Group 递归展开的子元素，首次调用后缓存）"""
        cached = getattr(self, "_cached_flattened", None)
        if cached is not None:
            return cached
        result = []
        for elem in self.elements:
            if elem.type is None:
                logger.warning(
                    "Page %d: 跳过 type=None 的异常元素 (%s)",
                    self.index,
                    elem.shape_name or "unknown",
                )
                continue
            result.extend(elem.iter_flat())
        object.__setattr__(self, "_cached_flattened", result)
        return result

    @property
    def all_text(self) -> str:
        """提取该页所有文本 (首次调用后缓存)"""
        cached = getattr(self, "_cached_all_text", None)
        if cached is not None:
            return cached
        texts = []
        for elem in self.flattened_elements:
            for para in elem.paragraphs:
                if para.text and para.text.strip():
                    texts.append(para.text)
            # 预留: 未来支持 Per-shape 备注（当前所有 Converter 均未赋值 elem.notes，此为死代码路径）
            if elem.notes:
                texts.append(elem.notes)
            for row in elem.tables:
                for cell in row:
                    if cell.text and cell.text.strip():
                        texts.append(cell.text)
        # 也包含幻灯片级别的演讲者备注
        if self.notes and self.notes.strip():
            texts.append(self.notes)
        object.__setattr__(self, "_cached_all_text", "\n".join(texts))
        return self._cached_all_text

    @property
    def all_paragraphs(self) -> list[Paragraph]:
        """获取该页所有段落（含 Group 递归展开的子元素）"""
        result = []
        for elem in self.flattened_elements:
            result.extend(elem.paragraphs)
        return result

    @property
    def text_frames(self) -> list[PageElement]:
        """仅返回文本框类型元素（含 Group 递归展开）"""
        return [e for e in self.flattened_elements if e.type == "text_frame"]

    @property
    def tables(self) -> list[PageElement]:
        """仅返回包含表格的元素（含 Group 递归展开）"""
        return [e for e in self.flattened_elements if e.type == "table"]


@dataclass
class DocumentMetadata:
    """文档元数据"""

    title: str | None = None
    author: str | None = None
    created: str | None = None
    modified: str | None = None
    slide_count: int | None = None  # PPTX
    page_count: int | None = None  # PDF / DOCX
    word_count: int | None = None
    custom_properties: dict = field(default_factory=dict)


@dataclass
class Document:
    """统一文档模型 — 所有 Converter 输出此结构"""

    source_path: str
    format: str  # "pptx" | "docx" | "pdf" | "md"
    metadata: DocumentMetadata
    pages: list[Page] = field(default_factory=list)

    def invalidate_cache(self) -> None:
        """清除 Document 级缓存（当 pages/elements 被修改后调用）。

        同时清除所有子页面的缓存，确保一致性。
        """
        object.__setattr__(self, "_cached_all_text", None)
        object.__setattr__(self, "_cached_all_paragraphs", None)
        for page in self.pages:
            page.invalidate_cache()

    @property
    def all_text(self) -> str:
        """获取全文 (首次调用后缓存)"""
        cached = getattr(self, "_cached_all_text", None)
        if cached is not None:
            return cached
        object.__setattr__(
            self, "_cached_all_text", "\n\n".join(page.all_text for page in self.pages)
        )
        return self._cached_all_text

    @property
    def all_paragraphs(self) -> list[Paragraph]:
        """获取全文档所有段落（首次调用后缓存）"""
        cached = getattr(self, "_cached_all_paragraphs", None)
        if cached is not None:
            return cached
        result = []
        for page in self.pages:
            result.extend(page.all_paragraphs)
        object.__setattr__(self, "_cached_all_paragraphs", result)
        return result
