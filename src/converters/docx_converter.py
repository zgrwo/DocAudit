"""DOCX 转换器 — 使用 python-docx 解析，保留段落/字符样式信息"""

import logging
import re
from collections import defaultdict
from pathlib import Path

from docx import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Length
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

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

ALIGNMENT_MAP = {
    WD_ALIGN_PARAGRAPH.LEFT: "left",
    WD_ALIGN_PARAGRAPH.CENTER: "center",
    WD_ALIGN_PARAGRAPH.RIGHT: "right",
    WD_ALIGN_PARAGRAPH.JUSTIFY: "justify",
}

# 样式型标题回退 (HIGH-1): "Heading N" 样式名 → 0-based 层级 N-1
HEADING_STYLE_RE = re.compile(r"^Heading\s+(\d+)$", re.IGNORECASE)


def _rpr_font_name(rpr, attr: str) -> str | None:
    """从 w:rPr/w:rFonts 读取 ascii/hAnsi/eastAsia 字体。"""
    if rpr is None:
        return None
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        return None
    return rfonts.get(qn(attr))


def _rpr_size_pt(rpr) -> float | None:
    """w:sz val 为半磅 → pt。"""
    if rpr is None:
        return None
    sz = rpr.find(qn("w:sz"))
    if sz is None:
        return None
    try:
        return int(sz.get(qn("w:val"))) / 2.0
    except (TypeError, ValueError):
        return None


class _DocxStyleResolver:
    """解析 DOCX 的样式继承字体/字号。

    顺序：run rPr → paragraph style → based-on style → Normal → docDefaults。
    python-docx 对继承值返回 None，旧实现导致 FMT-001/002 对 Word 文档漏检。
    """

    def __init__(self, doc):
        self.doc = doc
        self._defaults = self._read_doc_defaults()

    def _read_doc_defaults(self) -> dict:
        result: dict[str, object] = {"size": None, "latin": None, "ea": None}
        try:
            styles_el = self.doc.styles.element
            defaults = styles_el.find(qn("w:docDefaults"))
            if defaults is None:
                return result
            rpr_default = defaults.find(qn("w:rPrDefault"))
            if rpr_default is None:
                return result
            rpr = rpr_default.find(qn("w:rPr"))
            result["size"] = _rpr_size_pt(rpr)
            result["latin"] = _rpr_font_name(rpr, "w:ascii") or _rpr_font_name(rpr, "w:hAnsi")
            result["ea"] = _rpr_font_name(rpr, "w:eastAsia")
        except Exception:
            return result
        return result

    def _style_chain(self, style):
        seen: set[int] = set()
        current = style
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            yield current
            try:
                current = current.base_style
            except Exception:
                return

    def resolve_run(self, para, run) -> tuple:
        """返回 (effective_latin, effective_ea, effective_size, inherited_size)。"""
        latin = run.font.name
        try:
            rpr = run._element.rPr
        except Exception:
            rpr = None
        east_asia = _rpr_font_name(rpr, "w:eastAsia")
        explicit_size = run.font.size.pt if run.font.size is not None else None
        size = explicit_size

        # 段落样式 → based-on 链
        for style in self._style_chain(getattr(para, "style", None)):
            style_font = getattr(style, "font", None)
            if latin is None and style_font is not None and style_font.name:
                latin = style_font.name
            if east_asia is None:
                east_asia = _rpr_font_name(getattr(style.element, "rPr", None), "w:eastAsia")
            if size is None and style_font is not None and style_font.size is not None:
                size = style_font.size.pt

        if size is None:
            size = self._defaults.get("size")
        if latin is None:
            latin = self._defaults.get("latin")
        if east_asia is None:
            east_asia = self._defaults.get("ea")

        return latin, east_asia, size, explicit_size is None and size is not None


