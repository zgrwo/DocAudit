"""PPTX 转换器 — 使用 python-pptx 解析，保留完整格式元数据"""

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from lxml import etree
from pptx import Presentation
from pptx.enum.dml import MSO_FILL_TYPE
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn
from pptx.util import Length

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

# PPTX 内部命名空间
NSMAP = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


def _sz_to_pt(def_rpr) -> float | None:
    """a:defRPr/@sz (百分之一 pt) → pt。"""
    if def_rpr is None:
        return None
    raw = def_rpr.get("sz")
    if not raw:
        return None
    try:
        return int(raw) / 100.0
    except (TypeError, ValueError):
        return None


def _typeface(def_rpr, tag: str) -> str | None:
    """读取 defRPr/a:latin|a:ea 的 typeface。"""
    if def_rpr is None:
        return None
    child = def_rpr.find(qn(tag))
    if child is None:
        return None
    return child.get("typeface")


def _lvl_name(level: int | None) -> str:
    """0-based 段落级别 → a:lvlNpPr (1-9)。"""
    n = max(0, min(8, level or 0)) + 1
    return f"a:lvl{n}pPr"


def _lst_style(element) -> Any:
    """从 p:sp / p:graphicFrame 等元素取 p:txBody/a:lstStyle。"""
    if element is None:
        return None
    tx_body = element.find(qn("p:txBody"))
    if tx_body is None:
        return None
    return tx_body.find(qn("a:lstStyle"))


def _def_rpr_from_style(style_element, level: int | None) -> Any:
    """p:titleStyle/p:bodyStyle/a:lvlNpPr/a:defRPr。"""
    if style_element is None:
        return None
    lvl = style_element.find(qn(_lvl_name(level)))
    if lvl is None:
        return None
    return lvl.find(qn("a:defRPr"))


def _def_rpr_from_lst(lst_style, level: int | None) -> Any:
    """a:lstStyle/a:lvlNpPr/a:defRPr。"""
    if lst_style is None:
        return None
    lvl = lst_style.find(qn(_lvl_name(level)))
    if lvl is None:
        return None
    return lvl.find(qn("a:defRPr"))


