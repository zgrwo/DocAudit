"""tools/check_skill_sync.py 的测试。

规则（与 tools/check_skill_sync.py 保持一致）:
- skills/*.md 与 .qoder/skills/<name>/SKILL.md 去 frontmatter 后正文必须一致
- frontmatter (--- 到 ---) 允许差异 (.qoder 副本会加 trigger 键)
- 名称映射: python-SKILL.md → python; refactoring-guardian.md → refactoring-guardian
- 缺少 .qoder 注册副本 → 不一致
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from check_skill_sync import (  # noqa: E402
    check_skill_sync,
    normalize,
    skill_name,
    strip_frontmatter,
)


def _make_dirs(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    qoder_dir = tmp_path / "qoder_skills"
    skills_dir.mkdir()
    qoder_dir.mkdir()
    return skills_dir, qoder_dir


def test_strip_frontmatter():
    text = "---\nname: python\ndescription: x\n---\n\n# 正文\n内容"
    assert strip_frontmatter(text).strip() == "# 正文\n内容"

    no_fm = "# 没有 frontmatter"
    assert strip_frontmatter(no_fm) == no_fm


def test_skill_name_mapping():
    assert skill_name(Path("python-SKILL.md")) == "python"
    assert skill_name(Path("refactoring-guardian.md")) == "refactoring-guardian"


def test_normalize_whitespace():
    """CRLF / 行尾空白 / 首尾空行差异 → 归一化后一致"""
    a = normalize("\r\n# 标题\r\n正文  \r\n\r\n")
    b = normalize("\n# 标题\n正文\n")
    assert a == b


def test_same_body_passes(tmp_path):
    """正文一致 (frontmatter 不同) → 通过"""
    skills_dir, qoder_dir = _make_dirs(tmp_path)
    body = "# 正文\n内容一致\n"
    (skills_dir / "python-SKILL.md").write_text("---\nname: python\n---\n" + body, encoding="utf-8")
    target = qoder_dir / "python"
    target.mkdir()
    (target / "SKILL.md").write_text(
        "---\nname: python\ntrigger: x\n---\n" + body, encoding="utf-8"
    )
    assert check_skill_sync(skills_dir, qoder_dir) == []


def test_body_diff_flagged(tmp_path):
    """正文不一致 → 报告该技能"""
    skills_dir, qoder_dir = _make_dirs(tmp_path)
    (skills_dir / "python-SKILL.md").write_text("# 正文 A\n", encoding="utf-8")
    target = qoder_dir / "python"
    target.mkdir()
    (target / "SKILL.md").write_text("# 正文 B\n", encoding="utf-8")
    problems = check_skill_sync(skills_dir, qoder_dir)
    assert len(problems) == 1
    assert "python-SKILL.md" in problems[0]


def test_missing_registered_copy_flagged(tmp_path):
    """skills/ 有文件但 .qoder 无注册副本 → 报告缺失"""
    skills_dir, qoder_dir = _make_dirs(tmp_path)
    (skills_dir / "python-SKILL.md").write_text("# 正文\n", encoding="utf-8")
    problems = check_skill_sync(skills_dir, qoder_dir)
    assert len(problems) == 1
    assert "python-SKILL.md" in problems[0]
    assert "SKILL.md" in problems[0]


def test_plain_name_mapping_syncs(tmp_path):
    """skills/refactoring-guardian.md ↔ .qoder/skills/refactoring-guardian/SKILL.md"""
    skills_dir, qoder_dir = _make_dirs(tmp_path)
    body = "# 重构守卫\n内容\n"
    (skills_dir / "refactoring-guardian.md").write_text(
        "---\ndescription: x\n---\n" + body, encoding="utf-8"
    )
    target = qoder_dir / "refactoring-guardian"
    target.mkdir()
    (target / "SKILL.md").write_text(
        "---\ndescription: x\ntrigger: y\n---\n" + body, encoding="utf-8"
    )
    assert check_skill_sync(skills_dir, qoder_dir) == []
