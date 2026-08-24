"""PDF 转换器 — 使用 Docling 解析，保留标题层级和表格结构"""

import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

from src.converters.base import BaseConverter
from src.models.document import (
    Document,
    DocumentMetadata,
    Page,
    PageElement,
    Paragraph,
    TableCell,
)

logger = logging.getLogger(__name__)


def _hf_cache_dir() -> Path:
    """项目内 HuggingFace 模型缓存目录 (packages/hf_cache) — M5 离线注入目标"""
    return Path(__file__).resolve().parents[2] / "packages" / "hf_cache"


def _inject_hf_cache_env() -> None:
    """M5: 运行期注入 HuggingFace 环境变量 (在 DoclingConverter 实例化前调用)。

    - HF_HUB_CACHE 恒指向项目内 packages/hf_cache (setdefault，不覆盖用户显式设置)
    - 该目录存在 (离线预下载完成) 时另设 HF_HUB_OFFLINE=1，强制离线加载模型
    """
    hf_cache = _hf_cache_dir()
    os.environ.setdefault("HF_HUB_CACHE", str(hf_cache))
    if hf_cache.is_dir():
        os.environ.setdefault("HF_HUB_OFFLINE", "1")


def _ensure_ascii_install_path() -> None:
    """P0-1: Windows 下检测 Python 安装前缀路径是否含非 ASCII 字符。

    docling-parse 的 C++ 层在 Windows 上用 ANSI 代码页 fopen 打开其资源文件
    (pdf_resources/glyphs/*.dat)，路径含中文等非 ASCII 字符时 fopen 会拿到乱码
    文件名 → 资源"文件不存在" → PDF 转换必然失败 (详见 tooling-pitfalls #18)。

    仅 Windows 受限 (ANSI 代码页)；macOS/Linux 文件系统用 UTF-8 字节，中文路径
    可正常工作，无需检测。

    此函数在实例化 DoclingConverter 前调用，提前抛出可操作的错误，而非让
    docling 抛出晦涩的 "filename does not exists"。
    """
    if sys.platform != "win32":
        return  # 仅 Windows 存在 ANSI fopen 编码问题
    prefix = str(sys.prefix)
    if any(ord(c) >= 128 for c in prefix):
        raise RuntimeError(
            "PDF 转换依赖的 docling 引擎无法处理含非 ASCII 字符的安装路径 (Windows 限制)：\n"
            f"  当前 Python 安装路径: {prefix}\n"
            "请将项目与虚拟环境移动到纯英文 (ASCII) 目录后重试。\n"
            "参见 rules/tooling-pitfalls.md #18。"
        )