class _PptxStyleResolver:
    """解析 PPTX 的继承字体/字号。

    解析顺序（从高到低）：
    run rPr → paragraph a:pPr/a:defRPr → shape a:lstStyle
    → layout placeholder a:lstStyle → master p:txStyles → theme fontScheme。

    python-pptx 的 font.size/font.name 只返回显式值；真实 deck 的标题/正文
    通常继承 layout/master，导致 FMT-001/002 静默漏检。
    """

    def __init__(self, prs, slide):
        self.prs = prs
        self.slide = slide
        self.layout = slide.slide_layout
        self.master = self.layout.slide_master
        self._theme_fonts = self._load_theme_fonts()
        self._layout_lst_by_idx: dict[int, Any] = {}
        for ph in self.layout.placeholders:
            try:
                idx = ph.placeholder_format.idx
                if idx is not None:
                    self._layout_lst_by_idx[idx] = _lst_style(ph._element)
            except Exception:
                continue

    def _load_theme_fonts(self) -> dict[str, str]:
        """读取 theme 的 major/minor latin+ea 字体。"""
        fonts: dict[str, str] = {}
        try:
            for rel in self.master.part.rels.values():
                if "theme" not in rel.reltype:
                    continue
                theme_xml = etree.fromstring(rel.target_part.blob)
                scheme = theme_xml.find(".//" + qn("a:fontScheme"))
                if scheme is None:
                    continue
                for kind in ("majorFont", "minorFont"):
                    font_el = scheme.find(qn(f"a:{kind}"))
                    if font_el is None:
                        continue
                    for tag, suffix in (("a:latin", "lt"), ("a:ea", "ea")):
                        node = font_el.find(qn(tag))
                        if node is not None and node.get("typeface"):
                            prefix = "mj" if kind == "majorFont" else "mn"
                            fonts[f"+{prefix}-{suffix}"] = node.get("typeface")
                break
        except Exception:
            # 主题解析失败时返回空表；调用方会跳过 +mj/+mn token，不误报。
            return {}
        return fonts

    def _resolve_typeface(self, value: str | None) -> str | None:
        if not value:
            return None
        if value.startswith("+"):
            return self._theme_fonts.get(value)
        return value

    def _is_title(self, shape) -> bool:
        try:
            return bool(
                shape.is_placeholder
                and int(shape.placeholder_format.type) in (1, 3, 5)  # TITLE/CENTER/VERTICAL
            )
        except Exception:
            return False

    def _is_body(self, shape) -> bool:
        try:
            return bool(shape.is_placeholder and int(shape.placeholder_format.type) in (2, 4, 6))
        except Exception:
            return False

    def _master_style(self, shape):
        try:
            tx_styles = self.master._element.find(qn("p:txStyles"))
            if tx_styles is None:
                return None
            if self._is_title(shape):
                return tx_styles.find(qn("p:titleStyle"))
            if self._is_body(shape):
                return tx_styles.find(qn("p:bodyStyle"))
            return tx_styles.find(qn("p:otherStyle"))
        except Exception:
            return None

    def _layout_lst(self, shape):
        try:
            if not shape.is_placeholder:
                return None
            idx = shape.placeholder_format.idx
            return self._layout_lst_by_idx.get(idx)
        except Exception:
            return None

    def resolve_run(self, shape, para, run_elem, level: int | None) -> tuple:
        """返回 (effective_latin, effective_ea, effective_size, inherited_size)。"""
        explicit_latin = run_elem.font.name
        explicit_ea = _ea_typeface(run_elem)
        explicit_size = run_elem.font.size.pt if run_elem.font.size is not None else None

        p_pr = para._p.find(qn("a:pPr"))
        para_def = p_pr.find(qn("a:defRPr")) if p_pr is not None else None
        shape_def = _def_rpr_from_lst(_lst_style(shape._element), level)
        layout_def = _def_rpr_from_lst(self._layout_lst(shape), level)
        master_def = _def_rpr_from_style(self._master_style(shape), level)
        candidates = [para_def, shape_def, layout_def, master_def]

        latin = self._resolve_typeface(explicit_latin)
        east_asia = self._resolve_typeface(explicit_ea)
        size = explicit_size

        if size is None:
            for candidate in candidates:
                size = _sz_to_pt(candidate)
                if size is not None:
                    break
        if latin is None:
            for candidate in candidates:
                latin = self._resolve_typeface(_typeface(candidate, "a:latin"))
                if latin:
                    break
        if east_asia is None:
            for candidate in candidates:
                east_asia = self._resolve_typeface(_typeface(candidate, "a:ea"))
                if east_asia:
                    break

        return latin, east_asia, size, explicit_size is None and size is not None


