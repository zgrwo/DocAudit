"""审查器抽象基类 + Auditor 层共用判定（封面版式识别）"""

from abc import ABC, abstractmethod

from src.models.document import Document
from src.models.finding import AuditFinding

# 封面/标题版式的内置默认豁免名（对齐 rules.md CON-004「豁免版式」声明）。
# StructureAuditor（CON-004 页豁免）与 FormatAuditor（版式复用提示）共用，
# 避免两处各自维护版式词表导致判定漂移。
DEFAULT_COVER_LAYOUTS = (
    "标题幻灯片",
    "Title Slide",
    "Title",
    "Titelfolie",
    "封面",
    "タイトル",
    "Cover",
)

# 允许做前缀/包含匹配的封面专用短语；通用词（Title/标题）只做精确匹配，
# 否则 "Title and Content" 等内容页会被一起豁免。
_COVER_PHRASES = frozenset(
    {
        "title slide",
        "标题幻灯片",
        "封面",
        "封面页",
        "titelfolie",
        "タイトル",
        "cover",
        "cover page",
    }
)


def is_cover_layout(layout_name: str | None, exempt_layouts) -> bool:
    """判断版式是否为标题/封面页（自 ``StructureAuditor._is_exempt_layout`` 提取）。

    2026-10-28 修复：旧实现用子串匹配，``exempt_layouts`` 中的通用词 "Title"
    会把 "Title and Content" 等所有内容页一起豁免，导致 CON-004 在英文模板中
    完全失效。现改为：精确匹配（大小写不敏感）；仅对明确的封面短语允许前缀/
    包含匹配。
    """
    if not layout_name:
        return False
    layout = str(layout_name).strip().casefold()
    if not layout:
        return False

    for pattern in exempt_layouts or ():
        candidate = str(pattern).strip().casefold()
        if not candidate:
            continue
        if layout == candidate:
            return True
        # 只对明确的封面短语允许前缀/包含，避免 "Title" 误伤内容页。
        if candidate in _COVER_PHRASES and (layout.startswith(candidate) or candidate in layout):
            return True
    return False


class BaseAuditor(ABC):
    """所有审查器的抽象基类"""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    @abstractmethod
    def audit(self, doc: Document) -> list[AuditFinding]:
        """对文档执行审查，返回发现列表"""
        ...
