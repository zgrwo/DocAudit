"""审查器抽象基类"""

from abc import ABC, abstractmethod

from src.models.document import Document
from src.models.finding import AuditFinding


class BaseAuditor(ABC):
    """所有审查器的抽象基类"""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    @abstractmethod
    def audit(self, doc: Document) -> list[AuditFinding]:
        """对文档执行审查，返回发现列表"""
        ...
