"""规则 profile（严格 / 标准 / 宽松）— 一套规则适配不同交付等级（2026-11）。

profile 只调整两件事，不改规则本身：

- ``fail_on``：CI 退出码阈值（error → 阻断；warning/none 逐级放宽）；
- ``min_severity``：报告/摘要中保留的最低严重度（宽松档隐藏 info 级提示）。

规则内容仍由 rules.md 唯一决定；profile 是"同一规则集的不同执行口径"，
显式传 ``--fail-on`` 时以命令行为准。
"""

from __future__ import annotations

PROFILES: dict[str, dict] = {
    # 对外发布/评审会材料：warning 即阻断
    "strict": {"fail_on": "warning", "min_severity": "info"},
    # 日常交付（默认）：error 阻断
    "standard": {"fail_on": "error", "min_severity": "info"},
    # 草稿/内部讨论：不阻断，且隐藏 info 提示降低噪音
    "relaxed": {"fail_on": "none", "min_severity": "warning"},
}

DEFAULT_PROFILE = "standard"

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def get_profile(name: str | None) -> dict:
    """返回 profile 配置（未知名称回退 standard，并保留原始选择供 CLI 提示）。"""
    key = (name or DEFAULT_PROFILE).strip().lower()
    if key not in PROFILES:
        return dict(PROFILES[DEFAULT_PROFILE], requested=key, unknown=True)
    return dict(PROFILES[key], requested=key, unknown=False)


def filter_by_severity(findings: list, min_severity: str) -> list:
    """过滤低于 min_severity 的发现（profile 的"降噪"语义）。"""
    threshold = _SEVERITY_ORDER.get(min_severity, 2)
    return [f for f in findings if _SEVERITY_ORDER.get(f.severity.value, 2) <= threshold]