class PptxConverter(BaseConverter):
    """将 PPTX 文件转换为统一 Document 模型。

    保留信息：
    - 每个 Slide 的版式名称 (layout_name)
    - 每个 Shape 的精确位置 (left, top, width, height)
    - 每个 Run 的字体/字号/颜色/加粗/斜体
    - 段落对齐、缩进级别
    - 演讲者备注
    - 表格结构
    - 占位符类型 (title / body / ...)
    """

    def can_handle(self, source_path: str | Path) -> bool:
        ext = Path(source_path).suffix.lower().lstrip(".")
        return ext in ("pptx", "ppt")

    def convert(self, source_path: str | Path) -> Document:
        source_path = Path(source_path)
        logger.info("解析 PPTX: %s", source_path.name)

        if source_path.suffix.lower() == ".ppt":
            raise ValueError(
                "旧版二进制 .ppt 不受支持，请先用 PowerPoint/LibreOffice 另存为 .pptx 后重试"
            )

        try:
            prs = Presentation(str(source_path))
        except Exception as e:
            logger.error("无法打开 PPTX 文件: %s", e)
            raise ValueError(f"无法解析 PPTX 文件: {source_path}") from e

        # --- 元数据 ---
        core_props = prs.core_properties
        metadata = DocumentMetadata(
            title=core_props.title,
            author=core_props.author,
            created=str(core_props.created) if core_props.created else None,
            modified=str(core_props.modified) if core_props.modified else None,
            slide_count=len(prs.slides),
            custom_properties={
                "slide_width": _emu_to_pt(prs.slide_width),
                "slide_height": _emu_to_pt(prs.slide_height),
            },
        )

        # --- 遍历 Slide ---
        pages: list[Page] = []

        for slide_idx, slide in enumerate(prs.slides):
            # 版式/母版名称
            layout_name = None
            master_name = None
            try:
                layout_name = slide.slide_layout.name or None
                master = slide.slide_layout.slide_master
                master_name = master.name or str(master.part.partname)
            except Exception:
                pass  # bare-handler-ok — 版式/母版名读取降级，失败时保留 None

            # 演讲者备注
            notes_text = None
            try:
                if slide.has_notes_slide:
                    notes_text = slide.notes_slide.notes_text_frame.text.strip()
            except Exception:
                pass  # bare-handler-ok — 备注提取降级，失败时保留 None

            elements: list[PageElement] = []
            resolver = _PptxStyleResolver(prs, slide)

            # 按 z-order 遍历 shape
            for shape in slide.shapes:
                element = self._convert_shape(shape, resolver=resolver)
                if element is not None:
                    elements.append(element)

            pages.append(
                Page(
                    index=slide_idx,
                    elements=elements,
                    layout_name=layout_name,
                    master_name=master_name,
                    slide_number=slide_idx + 1,
                    notes=notes_text or None,
                )
            )

        logger.info(
            "PPTX 解析完毕: %d slides, %d 总元素", len(pages), sum(len(p.elements) for p in pages)
        )

        return Document(
            source_path=str(source_path),
            format="pptx",
            metadata=metadata,
            pages=pages,
        )

    # ── Shape 转换 ───────────────────────────────────────────

    def _convert_shape(
        self, shape: Any, transform: Any = None, resolver: Any = None
    ) -> PageElement | None:
        """将单个 Shape 转换为 PageElement。
        单个 shape 转换失败不影响同一 Slide 的其他 shape。

        transform: 可选的 (left, top, width, height) → 绝对坐标变换。
        Group 子元素坐标是相对 group 的局部坐标；2026-10-28 修复了
        未变换导致 FMT-005/对齐把局部坐标当页面坐标的问题。
        """
        try:
            shape_type = shape.shape_type

            if shape_type == MSO_SHAPE_TYPE.GROUP:
                return self._convert_group(shape, transform, resolver)

            if shape.has_table:
                return self._apply_transform(self._convert_table(shape), transform)

            if shape.has_text_frame:
                return self._apply_transform(self._convert_text_frame(shape, resolver), transform)

            if shape_type == MSO_SHAPE_TYPE.PICTURE:
                return self._apply_transform(self._convert_image(shape), transform)

            if shape_type == MSO_SHAPE_TYPE.CHART:
                return self._apply_transform(self._convert_chart(shape), transform)

            return None
        except Exception as e:
            # 宽捕获有据 (2026-09-06 审查 B-2): 单 shape 失败降级跳过, 不中断
            # 整文件转换 — python-pptx/lxml 对损坏 shape 可能抛窄列表
            # (ValueError/TypeError/...) 之外的异常 (如 OSError), 与 docx_converter
            # 的宽 Exception 策略对齐
            # 安全获取 shape 标识 — 避免 except 块内二次异常 (shape 属性访问可能同样失败)
            try:
                shape_label = f"{shape.name} (type={shape.shape_type})"
            except Exception:
                shape_label = f"<unknown shape: {type(shape).__name__}>"
            logger.warning("Shape 转换失败: %s: %s", shape_label, e)
            return None

    def _convert_text_frame(self, shape: Any, resolver: Any = None) -> PageElement:
        """转换文本框/占位符"""
        tf = shape.text_frame
        paragraphs: list[Paragraph] = []

        for para in tf.paragraphs:
            runs: list[Run] = []
            # 行距: 固定行距返回 Centipoints (Length, int 子类)，转为 pt 以满足 float|None 契约 (F5)
            line_spacing = para.line_spacing if para.line_spacing else None
            if isinstance(line_spacing, Length):
                line_spacing = line_spacing.pt
            for run_elem in para.runs:
                font = run_elem.font
                # 安全获取颜色
                try:
                    font_color = (
                        _rgb_to_hex(font.color.rgb) if font.color and font.color.rgb else None
                    )
                except Exception:
                    font_color = None

                # eastAsia 中文字体: a:rPr 下的 a:ea typeface
                # (python-pptx font.name 只读 a:latin，不含中文显示字体)
                font_name_east_asia = _ea_typeface(run_elem)

                effective_name = None
                effective_ea = None
                effective_size = None
                inherited_size = False
                if resolver is not None:
                    (
                        effective_name,
                        effective_ea,
                        effective_size,
                        inherited_size,
                    ) = resolver.resolve_run(shape, para, run_elem, para.level)

                runs.append(
                    Run(
                        text=run_elem.text,
                        font_name=font.name,
                        font_name_east_asia=font_name_east_asia,
                        # is not None (falsy 约定): 显式 0 字号是有效信息, 不作 truthy 短路
                        font_size=font.size / 12700 if font.size is not None else None,  # EMU → pt
                        bold=font.bold,
                        italic=font.italic,
                        underline=font.underline,
                        color=font_color,
                        effective_font_name=effective_name,
                        effective_font_name_east_asia=effective_ea,
                        effective_font_size=effective_size,
                        font_size_inherited=inherited_size,
                    )
                )

            bullet_type, bullet_char = _pptx_bullet(para)
            paragraphs.append(
                Paragraph(
                    text=para.text,
                    runs=runs,
                    level=para.level,
                    alignment=_pptx_alignment(para.alignment),
                    space_before=para.space_before.pt if para.space_before else None,
                    space_after=para.space_after.pt if para.space_after else None,
                    line_spacing=line_spacing,
                    bullet_type=bullet_type,
                    bullet_char=bullet_char,
                )
            )

        # 判断是否为占位符
        is_placeholder = shape.is_placeholder
        ph_type = None
        if is_placeholder:
            try:
                ph_type = shape.placeholder_format.type
            except Exception:
                ph_type = None  # 占位符格式损坏，回退为通用占位符

        return PageElement(
            type="text_frame",
            paragraphs=paragraphs,
            left=_emu_to_pt(shape.left) if shape.left is not None else None,
            top=_emu_to_pt(shape.top) if shape.top is not None else None,
            width=_emu_to_pt(shape.width) if shape.width is not None else None,
            height=_emu_to_pt(shape.height) if shape.height is not None else None,
            shape_name=shape.name,
            is_title=(is_placeholder and ph_type in (1, 3, 5)),
            is_body=(
                is_placeholder and ph_type in (2, 4, 6)
            ),  # BODY=2, SUBTITLE=4, VERTICAL_BODY=6
            is_placeholder=is_placeholder,
            placeholder_type=_placeholder_type_name(ph_type),
            auto_size=_enum_name(tf.auto_size),
            word_wrap=tf.word_wrap,
            margin_left=_emu_to_pt(tf.margin_left),
            margin_top=_emu_to_pt(tf.margin_top),
            margin_right=_emu_to_pt(tf.margin_right),
            margin_bottom=_emu_to_pt(tf.margin_bottom),
            vertical_anchor=_enum_name(tf.vertical_anchor),
        )

    def _convert_table(self, shape: Any) -> PageElement | None:
        """转换表格"""
        table = shape.table
        if len(table.rows) == 0:
            return None  # 空表格 — 无有意义内容
        cells: list[TableCell] = []
        for row_idx, row in enumerate(table.rows):
            for col_idx, cell in enumerate(row.cells):
                tf = cell.text_frame
                cell_text = tf.text.strip()

                # 取第一个 run 的格式作为单元格格式
                font_name = None
                font_size = None
                font_color = None
                if tf.paragraphs and tf.paragraphs[0].runs:
                    first_run = tf.paragraphs[0].runs[0]
                    font_name = first_run.font.name
                    if first_run.font.size is not None:  # falsy 约定: 0 字号不吞
                        font_size = first_run.font.size / 12700
                    try:
                        if first_run.font.color and first_run.font.color.rgb:
                            font_color = _rgb_to_hex(first_run.font.color.rgb)
                    except Exception:
                        font_color = None  # bare-handler-ok — 主题色等无法取 RGB，降级

                # 单元格底色 (仅 solid 纯色填充；渐变/图案/无填充 → None)
                fill_color = None
                try:
                    if cell.fill.type == MSO_FILL_TYPE.SOLID:
                        fill_color = _rgb_to_hex(cell.fill.fore_color.rgb)
                except Exception:
                    fill_color = None  # bare-handler-ok — 异常填充结构，降级

                cells.append(
                    TableCell(
                        text=cell_text,
                        row=row_idx,
                        col=col_idx,
                        font_name=font_name,
                        font_size=font_size,
                        fill_color=fill_color,
                        font_color=font_color,
                        margin_left=_emu_to_pt(cell.margin_left),
                        margin_top=_emu_to_pt(cell.margin_top),
                        margin_right=_emu_to_pt(cell.margin_right),
                        margin_bottom=_emu_to_pt(cell.margin_bottom),
                    )
                )

        # 按行分组 (单次遍历)
        row_map: dict[int, list[TableCell]] = defaultdict(list)
        for c in cells:
            row_map[c.row].append(c)
        rows = [row_map[r] for r in sorted(row_map)]

        # 表格几何 (FMT-TABLE-FIT): 行高/列宽；0 表示自动/未设置 → 不参与判定
        row_heights = [
            _emu_to_pt(r.height) if r.height is not None and r.height > 0 else 0.0
            for r in table.rows
        ]
        col_widths = [
            _emu_to_pt(c.width) if c.width is not None and c.width > 0 else 0.0
            for c in table.columns
        ]

        return PageElement(
            type="table",
            tables=rows,
            table_row_heights=row_heights,
            table_col_widths=col_widths,
            left=_emu_to_pt(shape.left) if shape.left is not None else None,
            top=_emu_to_pt(shape.top) if shape.top is not None else None,
            width=_emu_to_pt(shape.width) if shape.width is not None else None,
            height=_emu_to_pt(shape.height) if shape.height is not None else None,
            shape_name=shape.name,
        )

    def _convert_image(self, shape: Any) -> PageElement:
        """转换图片 — 仅保留格式/尺寸/alt 元数据，不把整图 blob 载入内存 (P1-5)"""
        image_ext = "unknown"
        px_width = px_height = None
        if shape.image and shape.image.content_type:
            image_ext = shape.image.content_type.split("/")[-1]
            if image_ext.startswith("x-"):
                image_ext = image_ext[2:]  # "x-emf" → "emf"
            try:
                px_width, px_height = shape.image.size
            except Exception:
                px_width = px_height = None

        alt_text = None
        try:
            c_nv_pr = shape._element.find(".//" + qn("p:cNvPr"))
            if c_nv_pr is not None:
                alt_text = c_nv_pr.get("descr") or c_nv_pr.get("title")
        except Exception:
            alt_text = None

        return PageElement(
            type="image",
            left=_emu_to_pt(shape.left) if shape.left is not None else None,
            top=_emu_to_pt(shape.top) if shape.top is not None else None,
            width=_emu_to_pt(shape.width) if shape.width is not None else None,
            height=_emu_to_pt(shape.height) if shape.height is not None else None,
            shape_name=shape.name,
            image_ext=image_ext,
            image_alt_text=alt_text,
            image_px_width=px_width,
            image_px_height=px_height,
        )

    def _convert_chart(self, shape: Any) -> PageElement:
        """转换图表 — 仅保留类型/标题/图例元数据，不读内嵌 Excel 整包 blob (P1-5)"""
        chart_type = None
        has_title = None
        chart_title = None
        has_legend = None
        try:
            chart = shape.chart
            chart_type = str(chart.chart_type) if chart.chart_type else None
            has_title = bool(chart.has_title)
            if has_title:
                try:
                    chart_title = chart.chart_title.text_frame.text.strip() or None
                except Exception:
                    chart_title = None
            has_legend = bool(chart.has_legend)
        except Exception:
            pass  # bare-handler-ok — 图表元数据提取降级，失败时保留 None，不阻塞审查

        return PageElement(
            type="chart",
            left=_emu_to_pt(shape.left) if shape.left is not None else None,
            top=_emu_to_pt(shape.top) if shape.top is not None else None,
            width=_emu_to_pt(shape.width) if shape.width is not None else None,
            height=_emu_to_pt(shape.height) if shape.height is not None else None,
            shape_name=shape.name,
            chart_type=chart_type,
            chart_has_title=has_title,
            chart_title=chart_title,
            chart_has_legend=has_legend,
        )

    @staticmethod
    def _apply_transform(element: PageElement | None, transform: Any) -> PageElement | None:
        """把 (left, top, width, height) 变换到绝对坐标；None 安全。"""
        if element is None or transform is None:
            return element
        left, top, width, height = transform(
            element.left, element.top, element.width, element.height
        )
        element.left = left
        element.top = top
        element.width = width
        element.height = height
        return element

    def _group_child_transform(self, shape: Any, parent_transform: Any = None) -> Any:
        """构造 group 子坐标 → 幻灯片绝对坐标的变换。

        OOXML group 的 a:xfrm 同时包含：
        - off/ext: group 在父坐标系中的位置/尺寸；
        - chOff/chExt: 子元素坐标系的偏移/尺寸。
        子元素 left/top 是相对 chOff 的局部坐标，必须按比例映射：
            abs = off + (child - chOff) * ext / chExt
        """
        gx = _emu_to_pt(shape.left) if shape.left is not None else None
        gy = _emu_to_pt(shape.top) if shape.top is not None else None
        gw = _emu_to_pt(shape.width) if shape.width is not None else None
        gh = _emu_to_pt(shape.height) if shape.height is not None else None
        if parent_transform is not None:
            gx, gy, gw, gh = parent_transform(gx, gy, gw, gh)
        if gx is None or gy is None or gw is None or gh is None or gw <= 0 or gh <= 0:
            return parent_transform

        ch_off_x = ch_off_y = 0.0
        ch_ext_w, ch_ext_h = gw, gh
        try:
            grp_sp_pr = shape._element.find(qn("p:grpSpPr"))
            xfrm = grp_sp_pr.find(qn("a:xfrm")) if grp_sp_pr is not None else None
            if xfrm is not None:
                ch_off = xfrm.find(qn("a:chOff"))
                ch_ext = xfrm.find(qn("a:chExt"))
                if ch_off is not None:
                    ch_off_x = _emu_to_pt(ch_off.get("x")) or 0.0
                    ch_off_y = _emu_to_pt(ch_off.get("y")) or 0.0
                if ch_ext is not None:
                    ch_ext_w = _emu_to_pt(ch_ext.get("cx")) or gw
                    ch_ext_h = _emu_to_pt(ch_ext.get("cy")) or gh
        except Exception:
            # 异常 XML 结构: 退化为恒等变换，不丢失子元素
            return parent_transform

        if ch_ext_w <= 0 or ch_ext_h <= 0:
            return parent_transform

        scale_x = gw / ch_ext_w
        scale_y = gh / ch_ext_h
        translate_x = gx - ch_off_x * scale_x
        translate_y = gy - ch_off_y * scale_y

        def _transform(left, top, width, height):
            return (
                left * scale_x + translate_x if left is not None else None,
                top * scale_y + translate_y if top is not None else None,
                width * scale_x if width is not None else None,
                height * scale_y if height is not None else None,
            )

        return _transform

    def _convert_group(
        self, shape: Any, transform: Any = None, resolver: Any = None
    ) -> PageElement:
        """转换群组 — 递归解析子形状并变换到幻灯片绝对坐标。"""
        child_transform = self._group_child_transform(shape, transform)
        child_elements: list[PageElement] = []
        for child in shape.shapes:
            element = self._convert_shape(child, child_transform, resolver)
            if element is not None:
                child_elements.append(element)

        group_element = PageElement(
            type="group",
            children=child_elements,
            left=_emu_to_pt(shape.left) if shape.left is not None else None,
            top=_emu_to_pt(shape.top) if shape.top is not None else None,
            width=_emu_to_pt(shape.width) if shape.width is not None else None,
            height=_emu_to_pt(shape.height) if shape.height is not None else None,
            shape_name=shape.name,
        )
        return self._apply_transform(group_element, transform) or group_element

    # ── 图表数据提取 ─────────────────────────────────────────
    # (P1-5: 不再读取内嵌 Excel 整包 blob — 模型仅保留 chart_type)


