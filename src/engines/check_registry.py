"""dispatch 检查注册表 — check_type 的单一真相来源 (Engine 层，零依赖)。

为什么放在 Engine 层：注册表是纯声明数据（check_type / 方法名 / 调度标志），
Auditor（custom_rules）、pipeline 编排器与配置校验（validation）都需要读它。
放在 Auditor 层会让 Engine → Auditor 反向依赖，违反七层单向依赖；放在此处
各方均只能向下依赖。

新增 check_type 的两步注册见 AGENTS.md 红线 4。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckSpec:
    """单个 check_type 的声明式注册项。

    新增 dispatch 检查只需两步：
      ① 在对应 Auditor 上实现方法
      ② 在本表增加一行
    `_DISPATCH`（调度）与 pipeline 的 `_skip_checks`（避免 audit() 直调重复执行）
    均由注册表派生 —— 历史上「三步注册缺一」导致的静默失效不再可能发生。
    """

    auditor: str  # "sa"=Structure / "fa"=Format / "fca"=Factual
    method: str
    per_page: bool = False
    pptx_only: bool = False
    skip_key: str = ""  # audit() 内部守卫键；空串表示与 check_type 同名


# ── 检查注册表: check_type → CheckSpec ────────────────────────
# 注意: 语言检查（"la"）故意不在此表 —— 依赖 lt_client/vocabulary/terminology
# 有状态实例，始终直接运行，不走 dispatch 委托机制。
CHECK_REGISTRY: dict[str, CheckSpec] = {
    "first_slide_has_title_layout": CheckSpec(
        "sa", "_check_title_slide", pptx_only=True, skip_key="title_slide"
    ),
    "figure_numbering_sequential": CheckSpec(
        "sa", "_check_figure_numbering", skip_key="figure_numbering"
    ),
    # pptx_only 必须 False: 方法内已有 PPTX 守卫 (para.level 是缩进级别),
    # dispatch 再按 PPTX 过滤会让非 PPTX 的标题层级检查彻底失效 (2026-09-06 回归)
    "heading_level_sequential": CheckSpec("sa", "_check_heading_levels", skip_key="heading_levels"),
    "numeric_cross_reference": CheckSpec(
        "fca", "_check_numeric_consistency", skip_key="numeric_consistency"
    ),
    "abbreviation_first_defined": CheckSpec("fca", "_check_abbreviation_first_defined"),
    "abbreviation_defined_never_used": CheckSpec("fca", "_check_abbreviation_defined_never_used"),
    "abbreviation_multiply_defined": CheckSpec("fca", "_check_abbreviation_multiply_defined"),
    "abbreviation_used_before_defined": CheckSpec("fca", "_check_abbreviation_used_before_defined"),
    "every_slide_has_conclusion": CheckSpec(
        "sa", "_check_every_slide_has_conclusion", pptx_only=True, skip_key="every_slide_conclusion"
    ),
    "duplicate_title": CheckSpec("sa", "_check_duplicate_title"),
    "title_trailing_punctuation": CheckSpec(
        "sa", "_check_title_trailing_punctuation", per_page=True
    ),
    "figure_caption_format": CheckSpec("sa", "_check_figure_caption_format"),
    # element_overflow / per_page_char_limit 是幻灯片版面语义 (位置/单页字数),
    # DOCX/MD/PDF 的"页"是逻辑章节或真实分页, 不适用 — 2026-10-28 收敛为 PPTX only。
    "element_overflow": CheckSpec("fa", "_check_element_overflow", per_page=True, pptx_only=True),
    "empty_placeholder": CheckSpec(
        "fa", "_check_empty_placeholders", per_page=True, pptx_only=True
    ),
    "bullet_consistency": CheckSpec("fa", "_check_bullet_consistency", per_page=True),
    "per_page_char_limit": CheckSpec(
        "fa", "_check_per_page_char_limit", per_page=True, pptx_only=True
    ),
    "table_contrast": CheckSpec("fa", "_check_table_contrast", per_page=True),
    "slide_structure_consistency": CheckSpec(
        "sa", "_check_slide_structure_consistency", pptx_only=True
    ),
    "title_length": CheckSpec("sa", "_check_title_length"),
}
