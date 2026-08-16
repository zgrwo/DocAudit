"""tools/check_bare_handlers.py 的测试。

规则（与 tools/check_bare_handlers.py 保持一致）:
- 裸 `except:` / `except BaseException` → 违规
- `except Exception`（含 `as e`）体为空或只有 `pass` → 违规，除非行尾有 `# bare-handler-ok`
- 具体异常类型（ValueError / yaml.YAMLError / 元组）→ 放行
- 处理器体内有 return/raise/调用等语句 → 放行
"""

import subprocess
import sys
import textwrap
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "check_bare_handlers.py"


def run_tool(paths: list[Path]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *[str(p) for p in paths]],
        capture_output=True,
        text=True,
    )


def write_sample(tmp_path: Path, body: str) -> Path:
    src = tmp_path / "sample.py"
    src.write_text(textwrap.dedent(body), encoding="utf-8")
    return src


def test_flags_bare_except(tmp_path):
    src = write_sample(
        tmp_path,
        """
        def f():
            try:
                return 1
            except:
                pass
        """,
    )
    r = run_tool([src])
    assert r.returncode != 0
    assert "except:" in r.stdout


def test_flags_base_exception(tmp_path):
    src = write_sample(
        tmp_path,
        """
        def f():
            try:
                return 1
            except BaseException:
                pass
        """,
    )
    r = run_tool([src])
    assert r.returncode != 0
    assert "BaseException" in r.stdout


def test_flags_silent_except_exception_pass(tmp_path):
    src = write_sample(
        tmp_path,
        """
        def f():
            try:
                return 1
            except Exception:
                pass
        """,
    )
    r = run_tool([src])
    assert r.returncode != 0
    assert "except Exception" in r.stdout


def test_flags_silent_except_exception_as_e(tmp_path):
    src = write_sample(
        tmp_path,
        """
        def f():
            try:
                return 1
            except Exception as e:
                pass
        """,
    )
    r = run_tool([src])
    assert r.returncode != 0


def test_allows_specific_exception_pass(tmp_path):
    src = write_sample(
        tmp_path,
        """
        def f():
            try:
                return 1
            except (AttributeError, ValueError):
                pass
        """,
    )
    r = run_tool([src])
    assert r.returncode == 0, r.stdout


def test_allows_noqa_comment(tmp_path):
    src = write_sample(
        tmp_path,
        """
        def f():
            try:
                return 1
            except Exception:
                pass  # bare-handler-ok — 降级路径，任何异常均可安全忽略
        """,
    )
    r = run_tool([src])
    assert r.returncode == 0, r.stdout


def test_allows_handler_with_return(tmp_path):
    src = write_sample(
        tmp_path,
        """
        def f():
            try:
                return 1
            except Exception:
                return False
        """,
    )
    r = run_tool([src])
    assert r.returncode == 0, r.stdout


def test_clean_file_passes(tmp_path):
    src = write_sample(
        tmp_path,
        """
        def f(x):
            return x or 0
        """,
    )
    r = run_tool([src])
    assert r.returncode == 0, r.stdout


def test_skips_docstring_teaching_text(tmp_path):
    """docstring 里的 'except:' 教学文字不得误报（AST 感知，天然跳过）。"""
    src = write_sample(
        tmp_path,
        '''
        def f():
            """示例: 禁止写 `except:` 裸捕获；也应避免 `except Exception: pass`。"""
            return 1
        ''',
    )
    r = run_tool([src])
    assert r.returncode == 0, r.stdout


def test_repo_clean():
    """全仓库无违规（含新增 noqa 注释的既有降级路径）。"""
    r = run_tool([Path(__file__).resolve().parent.parent])
    assert r.returncode == 0, r.stdout
