"""共享文本处理工具 — CJK 字符检测、CJK-Latin 混排正则、代码/URL 掩码等"""

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
        0x3400 <= cp <= 0x4DBF  # CJK Extension A
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

CJK_LATIN_BOUNDARY = re.compile(rf"({_CJK_CHAR_CLASS})([a-zA-Z0-9])")
"""CJK 字符后紧接拉丁/数字 — 应加空格"""

LATIN_CJK_BOUNDARY = re.compile(rf"([a-zA-Z0-9])({_CJK_CHAR_CLASS})")
"""拉丁/数字后紧接 CJK 字符 — 应加空格"""

LATIN_CHINESE_PUNCT = re.compile(r"([a-zA-Z0-9])([，。；：！？])")
"""英文/数字后使用中文标点符号 — 应改为英文标点"""

# ── 英文词提取与分类 ────────────────────────────────────────
# 供 languagetool.py 拼写检查 和 language.py 语言分段共用

ENGLISH_WORD_RE = re.compile(r"\b[a-zA-Z]+\b")
"""提取所有纯字母英文词 (供外部调用者使用，当前流水线内部使用 ENGLISH_WORD_MIN4_RE)"""

ENGLISH_WORD_MIN4_RE = re.compile(r"\b[a-zA-Z]{4,}\b")
"""提取 4+ 字符英文词（过滤短缩写/介词）"""

# ── 项目符号识别 (格式/语言审计器共用 SSOT) ─────────────────

SYMBOL_BULLET_RE = re.compile(r"^\s*[•◦▪▸◆\-*]\s")
"""符号类项目符号: • ◦ ▪ ▸ ◆ - *"""

NUMBERED_BULLET_RE = re.compile(r"^\s*(?:\d+[\.\)]\s|\(\d+\)\s|[①②③④⑤⑥⑦⑧⑨⑩]\s)")
"""数字类项目符号: 1. 2) (1) ①"""

LETTERED_BULLET_RE = re.compile(r"^\s*(?:[a-zA-Z][\.\)]\s|\([a-zA-Z]\)\s)")
"""字母类项目符号: a) A. (a)"""


# ── 代码 / URL / Markdown 结构语法掩码 (语言类检查共用) ──────
# 这些区间内的文本不是自然语言：其中的 `--flag`、`# 注释`、英文标识符、
# 分隔线 `---` 不应触发混排/标点/拼写检查（2026-11 审查：README 自审时
# `--fail-on` 被报 PUNCT-007、`---` 分隔线被报破折号、代码标识符被报 PY-SPELL）。
# 掩码等长替换为空格，字符位置不变。

MASK_FENCED_CODE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
MASK_CODE_RE = re.compile(r"`[^`]*`")
MASK_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
MASK_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
# HTML 注释 (Markdown 常用 <!-- last_updated: … -->)
MASK_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# Markdown 分隔线: 整行仅由 3+ 个 -/*/_ 组成 (可带前导空白)
MASK_HR_RE = re.compile(r"(?m)^[ \t]{0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
# 顺序即掩码顺序: 先整块代码/注释, 再分隔线, 最后 URL/邮箱/行内代码
MASK_REGEXES = (
    MASK_FENCED_CODE_RE,
    MASK_HTML_COMMENT_RE,
    MASK_HR_RE,
    MASK_URL_RE,
    MASK_EMAIL_RE,
    MASK_CODE_RE,
)


def mask_prose_noise(text: str) -> str:
    """把代码/URL/注释/分隔线替换为等长空格，供只应检查自然语言的规则使用。"""
    masked = text
    for regex in MASK_REGEXES:
        masked = regex.sub(lambda m: " " * len(m.group(0)), masked)
    return masked


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
