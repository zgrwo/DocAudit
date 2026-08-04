"""Engine 层 — 可复用后端服务。

注意: pipeline.py 依赖 Auditor 层，不可在此处导入 (会触发循环引用)。
使用方应直接从子模块导入: from src.engines.pipeline import build_auditors
"""

from src.engines.rule_parser import parse_rules_md, extract_auditor_config, AuditRule
from src.engines.terminology import TerminologyChecker
from src.engines.vocabulary import Vocabulary
from src.engines.languagetool import LanguageToolClient
from src.engines.autofix import AutoFixer

__all__ = [
    "parse_rules_md",
    "extract_auditor_config",
    "AuditRule",
    "TerminologyChecker",
    "Vocabulary",
    "LanguageToolClient",
    "AutoFixer",
]