class PdfConverter(BaseConverter):
    """将 PDF 文件转换为统一 Document 模型。

    使用 IBM Docling 进行版面分析，保留：
    - 标题层级 (heading levels)
    - 表格结构
    - 阅读顺序
    - 页面级别的文本内容

    注意：PDF 没有字体/字号等格式属性，仅保留结构信息。
    """

    def can_handle(self, source_path: str | Path) -> bool:
        ext = Path(source_path).suffix.lower().lstrip(".")
        return ext == "pdf"

    def convert(self, source_path: str | Path) -> Document:
        source_path = Path(source_path)

        # 检查 Docling 是否可用
        try:
            from docling.document_converter import DocumentConverter as DoclingConverter
        except ImportError:
            raise ImportError(
                "PDF 转换需要安装 docling 依赖。请运行: "
                "pip install docaudit[pdf] 或 pip install docling"
            )

        logger.info("使用 Docling 解析 PDF: %s", source_path.name)

        # P0-1: 非 ASCII 安装路径下 docling C++ 层必然失败，提前抛出可操作错误
        _ensure_ascii_install_path()

        # M5: 在实例化 DoclingConverter 前注入 HF 环境变量 (项目内离线模型缓存)
        _inject_hf_cache_env()

        # Docling 转换
        converter = DoclingConverter()
        result = converter.convert(str(source_path))
        docling_doc = result.document

        # --- 元数据 ---
        metadata = DocumentMetadata(
            title=source_path.stem,
            page_count=len(docling_doc.pages) if docling_doc.pages else None,
        )

        # --- 按页遍历 Docling 输出 ---
        pages: list[Page] = []

        if docling_doc.pages:
            # 适配不同 docling 版本的页面结构:
            # - 旧版: pages 值为 DlPage，自带 cells/items/tables 内容
            # - >= 2.119: pages 值为 PageItem 引用 (仅 size/image/page_no，无内容)，
            #   内容在 document 级 texts/tables，按 item.prov[0].page_no 归属页面
            first_page = next(iter(docling_doc.pages.values()))
            if (
                hasattr(first_page, "cells")
                or hasattr(first_page, "items")
                or hasattr(first_page, "tables")
            ):
                pages = self._convert_pages_from_page_objects(docling_doc)
            else:
                pages = self._convert_pages_from_document_items(docling_doc)
        else:
            # 回退：使用 Markdown 导出并按页拆分
            md_text = docling_doc.export_to_markdown()
            for page_idx, page_text in enumerate(md_text.split("\n\n---\n\n")):
                if page_text.strip():
                    pages.append(
                        Page(
                            index=page_idx,
                            elements=[
                                PageElement(
                                    type="text_frame",
                                    paragraphs=[Paragraph(text=page_text.strip(), runs=[])],
                                )
                            ],
                            slide_number=page_idx + 1,
                        )
                    )

        if not pages:
            # 最终回退
            pages.append(
                Page(
                    index=0,
                    elements=[
                        PageElement(
                            type="text_frame",
                            paragraphs=[Paragraph(text=docling_doc.export_to_markdown(), runs=[])],
                        )
                    ],
                    slide_number=1,
                )
            )

        return Document(
            source_path=str(source_path),
            format="pdf",
            metadata=metadata,
            pages=pages,
        )

    def _convert_pages_from_page_objects(self, docling_doc) -> list[Page]:
        """旧版 docling 路径: 每页对象自带 cells/items/tables 内容"""
        pages: list[Page] = []

        for page_idx, page_key in enumerate(sorted(docling_doc.pages.keys())):
            docling_page = docling_doc.pages[page_key]
            elements: list[PageElement] = []

            # 提取页面上的文本项 (适配 Docling 不同版本 API)
            try:
                uses_cells = False
                if hasattr(docling_page, "cells"):
                    uses_cells = True
                    for cell in docling_page.cells:
                        elem = self._convert_cell(cell)
                        if elem is not None:
                            elements.append(elem)
                    # cells API 已包含表格内容，不重复提取
                elif hasattr(docling_page, "items"):
                    for item in docling_page.items:
                        elem = self._convert_item(item)
                        if elem is not None:
                            elements.append(elem)
                else:
                    # 未知 Docling API: 回退到文本导出，避免静默丢页
                    logger.debug("Docling page %d 结构未知，回退到文本导出", page_idx)
                    try:
                        page_text = (
                            docling_page.export_to_markdown()
                            if hasattr(docling_page, "export_to_markdown")
                            else ""
                        )
                    except Exception:
                        page_text = ""
                    if page_text.strip():
                        elements.append(
                            PageElement(
                                type="text_frame",
                                paragraphs=[Paragraph(text=page_text.strip(), runs=[])],
                            )
                        )
                # 非 cells API 路径: 尝试提取结构化表格 (统一处理，避免 items/fallback 分支重复)
                if not uses_cells and hasattr(docling_page, "tables"):
                    for table in docling_page.tables:
                        elem = self._convert_docling_table(table)
                        if elem is not None:
                            elements.append(elem)
            except Exception as e:
                logger.warning("Docling 页面 %d 解析失败: %s，跳过该页", page_idx, e)

            pages.append(
                Page(
                    index=page_idx,
                    elements=elements,
                    slide_number=page_idx + 1,
                )
            )
        return pages

    def _convert_pages_from_document_items(self, docling_doc) -> list[Page]:
        """docling >= 2.119 路径: pages 值为无内容的 PageItem 引用。

        内容在 document 级 texts/tables，按 item.prov[0].page_no 归属到各页；
        无 prov 归属的项并入第一页，避免内容丢失。
        """
        page_texts: dict[int | None, list] = defaultdict(list)
        for item in getattr(docling_doc, "texts", []) or []:
            page_nos = self._item_page_nos(item)
            if page_nos:
                # F3: 跨页 item 并入所有涉及页面 (旧实现只取 prov[0]，丢页)
                for pn in page_nos:
                    page_texts[pn].append(item)
            else:
                page_texts[None].append(item)
        page_tables: dict[int | None, list] = defaultdict(list)
        for table in getattr(docling_doc, "tables", []) or []:
            page_nos = self._item_page_nos(table)
            if page_nos:
                for pn in page_nos:
                    page_tables[pn].append(table)
            else:
                page_tables[None].append(table)

        page_keys = sorted(docling_doc.pages.keys())
        fallback_page_no = page_keys[0] if page_keys else None
        orphan_texts = page_texts.get(None, [])
        orphan_tables = page_tables.get(None, [])

        pages: list[Page] = []
        for page_idx, page_key in enumerate(page_keys):
            elements: list[PageElement] = []
            page_items = page_texts.get(page_key, [])
            if page_key == fallback_page_no:
                page_items = page_items + orphan_texts
            for item in page_items:
                elem = self._convert_item(item)
                if elem is not None:
                    elements.append(elem)
            page_tables_on_page = page_tables.get(page_key, [])
            if page_key == fallback_page_no:
                page_tables_on_page = page_tables_on_page + orphan_tables
            for table in page_tables_on_page:
                elem = self._convert_docling_table(table)
                if elem is not None:
                    elements.append(elem)

            pages.append(
                Page(
                    index=page_idx,
                    elements=elements,
                    slide_number=page_idx + 1,
                )
            )
        return pages

    @staticmethod
    def _item_page_nos(item) -> list[int]:
        """取 item 归属页码列表 (docling >= 2.119: item.prov[].page_no)。

        F3: 遍历全部 prov 而非只取 prov[0]——跨页 item (如跨页段落/表格)
        并入所有涉及页面；无 prov 或 page_no 为 None 时返回空列表 (调用方并入首页)。
        """
        prov = getattr(item, "prov", None) or []
        return [p.page_no for p in prov if getattr(p, "page_no", None) is not None]

    def _convert_cell(self, cell) -> PageElement | None:
        """Docling cell → PageElement

        表格 cell 暂不拆分结构，统一作为 text_frame 保留文本内容。
        """
        cell_text = getattr(cell, "text", "")
        if not cell_text or not str(cell_text).strip():
            return None

        return PageElement(
            type="text_frame",
            paragraphs=[Paragraph(text=str(cell_text).strip(), runs=[])],
        )

    def _convert_item(self, item) -> PageElement | None:
        """Docling item → PageElement"""
        item_text = getattr(item, "text", str(item))
        if not item_text or not str(item_text).strip():
            return None

        # 尝试获取标题层级: 旧版 heading_level 属性 / docling >= 2.119 label 枚举
        level = getattr(item, "heading_level", None)
        if level is None:
            label = getattr(item, "label", None)
            if label is not None:
                label_str = label.value if hasattr(label, "value") else str(label)
                if label_str == "title":
                    level = 1
                elif label_str == "section_header":
                    level = 2

        return PageElement(
            type="text_frame",
            paragraphs=[
                Paragraph(
                    text=str(item_text).strip(),
                    runs=[],
                    level=level,
                )
            ],
            is_title=(level == 1),
        )

    def _convert_docling_table(self, table) -> PageElement | None:
        """Docling table → PageElement (表格结构)"""
        try:
            rows: list[list[TableCell]] = []
            if hasattr(table, "export_to_dataframe"):
                try:
                    import pandas  # noqa: F401 — availability check
                except ImportError:
                    logger.warning("PDF 表格转换需要 pandas。请运行: pip install docaudit[pdf]")
                    return None
                df = table.export_to_dataframe()
                if df is None:
                    logger.debug("Docling table.export_to_dataframe() 返回 None，跳过")
                    return None
                for row_idx, (_, row) in enumerate(df.iterrows()):
                    row_cells = [
                        TableCell(text=str(v) if v is not None else "", row=row_idx, col=col_idx)
                        for col_idx, v in enumerate(row)
                    ]
                    if row_cells:
                        rows.append(row_cells)
            else:
                # 回退：尝试 cells 属性
                table_cells = getattr(table, "cells", [])
                if table_cells:
                    row_map: dict[int, list[TableCell]] = {}
                    for cell in table_cells:
                        r = getattr(cell, "row", 0)
                        c = getattr(cell, "col", 0)
                        t = getattr(cell, "text", "")
                        row_map.setdefault(r, []).append(
                            TableCell(text=str(t).strip(), row=r, col=c)
                        )
                    rows = [cells for _, cells in sorted(row_map.items())]

            if rows:
                return PageElement(type="table", tables=rows)
        except Exception as e:
            logger.debug("Docling 表格转换失败: %s", e)
        return None