class _DocxNumberingResolver:
    """解析 DOCX 项目符号/编号 (w:numPr + numbering.xml) — 2026-10-29。

    列表段落的符号不存在于文本里：Word 用 numPr(numId, ilvl) 引用 numbering.xml
    的抽象编号定义。不解析时 DOCX 的 FMT-007（符号样式一致性）、
    TXT-BULLET-PUNCT（末尾标点）对列表完全失明。

    解析顺序：段落 numPr → 段落样式 numPr（python-docx 的 List Bullet/Number
    样式把 numPr 写在样式定义里）。
    """

    # Symbol/Wingdings 私有使用区码位 → 统一为通用圆点（审计器按类型而非字形判定）
    _PRIVATE_USE_BULLET = "•"

    def __init__(self, doc):
        self._levels: dict[tuple[str, str], str] = {}
        self._chars: dict[tuple[str, str], str | None] = {}
        try:
            self._parse_numbering(doc)
        except Exception as e:
            logger.debug("DOCX numbering 解析失败，列表符号降级为空: %s", e)

    def _parse_numbering(self, doc) -> None:
        try:
            numbering = doc.part.numbering_part.element
        except Exception:
            return  # 无 numbering 部件（无列表文档）
        namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        abstract = {
            a.get(f"{{{namespaces['w']}}}abstractNumId"): a
            for a in numbering.findall("w:abstractNum", namespaces)
        }
        for num in numbering.findall("w:num", namespaces):
            num_id = num.get(f"{{{namespaces['w']}}}numId")
            abs_ref = num.find("w:abstractNumId", namespaces)
            abs_id = abs_ref.get(f"{{{namespaces['w']}}}val") if abs_ref is not None else None
            absnum = abstract.get(abs_id)
            if num_id is None or absnum is None:
                continue
            for lvl in absnum.findall("w:lvl", namespaces):
                ilvl = lvl.get(f"{{{namespaces['w']}}}ilvl", "0")
                fmt = lvl.find("w:numFmt", namespaces)
                text_el = lvl.find("w:lvlText", namespaces)
                fmt_val = fmt.get(f"{{{namespaces['w']}}}val") if fmt is not None else None
                raw_text = text_el.get(f"{{{namespaces['w']}}}val") if text_el is not None else None
                key = (str(num_id), str(ilvl))
                if fmt_val == "bullet":
                    self._levels[key] = "char"
                    self._chars[key] = self._normalize_bullet_char(raw_text)
                elif fmt_val == "none":
                    self._levels[key] = "none"
                elif fmt_val:
                    self._levels[key] = "number"

    @classmethod
    def _normalize_bullet_char(cls, raw: str | None) -> str | None:
        if not raw:
            return None
        ch = raw[0]
        if 0xF000 <= ord(ch) <= 0xF0FF:  # Symbol/Wingdings 私有区
            return cls._PRIVATE_USE_BULLET
        return ch

    @staticmethod
    def _paragraph_num_pr(para):
        """取段落 numPr；段落级缺失时回退到样式级。"""
        num_pr = None
        try:
            pPr = para._element.pPr
            if pPr is not None:
                num_pr = pPr.numPr
        except Exception:
            num_pr = None
        if num_pr is not None:
            return num_pr
        try:
            style = para.style
            style_name = style.name or ""
            style_pPr = style._element.pPr
            # 标题样式的 numPr 是章节编号（1. / 2.1 等），不是项目符号；
            # 旧实现无条件回退 → FMT-007 把标题当 bullet 逐页误报（2026-10-29 审查）
            if HEADING_STYLE_RE.match(style_name):
                return None
            if style_pPr is not None and getattr(style_pPr, "outlineLvl", None) is not None:
                return None
            if style_pPr is not None:
                return style_pPr.numPr
        except Exception:
            return None
        return None

    def resolve(self, para) -> tuple[str | None, str | None]:
        """返回 (bullet_type, bullet_char)；非列表段落返回 (None, None)。"""
        num_pr = self._paragraph_num_pr(para)
        if num_pr is None:
            return (None, None)
        try:
            num_id = num_pr.numId.val if num_pr.numId is not None else None
            ilvl = num_pr.ilvl.val if num_pr.ilvl is not None else 0
        except Exception:
            return (None, None)
        if num_id is None:
            return (None, None)
        key = (str(num_id), str(ilvl))
        return self._levels.get(key), self._chars.get(key)


