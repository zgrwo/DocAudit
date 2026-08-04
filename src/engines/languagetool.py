"""LanguageTool 集成 — 三层自动降级

Tier 1: 已有 Docker / 外部服务 (localhost:8010)
Tier 2: Java 子进程 — 自动启动 standalone server (需 Java)
Tier 3: 纯 Python 拼写检查 — pyspellchecker + 中文语法正则 (零依赖)
"""

import atexit
import logging
import re
import subprocess
import time
import shutil
import weakref
from pathlib import Path
from typing import Any

from src.text_utils import ENGLISH_WORD_MIN4_RE, is_technical_token

logger = logging.getLogger(__name__)

# LanguageTool standalone server 版本与 JAR 文件名
LT_VERSION = "6.5"
LT_SERVER_JAR = "languagetool-server.jar"

# 模块级预编译中文语法模式 (避免每次调用重复编译)
_ZH_PATTERNS = [
    # 重复用词
    (re.compile(r"的的"), "重复用词: '的的'"),
    (re.compile(r"了了"), "重复用词: '了了'"),
    (re.compile(r"是是"), "重复用词: '是是'"),
    (re.compile(r"在在"), "重复用词: '在在'"),
    # 的/地/得 常见误用
    (re.compile(r"仔细的"), "应为 '仔细地' (副词用'地')"),
    (re.compile(r"认真的"), "根据语境可能应为 '认真地' (副词用'地')"),
    (re.compile(r"很快的"), "应为 '很快地' (副词用'地')"),
    (re.compile(r"做的好"), "应为 '做得好' (补语用'得')"),
    (re.compile(r"说的对"), "应为 '说得对' (补语用'得')"),
    # 在/再 区分 (限制距离≤15字符，避免跨句误报)
    (re.compile(r"再.{0,15}?在"), "注意区分 '再'(again/further) 和 '在'(at/in)"),
    (re.compile(r"在.{0,15}?再"), "注意区分 '在'(at/in) 和 '再'(again/further)"),
    # 做/作 区分
    (re.compile(r"做功"), "半导体语境中通常用 '做功'；但如果指'作为功'应写 '作功'"),
    # 语义重复 (限制距离≤20字符，避免跨句误报)
    (re.compile(r"约[^左右]{0,20}左右"), "语义重复: '约' 和 '左右' 不能同时使用"),
    (re.compile(r"大约[^左右]{0,20}左右"), "语义重复: '大约' 和 '左右' 不能同时使用"),
    (re.compile(r"大概[^左右]{0,20}左右"), "语义重复: '大概' 和 '左右' 不能同时使用"),
    (re.compile(r"超过[^以上]{0,20}以上"), "语义重复: '超过' 和 '以上' 不能同时使用"),
    (re.compile(r"至少[^以上]{0,20}以上"), "语义重复: '至少' 和 '以上' 不能同时使用"),
    # 欧化句式 (限制距离≤20字符，避免跨句误报)
    (re.compile(r"通过.{0,20}?了"), "欧化句式: 避免 '通过...了' 结构，改用直接陈述"),
    (re.compile(r"被.{0,20}?所"), "欧化句式: 避免 '被...所...' 结构"),
    # 标点
    (re.compile(r"，，+"), "重复逗号"),
    (re.compile(r"。。+"), "重复句号"),
    (re.compile(r"、、+"), "重复顿号"),
    # 技术写作常见错别字 (限制距离≤10字符)
    (re.compile(r"良率.{0,10}?底(?![部层])"), "可能为'良率低'之误 ('底' vs '低')"),
    (re.compile(r"异质.{0,10}?结合"), "半导体语境中应为 '异质集成' 而非 '异质结合'"),
]

