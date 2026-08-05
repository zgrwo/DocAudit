"""转换器抽象基类"""

from abc import ABC, abstractmethod
from pathlib import Path

from src.models.document import Document


class BaseConverter(ABC):
    """所有格式转换器的抽象基类"""

    @abstractmethod
    def can_handle(self, source_path: str | Path) -> bool:
        """判断是否能处理该文件"""
        ...

    @abstractmethod
    def convert(self, source_path: str | Path) -> Document:
        """将文件转换为统一 Document 模型"""
        ...
