"""词汇表检查引擎 — accept.txt / reject.txt

Inspired by Vale's Vocab system:
- accept.txt: 项目认可词汇白名单 (LanguageTool/术语引擎不应标记)
- reject.txt: 项目禁用词汇黑名单 (始终标记)

reject.txt 支持两种格式:
1. 纯单词/短语: 使用单词边界匹配 (如 "kind of")
2. 正则表达式: 直接编译为 regex (如 "flip-chip(?!.*bump)")
   - 自动检测: 如果条目包含正则特殊字符且可成功编译，则作为正则处理
   - 否则回退到字面字符串的边界匹配
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# 正则特殊字符集合，用于判断条目是否为 regex
_REGEX_SPECIAL = set(r".^$*+?{}[]\|()")


def _has_regex_chars(s: str) -> bool:
    """检查字符串是否包含正则特殊字符"""
    return bool(_REGEX_SPECIAL & set(s))


def _read_lines(path: Path) -> list[str]:
    """读取词汇表文件行，带编码回退 (UTF-8 → GBK → replace)。

    中文 Windows 用户可能以系统默认 GBK 保存词汇表；裸 read_text(utf-8)
    会抛 UnicodeDecodeError 打穿 build_auditors (2026-08 审查实证)。
    """
    for encoding in ("utf-8", "gbk"):
        try:
            return path.read_text(encoding=encoding).splitlines()
        except UnicodeDecodeError:
            continue
    logger.warning("词汇表文件编码无法识别 (非 UTF-8/GBK)，按 UTF-8 容错读取: %s", path.name)
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


class Vocabulary:
    """项目级术语词汇表。

    Usage:
        vocab = Vocabulary("vocab")
        vocab.is_accepted("FinFET")     → True
        vocab.should_reject("kind of")  → [rejection reason, ...]
    """

    def __init__(self, vocab_dir: str | Path | None = None):
        self.accepted: set[str] = set()
        self.rejected: dict[str, str] = {}  # word → reason
        self._rejected_patterns: list[tuple[str, re.Pattern, str]] = []  # (word, pattern, reason)
        if vocab_dir:
            self.load(vocab_dir)

    def load(self, vocab_dir: str | Path):
        """加载词汇表目录"""
        directory = Path(vocab_dir)

        accept_path = directory / "accept.txt"
        if accept_path.exists():
            loaded = 0
            for line in _read_lines(accept_path):
                line = line.strip()
                if line and not line.startswith("#"):
                    self.accepted.add(line.lower())
                    loaded += 1
            logger.info("加载白名单: %d 个术语", loaded)

        reject_path = directory / "reject.txt"
        if reject_path.exists():
            loaded = 0
            for line in _read_lines(reject_path):
                line = line.strip()
                if line and not line.startswith("#"):
                    # 格式: "word" 或 "word # reason" (# 前空格可选)
                    m = re.match(r"^(.+?)\s*#\s*(.+)$", line)
                    if m:
                        word = m.group(1).strip()
                        reason = m.group(2).strip()
                    else:
                        word = line.strip()
                        reason = "词汇表中的禁用术语"
                    self.rejected[word.lower()] = reason

                    # 预编译匹配模式: 自动检测正则 vs 字面字符串
                    try:
                        if _has_regex_chars(word):
                            pattern = re.compile(word, re.IGNORECASE)
                        elif any("\u4e00" <= c <= "\u9fff" for c in word):
                            # CJK 词: \b 对中文字符无效，直接匹配
                            pattern = re.compile(re.escape(word), re.IGNORECASE)
                        else:
                            pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
                        self._rejected_patterns.append((word, pattern, reason))
                    except re.error as e:
                        logger.debug("reject 条目正则编译失败，回退到字面匹配: %s — %s", word, e)
                        pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
                        self._rejected_patterns.append((word, pattern, reason))
                    loaded += 1
            logger.info(
                "加载黑名单: %d 个禁用术语 (预编译 %d 个模式)", loaded, len(self._rejected_patterns)
            )

    def is_accepted(self, word: str) -> bool:
        """检查术语是否在白名单中（应被接受）"""
        return word.lower() in self.accepted

    def should_reject(self, text: str) -> list[tuple[str, str]]:
        """检查文本是否包含禁用术语。

        使用预编译的正则模式，支持:
        - 单词边界匹配 (纯单词条目)
        - 完整正则表达式 (包含特殊字符的条目)

        Returns: [(matched_word, reason), ...]
        """
        hits: list[tuple[str, str]] = []
        # 模式已编译为 IGNORECASE，直接在原文上匹配，无需预先 lower()
        for word, pattern, reason in self._rejected_patterns:
            if pattern.search(text):
                hits.append((word, reason))
        return hits

    def filter_accepted(self, words: set[str]) -> set[str]:
        """从词集合中过滤出白名单中的词（返回被接受的词）"""
        return {w for w in words if self.is_accepted(w)}