# ── 工具函数 ────────────────────────────────────────────────


def _placeholder_type_name(ph_type) -> str | None:
    """PPTX placeholder 枚举 → 语义名称。"""
    if ph_type is None:
        return None
    try:
        value = int(ph_type)
    except (TypeError, ValueError):
        return None
    return {
        1: "title",  # TITLE
        3: "title",  # CENTER_TITLE
        5: "title",  # VERTICAL_TITLE
        2: "body",  # BODY
        6: "body",  # VERTICAL_BODY
        4: "subtitle",  # SUBTITLE
        13: "slide_number",  # SLIDE_NUMBER
        15: "footer",  # FOOTER
        16: "date",  # DATE
        14: "header",  # HEADER
    }.get(value, "other")


def _enum_name(value) -> str | None:
    """枚举 → 名称 (兼容 python-pptx 的 str 表示)。"""
    if value is None:
        return None
    name = getattr(value, "name", None)
    if name:
        return str(name)
    text = str(value)
    return text.split(".")[-1] if "." in text else text


def _pptx_bullet(para) -> tuple[str | None, str | None]:
    """提取段落项目符号格式 (2026-10-28)。

    PowerPoint 的真实项目符号在 a:pPr 的 a:buChar / a:buAutoNum，
    不在段落文本里。旧实现只检查文本前缀，导致 FMT-007 对真实 PPT 半盲。
    """
    try:
        pPr = para._p.find(qn("a:pPr"))
        if pPr is None:
            return None, None
        if pPr.find(qn("a:buNone")) is not None:
            return "none", None
        bu_char = pPr.find(qn("a:buChar"))
        if bu_char is not None:
            return "char", bu_char.get("char")
        if pPr.find(qn("a:buAutoNum")) is not None:
            return "number", None
    except Exception:
        pass  # bare-handler-ok — 异常 XML 结构，项目符号降级为 None
    return None, None


