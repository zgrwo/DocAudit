"""CI 验证脚本：skills/ 与 .qoder/skills/ 双份技能维护一致性检查。

skills/*.md 与 .qoder/skills/<name>/SKILL.md 是同一技能的仓库副本与注册副本，
正文必须一致。frontmatter（--- 到 --- 之间的 YAML 块）允许差异（.qoder 副本会加 trigger 等键）。

名称映射: skills/python-SKILL.md → python；skills/refactoring-guardian.md → refactoring-guardian。
退出码 0 = 通过，1 = 存在不一致。
"""

import sys
from pathlib import Path

# 平台本地技能白名单: 源文件在 .qoder/prompts/<name>.prompt.md (平台本地资产, 不入库)，
# 注册副本在 .qoder/skills/<name>/SKILL.md (入库)。与 AGENTS.md「技能加载」表一致。
# 不能靠 .qoder/prompts 文件存在性豁免 — CI 全新检出时该目录不存在, 门禁会误报
# (2026-08-19 CI lint job 实测失败)。
PLATFORM_LOCAL_SKILLS = frozenset({"deep-code-review"})


def strip_frontmatter(text: str) -> str:
    """去除文档开头的 YAML frontmatter 块（--- 到 --- 之间），返回正文。"""
    if text.startswith("\ufeff"):
        # LOW13: BOM 容错 — utf-8 读取保留 BOM，且 \ufeff 不属于空白 (strip 不剥离)，
        # 须先显式剥除再判 frontmatter，否则带 BOM 的文件会被整体当作正文误报不一致
        text = text[1:]
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        end = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
        if end is not None:
            return "\n".join(lines[end + 1 :])
    return text


def normalize(text: str) -> str:
    """归一化正文: CRLF→LF、行尾空白去除、首尾空行去除（避免行尾差异误报）。"""
    normalized = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))
    return normalized.strip() + "\n"


def skill_name(skill_file: Path) -> str:
    """skills/ 下文件 → 技能名 (python-SKILL.md → python; refactoring-guardian.md → refactoring-guardian)"""
    stem = skill_file.stem
    return stem[: -len("-SKILL")] if stem.endswith("-SKILL") else stem


def check_skill_sync(skills_dir: Path, qoder_skills_dir: Path) -> list[str]:
    """返回 skills/ 与 .qoder/skills/ 的不一致清单（空列表 = 通过）。"""
    problems: list[str] = []
    for skill_file in sorted(skills_dir.glob("*.md")):
        name = skill_name(skill_file)
        target = qoder_skills_dir / name / "SKILL.md"
        if not target.exists():
            problems.append(f"{skill_file.name} → 缺少对应注册副本 .qoder/skills/{name}/SKILL.md")
            continue
        body_a = normalize(strip_frontmatter(skill_file.read_text(encoding="utf-8")))
        body_b = normalize(strip_frontmatter(target.read_text(encoding="utf-8")))
        if body_a != body_b:
            problems.append(
                f"{skill_file.name} 与 .qoder/skills/{name}/SKILL.md 正文不一致 (去 frontmatter 后)"
            )
    # LOW13: 双向检查 — .qoder/skills 下多余的注册副本 (skills/ 无对应源文件) 也报。
    # 例外: 源在 .qoder/prompts/<name>.prompt.md 的平台本地资产 (不入库, 如 deep-code-review)
    prompts_dir = qoder_skills_dir.parent / "prompts"
    for reg_dir in sorted(qoder_skills_dir.iterdir()) if qoder_skills_dir.is_dir() else []:
        if not reg_dir.is_dir():
            continue
        name = reg_dir.name
        # 白名单内平台本地技能 (源在 .qoder/prompts/, 不入库) 直接豁免
        if name in PLATFORM_LOCAL_SKILLS:
            continue
        source = skills_dir / f"{name}-SKILL.md"
        if not source.exists():
            source = skills_dir / f"{name}.md"
        if not source.exists() and not (prompts_dir / f"{name}.prompt.md").exists():
            problems.append(
                f"多余注册副本 .qoder/skills/{name}/SKILL.md — skills/ 无对应源文件 "
                f"({name}-SKILL.md / {name}.md)，且无平台本地源 (.qoder/prompts/{name}.prompt.md)"
            )
    return problems


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    skills_dir = root / "skills"
    qoder_skills_dir = root / ".qoder" / "skills"

    problems = check_skill_sync(skills_dir, qoder_skills_dir)
    if problems:
        print("技能双份维护检查失败 — 以下 skills/ 与 .qoder/skills/ 不一致:")
        for p in problems:
            print(f"  - {p}")
        print("\n请同步 skills/ 与 .qoder/skills/<name>/SKILL.md 的正文 (frontmatter 允许差异)")
        return 1

    print("skill sync check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