class LanguageToolClient:
    """LanguageTool 客户端，自动选择最优后端。"""

    DEFAULT_URL = "http://localhost:8010/v2"
    DEFAULT_PORT = 8011  # Java subprocess uses different port to avoid conflict

    # 类级别弱引用集合，避免多实例重复注册 atexit
    _instances: weakref.WeakSet = weakref.WeakSet()
    _atexit_registered: bool = False

    @classmethod
    def _cleanup_all(cls):
        """atexit 回调：清理所有存活实例的 Java 子进程"""
        for inst in list(cls._instances):
            inst._cleanup_java()

    def __init__(self, base_url: str = DEFAULT_URL, timeout: int = 30,
                 auto_start: bool = True):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.auto_start = auto_start
        self._available = None
        self._backend = None  # "docker" | "java" | "python"
        self._java_process = None
        self._spell_checker = None
        # 类级别统一注册 atexit，避免多实例重复注册
        LanguageToolClient._instances.add(self)
        if not LanguageToolClient._atexit_registered:
            atexit.register(LanguageToolClient._cleanup_all)
            LanguageToolClient._atexit_registered = True

    # ── Availability ─────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        """检查是否有可用的语言检查后端"""
        if self._available is not None:
            return self._available

        # Tier 1: try existing service
        if self._try_connect(self.base_url):
            self._available = True
            self._backend = "docker"
            logger.info("LanguageTool: using existing service at %s", self.base_url)
            return True

        # Tier 2: try Java subprocess
        if self.auto_start and self._try_java():
            self._available = True
            self._backend = "java"
            return True

        # Tier 3: pure Python fallback
        if self._init_python_fallback():
            self._available = True
            self._backend = "python"
            logger.info("LanguageTool: using pure-Python fallback (basic)")

            return True

        self._available = False
        return False

    def _try_connect(self, url: str) -> bool:
        try:
            import requests
            resp = requests.get(f"{url}/languages", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    # ── Tier 2: Java subprocess ──────────────────────────────

    def _try_java(self) -> bool:
        """尝试在 Java 子进程中启动 LanguageTool"""
        if not shutil.which("java"):
            logger.info("Java not found, skipping LanguageTool subprocess")
            return False

        jar_path = self._find_jar()
        if not jar_path:
            return False

        try:
            port = self.DEFAULT_PORT
            self._java_process = subprocess.Popen(
                ["java", "-Xmx1g", "-jar", str(jar_path), "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            # Wait for server to start (up to 30s)
            java_url = f"http://localhost:{port}/v2"
            for _ in range(30):
                time.sleep(1)
                if self._try_connect(java_url):
                    self.base_url = java_url
                    logger.info("LanguageTool: Java server started on port %d", port)
                    return True
            # 超时: 先终止子进程，再读 stderr (避免对活进程的阻塞 read())
            try:
                self._java_process.terminate()
                self._java_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    self._java_process.kill()
                    self._java_process.wait(timeout=5)
                except Exception:
                    pass
            except Exception:
                try:
                    self._java_process.kill()
                except Exception:
                    pass
            # 进程已终止，stderr 可安全读取 (EOF 已到达)
            stderr_output = ""
            try:
                if self._java_process.stderr:
                    stderr_output = self._java_process.stderr.read().decode(errors="replace")
            except Exception:
                pass
            logger.warning("LanguageTool Java server timed out (port %d). stderr: %s",
                           port, stderr_output[:500] if stderr_output else "(empty)")
            self._java_process = None
            return False
        except Exception as e:
            logger.warning("Failed to start LanguageTool Java: %s", e)
            return False

    def _find_jar(self) -> Path | None:
        """查找本地 LanguageTool standalone jar（不执行下载）"""
        import sys
        cache_dir = Path(sys.prefix) / "share" / "languagetool"
        cache_dir.mkdir(parents=True, exist_ok=True)

        jar_path = cache_dir / f"LanguageTool-{LT_VERSION}" / "languagetool-server.jar"
        if jar_path.exists():
            return jar_path

        # Also check LT_SERVER_JAR in root of cache_dir
        alt = cache_dir / LT_SERVER_JAR
        if alt.exists():
            return alt

        logger.info(
            "LanguageTool standalone JAR not found. "
            "Download from https://languagetool.org/download/ "
            "and place at %s", jar_path
        )
        return None

    # ── Tier 3: Pure Python fallback ─────────────────────────

    def _init_python_fallback(self) -> bool:
        """初始化纯 Python 拼写检查"""
        try:
            from spellchecker import SpellChecker
            self._spell_checker = SpellChecker()
            return True
        except ImportError:
            return False

    # ── Check ────────────────────────────────────────────────

    def check(
        self, text: str, language: str = "auto",
        mother_tongue: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.is_available:
            return []

        if self._backend == "python":
            return self._check_python(text, language)
        else:
            return self._check_http(text, language, mother_tongue)

    def _check_http(self, text: str, language: str,
                    mother_tongue: str | None = None) -> list[dict[str, Any]]:
        """通过 HTTP API 检查 (Docker or Java)"""
        MAX_LENGTH = 15000
        results: list[dict[str, Any]] = []

        for chunk_start in range(0, len(text), MAX_LENGTH):
            chunk = text[chunk_start:chunk_start + MAX_LENGTH]
            params = {"text": chunk, "language": language}
            if mother_tongue:
                params["motherTongue"] = mother_tongue
            try:
                import requests
                resp = requests.post(f"{self.base_url}/check", data=params,
                                     timeout=self.timeout)
                if resp.status_code == 200:
                    matches = resp.json().get("matches", [])
                    for m in matches:
                        m["offset"] += chunk_start
                    results.extend(matches)
            except Exception as e:
                logger.warning("LanguageTool request failed: %s", e)
                break
            if chunk_start + MAX_LENGTH < len(text):
                time.sleep(0.1)

        return results

    def _check_python(self, text: str, language: str) -> list[dict[str, Any]]:
        """纯 Python 基础检查：中文语法正则 + 智能英文拼写 (仅检查清晰英文词)。

        英文拼写仅检查满足以下条件的词（大幅减少 pyspellchecker 负担）：
        - 纯字母 (a-zA-Z)，至少 4 字符
        - 非全大写缩写 (如 TSV) 且非驼峰 (如 FinFET)
        - 每页最多 100 个独立词
        需要完整拼写+语法检查请启动 Docker/Java LanguageTool 后端。
        """
        results: list[dict[str, Any]] = []

        # ── 智能英文拼写检查 ──────────────────────────────────
        if self._spell_checker and language in ("en-US", "en", "auto"):
            # 使用 text_utils 共享的正则和分类函数
            raw_words = ENGLISH_WORD_MIN4_RE.findall(text)
            # 过滤：排除技术缩写/驼峰词，小写去重
            candidates: list[str] = []
            seen: set[str] = set()
            for w in raw_words:
                wl = w.lower()
                if wl in seen:
                    continue
                if is_technical_token(w):
                    continue
                seen.add(wl)
                candidates.append(w)
                if len(candidates) >= 100:  # 每页上限，保证性能
                    break

            if candidates:
                # 统一转小写进行拼写检查
                lower_candidates = [w.lower() for w in candidates]
                misspelled = self._spell_checker.unknown(lower_candidates)
                for word_lower in misspelled:
                    if len(word_lower) <= 3 or word_lower.isdigit():
                        continue
                    candidates_list = self._spell_checker.candidates(word_lower)
                    suggestion = ", ".join(list(candidates_list)[:3]) if candidates_list else None
                    # 使用大小写不敏感正则查找所有出现位置
                    pattern = re.compile(re.escape(word_lower), re.IGNORECASE)
                    for m in pattern.finditer(text):
                        results.append({
                            "message": f"可能的拼写错误: '{word_lower}'",
                            "offset": m.start(),
                            "length": len(m.group()),
                            "rule": {
                                "id": "PY-SPELL",
                                "category": {"id": "MISSPELLING"},
                                "issueType": "misspelling",
                            },
                            "replacements": [{"value": suggestion}] if suggestion else [],
                            "context": {
                                "text": text[max(0, m.start() - 20):m.end() + 20],
                            },
                        })

        # ── 中文基础语法正则 ──────────────────────────────────
        if language in ("zh-CN", "auto"):
            results.extend(self._check_chinese_patterns(text))

        return results

    def _check_chinese_patterns(self, text: str) -> list[dict[str, Any]]:
        """中文基础语法正则检查"""
        results: list[dict[str, Any]] = []
        for pattern, msg in _ZH_PATTERNS:
            for m in pattern.finditer(text):
                results.append({
                    "message": msg,
                    "offset": m.start(),
                    "length": m.end() - m.start(),
                    "rule": {
                        "id": "PY-ZH-GRAMMAR",
                        "category": {"id": "GRAMMAR"},
                        "issueType": "grammar",
                    },
                    "replacements": [],
                    "context": {"text": text[max(0, m.start() - 10):m.end() + 10]},
                })
        return results

    def check_chinese_only(self, text: str) -> list[dict[str, Any]]:
        """便捷方法：仅中文检查。当前流水线使用 language="auto" 自动检测，此方法供外部调用。"""
        return self.check(text, language="zh-CN")

    def check_english_only(self, text: str) -> list[dict[str, Any]]:
        """便捷方法：仅英文检查。当前流水线使用 language="auto" 自动检测，此方法供外部调用。"""
        return self.check(text, language="en-US")

    # ── Reset ────────────────────────────────────────────────

    def reset(self):
        """重置所有缓存状态，强制重新探测后端。

        适用于 LanguageTool 服务在审计运行中途启动的场景。
        """
        # 先清理 Java 子进程，避免下次探测时端口冲突或僵尸进程
        if self._java_process is not None:
            self._cleanup_java()
        self._available = None
        self._backend = None
        self._java_process = None

    # ── Cleanup ──────────────────────────────────────────────

    def _cleanup_java(self):
        """安全清理 Java 子进程 (供 atexit 调用)。"""
        try:
            if self._java_process and self._java_process.poll() is None:
                self._java_process.terminate()
                try:
                    self._java_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._java_process.kill()
                self._java_process = None
        except Exception:
            pass  # 解释器关闭期间模块可能已被清理

    def shutdown(self):
        """终止 Java 子进程 (用户主动调用)。"""
        had_process = self._java_process is not None
        self._cleanup_java()
        if had_process:
            logger.info("LanguageTool Java server stopped")

    def __del__(self):
        """清理 Java 子进程。解释器关闭期间不执行（atexit 已处理）。"""
        # Python 3.4+ 解释器关闭时模块可能已被清理，
        # 此时 subprocess 不可用；atexit 注册的 _cleanup_java 已处理正常退出路径。
        try:
            if self._java_process is not None:
                self._cleanup_java()
        except Exception:
            pass  # 解释器关闭期间不抛异常