def _ea_typeface(run_elem) -> str | None:
    """只读提取 run 的 a:ea typeface (F4)。

    不使用 run.font._rPr (get_or_add 会凭空创建空 a:rPr)，改走只读
    run._r.find(qn("a:rPr"))；a:rPr 或 a:ea 不存在时返回 None，保持现有行为。
    """
    try:
        rPr = run_elem._r.find(qn("a:rPr"))
        if rPr is not None:
            ea = rPr.find(qn("a:ea"))
            if ea is not None:
                return ea.get("typeface")
    except Exception:
        pass  # bare-handler-ok — ea 字体提取降级，失败时保留 None
    return None


def _emu_to_pt(emu_value) -> float | None:
    """EMU (English Metric Unit) → points (1 pt = 12700 EMU)"""
    if emu_value is None:
        return None
    if isinstance(emu_value, (int, float)):
        return round(emu_value / 12700, 2)
    return round(int(emu_value) / 12700, 2)


def _rgb_to_hex(rgb) -> str | None:
    """RGB 颜色 → hex 字符串"""
    if rgb is None:
        return None
    try:
        return str(rgb)
    except Exception:
        return None


def _pptx_alignment(align) -> str | None:
    """python-pptx 对齐枚举 → 字符串"""
    if align is None:
        return None
    mapping = {
        1: "left",
        2: "center",
        3: "right",
        4: "justify",
    }
    return mapping.get(int(align), None)
