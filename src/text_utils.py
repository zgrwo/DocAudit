"""共享文本处理工具 — CJK 字符检测、CJK-Latin 混排正则等"""

import re

# ── CJK 字符检测 ────────────────────────────────────────────

def is_cjk_char(c: str) -> bool:
    """判断单个字符是否为 CJK 汉字 (含扩展 A 和兼容区)。

    覆盖范围:
    - CJK Extension A: U+3400–U+4DBF (6,592 字符)
    - CJK Unified Ideographs: U+4E00–U+9FFF (20,992 字符)
    - CJK Compatibility Ideographs: U+F900–U+FAFF (512 字符)

    注意: CJK Extension B+ (U+20000+) 需 surrogate pair 支持，暂未覆盖。
    """
    if not c:
        return False
    if len(c) != 1:
        raise ValueError(f"is_cjk_char 需要单个字符，收到 {len(c)} 个字符: {c!r}")
    cp = ord(c)
    return (
        0x3400 <= cp <= 0x4DBF    # CJK Extension A
        or 0x4E00 <= cp <= 0x9FFF  # CJK Unified Ideographs
        or 0xF900 <= cp <= 0xFAFF  # CJK Compatibility Ideographs
    )


# ── CJK 字符类 (正则用) ─────────────────────────────────────
# 覆盖范围与 is_cjk_char() 保持一致: CJK Ext A + Unified + Compat
_CJK_CHAR_CLASS = r"[一-鿿㐀-䶿豈-﫿]"

# 预编译的 CJK 字符检测正则 (供 language.py, languagetool.py 共用)
CJK_RE = re.compile(_CJK_CHAR_CLASS)


# ── CJK-Latin 混排格式预编译正则 ────────────────────────────
# 供 language.py 的中英混排检查 和 autofix.py 的空格修复共用

CJK_LATIN_BOUNDARY = re.compile(
    rf"({_CJK_CHAR_CLASS})([a-zA-Z0-9])"
)
"""CJK 字符后紧接拉丁/数字 — 应加空格"""

LATIN_CJK_BOUNDARY = re.compile(
    rf"([a-zA-Z0-9])({_CJK_CHAR_CLASS})"
)
"""拉丁/数字后紧接 CJK 字符 — 应加空格"""

LATIN_CHINESE_PUNCT = re.compile(
    rf"([a-zA-Z0-9])([，。；：！？])"
)
"""英文/数字后使用中文标点符号 — 应改为英文标点"""

# ── 英文词提取与分类 ────────────────────────────────────────
# 供 languagetool.py 拼写检查 和 language.py 语言分段共用

ENGLISH_WORD_RE = re.compile(r"\b[a-zA-Z]+\b")
"""提取所有纯字母英文词 (供外部调用者使用，当前流水线内部使用 ENGLISH_WORD_MIN4_RE)"""

ENGLISH_WORD_MIN4_RE = re.compile(r"\b[a-zA-Z]{4,}\b")
"""提取 4+ 字符英文词（过滤短缩写/介词）"""


def is_technical_token(word: str) -> bool:
    """判断英文词是否为技术缩写/驼峰词，拼写检查时应跳过。
    规则：全大写 (TSV, CMOS) 或驼峰 (FinFET, GaN)。
    """
    if not word or len(word) < 2:
        return False
    if word.isupper():
        return True
    # 驼峰: 至少 2 个大写字母 + 至少 1 个小写字母 (PascalCase / camelCase)
    # 覆盖: FinFET, GaN, iOS, iPadOS, macOS 等
    # 排除: 句首大写普通词 (This, When, From — 仅 1 个大写)
    upper_count = sum(1 for c in word if c.isupper())
    has_lower = any(c.islower() for c in word)
    if upper_count >= 2 and has_lower:
        return True
    return False