class DocxConverter(BaseConverter):
    """将 DOCX 文件转换为统一 Document 模型。

    保留信息：
    - 段落样式名称 + 大纲级别
    - Run 级字体/字号/加粗/斜体/颜色
    - 段落对齐方式 + 间距
    - 表格结构
    - 文档元素顺序（段落和表格交错出现）
    """

    def can_handle(self, source_path: str | Path) -> bool:
        ext = Path(source_path).suffix.lower().lstrip(".")
        return ext in ("docx", "doc")

    def convert(self, source_path: str | Path) -> Document:
        source_path = Path(source_path)
        logger.info("解析 DOCX: %s", source_path.name)

        if source_path.suffix.lower() == ".doc":
            raise ValueError(
                "旧版二进制 .doc 不受支持，请先用 Word/LibreOffice 另存为 .docx 后重试"
            )

        try:
            doc = DocxDocument(str(source_path))
        except Exception as e:
            logger.error("无法打开 DOCX 文件: %s", e)
            raise ValueError(f"无法解析 DOCX 文件: {source_path}") from e

        # --- 元数据 ---
        metadata = self._extract_metadata(doc)

        # --- 构建元素查找表 (局部变量, 线程安全) ---
        para_map = {p._element: p for p in doc.paragraphs}
        table_map = {t._element: t for t in doc.tables}
        style_resolver = _DocxStyleResolver(doc)
        numbering_resolver = _DocxNumberingResolver(doc)

        # --- 遍历文档主体（保留段落和表格的交错顺序） ---
        elements: list[PageElement] = []

        for child in doc.element.body:
            tag = _tag_name(child)

            if tag == "p":
                para = para_map.get(child)
                if para is not None:
                    elem = self._convert_paragraph(para, style_resolver, numbering_resolver)
                    if elem is not None:
                        elements.append(elem)

            elif tag == "tbl":
                tbl = table_map.get(child)
                if tbl is not None:
                    elem = self._convert_table(tbl)
                    if elem is not None:
                        elements.append(elem)

            elif tag == "sdt":
                # SDT（内容控件）: 递归进入 sdtContent，段落/表格用 python-docx 包装器
                # 重新绑定父节点。旧实现用 para_map.get(item) 查表，而 Document.paragraphs
                # 不包含 SDT 内部段落 → 控件文本被静默丢弃（2026-10-29 审查 P1）。
                for block_tag, item in _iter_sdt_content(child):
                    if block_tag == "p":
                        elem = self._convert_paragraph(
                            DocxParagraph(item, doc), style_resolver, numbering_resolver
                        )
                    else:
                        elem = self._convert_table(DocxTable(item, doc))
                    if elem is not None:
                        elements.append(elem)

        # 未解析嵌套内容提示 (仅日志，不改变解析行为)
        self._warn_unparsed_nested_content(doc)

        # 页眉/页脚/脚注文本 → 辅助元素 (只参与语言/术语类审查)
        auxiliary = self._extract_auxiliary_elements(doc)

        logger.info("DOCX 解析完毕: %d 元素 (%d 辅助文本)", len(elements), len(auxiliary))

        # 分页
        pages = self._split_into_pages(elements)

        return Document(
            source_path=str(source_path),
            format="docx",
            metadata=metadata,
            pages=pages,
            auxiliary_elements=auxiliary,
        )

    def _extract_auxiliary_elements(self, doc: DocxDocument) -> list[PageElement]:
        """提取页眉/页脚/脚注文本 (2026-10-29)。

        只保留文本 (不做版面几何)，供 LanguageAuditor 做中英混排/标点/
        术语/禁用词检查。按 (类型, 文本) 去重：多节文档常共享同一页眉。
        """
        auxiliary: list[PageElement] = []
        seen: set[tuple[str, str]] = set()

        def add(kind: str, label: str, text: str) -> None:
            cleaned = (text or "").strip()
            if not cleaned:
                return
            key = (kind, cleaned)
            if key in seen:
                return
            seen.add(key)
            paragraphs = [Paragraph(text=line) for line in cleaned.splitlines() if line.strip()]
            auxiliary.append(
                PageElement(
                    type="text_frame",
                    placeholder_type=kind,
                    shape_name=label,
                    paragraphs=paragraphs,
                )
            )

        try:
            for section in doc.sections:
                for hf, kind, label in (
                    (section.header, "header", "页眉"),
                    (section.footer, "footer", "页脚"),
                    (section.first_page_header, "header", "首页页眉"),
                    (section.first_page_footer, "footer", "首页页脚"),
                    (section.even_page_header, "header", "偶数页页眉"),
                    (section.even_page_footer, "footer", "偶数页页脚"),
                ):
                    text = "\n".join(p.text for p in hf.paragraphs if p.text.strip())
                    add(kind, label, text)
        except Exception as e:
            logger.warning("页眉/页脚提取失败，跳过页眉页脚审查: %s", e)

        # 脚注: 通过 rels 找到 footnotes 部件并解析 w:footnote (id <= 0 为分隔符)
        try:
            for rel in doc.part.rels.values():
                if rel.reltype.endswith("/footnotes"):
                    for text in self._extract_footnote_texts(rel.target_part):
                        add("footnote", "脚注", text)
        except Exception as e:
            logger.warning("脚注提取失败，跳过脚注审查: %s", e)

        return auxiliary

    @staticmethod
    def _extract_footnote_texts(part) -> list[str]:
        """从 footnotes 部件解析正文脚注文本 (跳过 separator/continuation)。"""
        from docx.oxml import parse_xml

        try:
            root = parse_xml(part.blob)
        except Exception:
            return []
        ns_w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        texts: list[str] = []
        for footnote in root.findall(f"{ns_w}footnote"):
            fid = footnote.get(f"{ns_w}id")
            if fid is None or int(fid) <= 0:
                continue
            text = "".join(node.text or "" for node in footnote.iter(f"{ns_w}t")).strip()
            if text:
                texts.append(text)
        return texts

    def _warn_unparsed_nested_content(self, doc: DocxDocument) -> None:
        """提示当前仍未解析的嵌套内容（文本框）。

        页眉/页脚/脚注自 2026-10-29 起已提取到 `Document.auxiliary_elements`，
        不再在此告警。
        """
        # 文本框: 段落内 w:drawing/w:txbxContent (画布文本框中的文字)
        try:
            for para in doc.paragraphs:
                if para._element.findall(".//" + qn("w:txbxContent")):
                    logger.warning(
                        "段落包含文本框 (w:txbxContent) 内容，当前跳过未解析: %s",
                        para.text[:40] or "(无文本)",
                    )
        except Exception:
            pass  # bare-handler-ok — 文本框检测降级，不影响解析

    def _extract_metadata(self, doc: DocxDocument) -> DocumentMetadata:
        """提取文档元数据"""
        # 统计字数 (在 try/except 外计算，避免重复)
        word_count = sum(len(p.text.split()) for p in doc.paragraphs if p.text.strip())
        try:
            props = doc.core_properties
            return DocumentMetadata(
                title=props.title,
                author=props.author,
                created=str(props.created) if props.created else None,
                modified=str(props.modified) if props.modified else None,
                word_count=word_count,
            )
        except (AttributeError, ValueError) as e:
            logger.debug("元数据提取失败: %s", e, exc_info=True)
            return DocumentMetadata(word_count=word_count)

    def _convert_paragraph(
        self,
        para,
        style_resolver: _DocxStyleResolver | None = None,
        numbering_resolver: _DocxNumberingResolver | None = None,
    ) -> PageElement | None:
        """转换单个段落"""
        runs: list[Run] = []
        for r in para.runs:
            try:
                font = r.font
                font_color = None
                try:
                    if font.color and font.color.rgb:
                        font_color = str(font.color.rgb)
                except (AttributeError, ValueError):
                    pass

                # eastAsia 中文字体: w:rPr/w:rFonts 的 w:eastAsia 属性
                # (python-docx font.name 只读 w:ascii/w:hAnsi，不含中文显示字体)
                font_name_east_asia = None
                try:
                    rPr = r._element.rPr
                    if rPr is not None and rPr.rFonts is not None:
                        font_name_east_asia = rPr.rFonts.get(qn("w:eastAsia"))
                except Exception:
                    pass  # bare-handler-ok — eastAsia 字体提取降级，失败时保留 None

                effective_name = None
                effective_ea = None
                effective_size = None
                inherited_size = False
                if style_resolver is not None:
                    (
                        effective_name,
                        effective_ea,
                        effective_size,
                        inherited_size,
                    ) = style_resolver.resolve_run(para, r)

                runs.append(
                    Run(
                        text=r.text,
                        font_name=font.name,
                        font_name_east_asia=font_name_east_asia,
                        font_size=font.size.pt if font.size is not None else None,
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
            except Exception as e:
                # F9: 单个 run 提取失败仅跳过该 run (不丢整段格式)，并继续处理其余 run
                logger.debug("DOCX run 格式提取失败，跳过该 run: %s", e, exc_info=True)
                continue

        # 大纲级别
        level = None
        try:
            pPr = para._element.find(qn("w:pPr"))
            if pPr is not None:
                outline = pPr.find(qn("w:outlineLvl"))
                if outline is not None:
                    level = int(outline.get(qn("w:val"), "0"))
        except Exception:
            pass  # bare-handler-ok — 大纲级别提取降级，失败时保留 None

        full_text = para.text
        if not full_text.strip() and not runs:
            return None

        # 行距: 固定行距返回 Twips (Length, int 子类)，转为 pt 以满足 float|None 契约 (F5)
        line_spacing = None
        if para.paragraph_format and para.paragraph_format.line_spacing is not None:
            line_spacing = para.paragraph_format.line_spacing
            if isinstance(line_spacing, Length):
                line_spacing = line_spacing.pt

        # 判断是否为标题（Heading 样式）
        is_heading = False
        style_name = None
        try:
            style_name = para.style.name
            is_heading = style_name and "heading" in style_name.lower()
        except Exception:
            pass  # bare-handler-ok — 样式名读取降级，失败时按非标题处理

        # 样式级回退 (HIGH-1): 段落级无 outlineLvl 时，从样式定义补 level。
        # ① style 的 w:pPr/w:outlineLvl (python-docx add_heading 生成的样式型标题即此形态)
        # ② 样式名 "Heading N" → N-1 (样式未定义 outlineLvl 时)
        if is_heading and level is None:
            try:
                style_el = para.style._element
                if style_el is not None:
                    style_pPr = style_el.find(qn("w:pPr"))
                    if style_pPr is not None:
                        outline = style_pPr.find(qn("w:outlineLvl"))
                        if outline is not None:
                            level = int(outline.get(qn("w:val"), "0"))
            except Exception:
                pass  # bare-handler-ok — 样式级 outlineLvl 提取降级，失败时保留 None
            if level is None and style_name:
                m = HEADING_STYLE_RE.match(style_name)
                if m:
                    level = int(m.group(1)) - 1

        # 项目符号/编号: 段落 numPr → 样式 numPr → numbering.xml (2026-10-29)
        bullet_type = None
        bullet_char = None
        if numbering_resolver is not None:
            try:
                bullet_type, bullet_char = numbering_resolver.resolve(para)
            except Exception:
                bullet_type, bullet_char = None, None  # bare-handler-ok — 单段符号降级

        return PageElement(
            type="text_frame",
            paragraphs=[
                Paragraph(
                    text=full_text,
                    runs=runs,
                    level=level,
                    bullet_type=bullet_type,
                    bullet_char=bullet_char,
                    alignment=ALIGNMENT_MAP.get(para.alignment),
                    space_before=(
                        para.paragraph_format.space_before.pt
                        if (
                            para.paragraph_format and para.paragraph_format.space_before is not None
                        )
                        else None
                    ),
                    space_after=(
                        para.paragraph_format.space_after.pt
                        if (para.paragraph_format and para.paragraph_format.space_after is not None)
                        else None
                    ),
                    line_spacing=line_spacing,
                )
            ],
            # 段落样式名放入 style_name，shape_name 保留给 PPTX shape 名 (默认 None)
            style_name=style_name,
            # H1 或 H2 均视为标题 (与 _split_into_pages 的页面边界语义一致: level <= 1)
            is_title=is_heading and level is not None and level <= 1,
            is_body=not is_heading,
        )

    def _convert_table(self, table) -> PageElement | None:
        """转换表格"""
        if not table.rows:
            return None  # 空表格 — 无有意义内容
        try:
            cells: list[TableCell] = []
            for row_idx, row in enumerate(table.rows):
                for col_idx, cell in enumerate(row.cells):
                    cell_text = cell.text.strip()
                    # 提取第一个段落第一个 run 的字体信息
                    font_name = None
                    font_size = None
                    font_color = None
                    if cell.paragraphs and cell.paragraphs[0].runs:
                        first_run = cell.paragraphs[0].runs[0]
                        font_name = first_run.font.name
                        if first_run.font.size:
                            font_size = first_run.font.size.pt
                        try:
                            if first_run.font.color and first_run.font.color.rgb:
                                font_color = str(first_run.font.color.rgb)
                        except (AttributeError, ValueError):
                            font_color = None  # 主题色等无法取 RGB — 降级

                    # 单元格底色 (w:shd w:fill 直接指定的纯色；继承样式/无底色 → None)
                    fill_color = None
                    try:
                        tcPr = cell._tc.tcPr
                        if tcPr is not None:
                            shd = tcPr.find(qn("w:shd"))
                            if shd is not None:
                                fill = shd.get(qn("w:fill"))
                                if fill and fill.lower() != "auto":
                                    fill_color = fill.upper()
                    except Exception:
                        fill_color = None  # bare-handler-ok — 异常 XML 结构，降级

                    cells.append(
                        TableCell(
                            text=cell_text,
                            row=row_idx,
                            col=col_idx,
                            font_name=font_name,
                            font_size=font_size,
                            fill_color=fill_color,
                            font_color=font_color,
                        )
                    )

            nrows = len(table.rows)
            # 按行分组 (单次遍历，与 PptxConverter._convert_table 一致)
            row_map: dict[int, list[TableCell]] = defaultdict(list)
            for c in cells:
                row_map[c.row].append(c)
            rows: list[list[TableCell]] = [row_map[r] for r in sorted(row_map) if r < nrows]

            # 表格几何 (FMT-TABLE-FIT)：Word 自动布局下为 None/0 → 保留 0.0 占位，
            # 保证与行列索引对齐；判定时跳过 <= 0。
            row_heights: list[float] = []
            for row in table.rows:
                try:
                    h = row.height.pt if row.height is not None else 0.0
                except (AttributeError, TypeError):
                    h = 0.0
                row_heights.append(float(h) if h and h > 0 else 0.0)
            col_widths: list[float] = []
            for col in table.columns:
                try:
                    w = col.width.pt if col.width is not None else 0.0
                except (AttributeError, TypeError):
                    w = 0.0
                col_widths.append(float(w) if w and w > 0 else 0.0)

            return PageElement(
                type="table",
                tables=rows,
                table_row_heights=row_heights,
                table_col_widths=col_widths,
            )
        except Exception as e:
            logger.warning("表格转换失败: %s", e)
            return None

    def _split_into_pages(self, elements: list[PageElement]) -> list[Page]:
        """按语义边界拆分为多页：优先以标题(H1/H2)为页面边界，CHUNK_SIZE 为硬上限回退。

        这避免了将标题切到前一页末尾或后一页开头导致的假跳级问题。
        """
        pages: list[Page] = []
        CHUNK_SIZE = 40  # 硬上限回退 — 仅在无标题可用作页面边界时触发

        # 空文档直接返回单页空内容
        if not elements:
            return [Page(index=0, elements=[], slide_number=1)]

        current_chunk: list[PageElement] = []
        chunk_split_count = 0  # 统计 CHUNK_SIZE 回退触发次数，便于调试

        def _is_heading(elem: PageElement) -> bool:
            """判断元素是否为 H1 或 H2 级别标题"""
            if elem.type != "text_frame" or not elem.paragraphs:
                return False
            level = elem.paragraphs[0].level
            return level is not None and level <= 1

        for elem in elements:
            # 标题作为页面边界（但不在 chunk 为空时创建空页）
            if _is_heading(elem) and current_chunk:
                pages.append(
                    Page(
                        index=len(pages),
                        elements=current_chunk,
                        slide_number=len(pages) + 1,
                    )
                )
                current_chunk = []
            current_chunk.append(elem)
            # CHUNK_SIZE 硬上限回退：避免单页元素过多
            if len(current_chunk) >= CHUNK_SIZE:
                chunk_split_count += 1
                logger.debug(
                    "DOCX 分页: CHUNK_SIZE (%d) 回退触发 (第 %d 次)，当前页 %d 个元素",
                    CHUNK_SIZE,
                    chunk_split_count,
                    len(current_chunk),
                )
                pages.append(
                    Page(
                        index=len(pages),
                        elements=current_chunk,
                        slide_number=len(pages) + 1,
                    )
                )
                current_chunk = []

        if current_chunk:
            pages.append(
                Page(
                    index=len(pages),
                    elements=current_chunk,
                    slide_number=len(pages) + 1,
                )
            )

        return pages


def _iter_sdt_content(container) -> list[tuple[str, object]]:
    """递归取出 SDT 内容里的段落/表格元素（含嵌套 SDT，2026-10-29 审查）。

    Returns:
        [(tag, element)]，tag 为 "p" 或 "tbl"；element 为 lxml 节点，
        调用方负责用 python-docx 的 Paragraph/Table 包装（需要父 Document）。
    """
    blocks: list[tuple[str, object]] = []
    for child in container:
        child_tag = _tag_name(child)
        if child_tag in ("p", "tbl"):
            blocks.append((child_tag, child))
        elif child_tag == "sdtContent":
            blocks.extend(_iter_sdt_content(child))
        elif child_tag == "sdt":
            for inner in child:
                if _tag_name(inner) == "sdtContent":
                    blocks.extend(_iter_sdt_content(inner))
    return blocks


def _tag_name(element) -> str:
    """获取 XML 元素的标签名（去除命名空间）"""
    tag = element.tag
    return tag.split("}")[-1] if "}" in tag else tag
