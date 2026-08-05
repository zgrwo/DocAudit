"""PDF 转换器 — 使用 Docling 解析，保留标题层级和表格结构"""

import logging
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
                "pip install doc-audit[pdf] 或 pip install docling"
            )

        logger.info("使用 Docling 解析 PDF: %s", source_path.name)

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
            for page_idx, page_key in enumerate(sorted(docling_doc.pages.keys())):
                docling_page = docling_doc.pages[page_key]
                elements: list[PageElement] = []

                # 提取页面上的文本项 (适配 Docling 不同版本 API)
                try:
                    uses_cells = False
                    if hasattr(docling_page, 'cells'):
                        uses_cells = True
                        for cell in docling_page.cells:
                            elem = self._convert_cell(cell)
                            if elem is not None:
                                elements.append(elem)
                        # cells API 已包含表格内容，不重复提取
                    elif hasattr(docling_page, 'items'):
                        for item in docling_page.items:
                            elem = self._convert_item(item)
                            if elem is not None:
                                elements.append(elem)
                    else:
                        # 未知 Docling API: 回退到文本导出，避免静默丢页
                        logger.debug("Docling page %d 结构未知，回退到文本导出", page_idx)
                        try:
                            page_text = docling_page.export_to_markdown() if hasattr(docling_page, 'export_to_markdown') else ""
                        except Exception:
                            page_text = ""
                        if page_text.strip():
                            elements.append(PageElement(
                                type="text_frame",
                                paragraphs=[Paragraph(text=page_text.strip(), runs=[])],
                            ))
                    # 非 cells API 路径: 尝试提取结构化表格 (统一处理，避免 items/fallback 分支重复)
                    if not uses_cells and hasattr(docling_page, 'tables'):
                        for table in docling_page.tables:
                            elem = self._convert_docling_table(table)
                            if elem is not None:
                                elements.append(elem)
                except Exception as e:
                    logger.warning("Docling 页面 %d 解析失败: %s，跳过该页", page_idx, e)

                pages.append(Page(
                    index=page_idx,
                    elements=elements,
                    slide_number=page_idx + 1,
                ))
        else:
            # 回退：使用 Markdown 导出并按页拆分
            md_text = docling_doc.export_to_markdown()
            for page_idx, page_text in enumerate(md_text.split("\n\n---\n\n")):
                if page_text.strip():
                    pages.append(Page(
                        index=page_idx,
                        elements=[PageElement(
                            type="text_frame",
                            paragraphs=[Paragraph(text=page_text.strip(), runs=[])],
                        )],
                        slide_number=page_idx + 1,
                    ))

        if not pages:
            # 最终回退
            pages.append(Page(
                index=0,
                elements=[PageElement(
                    type="text_frame",
                    paragraphs=[Paragraph(text=docling_doc.export_to_markdown(), runs=[])],
                )],
                slide_number=1,
            ))

        return Document(
            source_path=str(source_path),
            format="pdf",
            metadata=metadata,
            pages=pages,
        )

    def _convert_cell(self, cell) -> PageElement | None:
        """Docling cell → PageElement"""
        cell_text = getattr(cell, 'text', '')
        if not cell_text or not str(cell_text).strip():
            return None

        # 判断是否为表格
        if hasattr(cell, 'row_span') or hasattr(cell, 'col_span'):
            # 如果是表格的一部分，标记但暂不处理复杂的拆分
            return PageElement(
                type="text_frame",
                paragraphs=[Paragraph(text=str(cell_text).strip(), runs=[])],
            )

        return PageElement(
            type="text_frame",
            paragraphs=[Paragraph(text=str(cell_text).strip(), runs=[])],
        )

    def _convert_item(self, item) -> PageElement | None:
        """Docling item → PageElement"""
        item_text = getattr(item, 'text', str(item))
        if not item_text or not str(item_text).strip():
            return None

        # 尝试获取标题层级
        level = getattr(item, 'heading_level', None)

        return PageElement(
            type="text_frame",
            paragraphs=[Paragraph(
                text=str(item_text).strip(),
                runs=[],
                level=level,
            )],
            is_title=(level == 1),
        )

    def _convert_docling_table(self, table) -> PageElement | None:
        """Docling table → PageElement (表格结构)"""
        try:
            rows: list[list[TableCell]] = []
            if hasattr(table, 'export_to_dataframe'):
                try:
                    import pandas  # noqa: F401 — availability check
                except ImportError:
                    logger.warning(
                        "PDF 表格转换需要 pandas。请运行: pip install doc-audit[pdf]"
                    )
                    return None
                df = table.export_to_dataframe()
                if df is None:
                    logger.debug("Docling table.export_to_dataframe() 返回 None，跳过")
                    return None
                for row_idx, (_, row) in enumerate(df.iterrows()):
                    row_cells = [
                        TableCell(text=str(v) if v is not None else "",
                                  row=row_idx, col=col_idx)
                        for col_idx, v in enumerate(row)
                    ]
                    if row_cells:
                        rows.append(row_cells)
            else:
                # 回退：尝试 cells 属性
                table_cells = getattr(table, 'cells', [])
                if table_cells:
                    row_map: dict[int, list[TableCell]] = {}
                    for cell in table_cells:
                        r = getattr(cell, 'row', 0)
                        c = getattr(cell, 'col', 0)
                        t = getattr(cell, 'text', '')
                        row_map.setdefault(r, []).append(
                            TableCell(text=str(t).strip(), row=r, col=c)
                        )
                    rows = [cells for _, cells in sorted(row_map.items())]

            if rows:
                return PageElement(type="table", tables=rows)
        except Exception as e:
            logger.debug("Docling 表格转换失败: %s", e)
        return None
