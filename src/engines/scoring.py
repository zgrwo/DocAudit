"""质量分（Quality Score）— 把发现列表折算成可解释的 0-100 分与等级。

设计口径（2026-11 新增，报告"好不好"的第一层量化）：

- 只计**可行动**发现：``SYS-ERROR``（系统错误）不进罚分——它表示"没查成"，
  应体现在 Coverage 的完整性声明里，而不是质量扣分。
- 罚分 = Σ(严重度权重 × 条数) / 页数（页数至少 1），避免短文档被少量问题秒杀。
- ``score = 100 × max(0, 1 - 罚分/满分罚分)``；满分罚分默认 20
  （``DEFAULT_PENALTY_CAP`` 常量；如后续需要可按 frontmatter parameters 接入），
  即"每页 2 个 error 即 0 分"。
- 估算类发现（metadata.estimated=True，如溢出/表格 fit/DPI 估算）按半权计入，
  因为它们不是精确测量。
- 分维度（结构/格式/语言/事实/自定义）按同一公式给出子分，便于定位短板。
"""

from __future__ import annotations

from collections import defaultdict

from src.models.finding import AuditFinding

# 严重度权重（1 个 error ≈ 3 个 warning ≈ 10 个 info）
SEVERITY_WEIGHTS: dict[str, float] = {"error": 10.0, "warning": 3.0, "info": 1.0}

# 发现类型 → 展示维度（SYS-ERROR 不计分，单独统计）
DIMENSION_LABELS: dict[str, str] = {
    "structure": "结构",
    "format": "格式",
    "language": "语言",
    "terminology": "语言",
    "factual": "事实",
    "custom": "自定义规则",
    "system": "系统",
}

# 等级阈值
GRADE_THRESHOLDS: tuple[tuple[str, int], ...] = (("A", 90), ("B", 75), ("C", 60))

DEFAULT_PENALTY_CAP = 20.0
ESTIMATED_FINDING_WEIGHT = 0.5


def _finding_weight(finding: AuditFinding) -> float:
    base = SEVERITY_WEIGHTS.get(finding.severity.value, 1.0)
    if (finding.metadata or {}).get("estimated"):
        return base * ESTIMATED_FINDING_WEIGHT
    return base


def _score_from_penalty(penalty_per_page: float, cap: float) -> int:
    if cap <= 0:
        return 100
    ratio = min(1.0, max(0.0, penalty_per_page / cap))
    return int(round(100 * (1.0 - ratio)))


def _grade(score: int) -> str:
    for label, threshold in GRADE_THRESHOLDS:
        if score >= threshold:
            return label
    return "D"


def compute_score(
    findings: list[AuditFinding],
    page_count: int,
    *,
    penalty_cap: float = DEFAULT_PENALTY_CAP,
) -> dict:
    """计算质量分。

    Args:
        findings: 去重后的发现列表。
        page_count: 文档页数（逻辑页/幻灯片页），至少按 1 计。
        penalty_cap: 满分罚分（每页加权罚分达到该值即 0 分）。

    Returns:
        ``{"score", "grade", "penalty", "penalty_per_page", "pages",
        "counts", "dimensions", "system_errors", "estimated"}``
    """
    pages = max(1, int(page_count or 0))
    penalty = 0.0
    counts = {sev: 0 for sev in SEVERITY_WEIGHTS}
    dim_penalty: dict[str, float] = defaultdict(float)
    dim_counts: dict[str, int] = defaultdict(int)
    system_errors = 0
    estimated = 0

    for finding in findings:
        if finding.type.value == "system" or finding.rule_id == "SYS-ERROR":
            system_errors += 1
            continue
        weight = _finding_weight(finding)
        if (finding.metadata or {}).get("estimated"):
            estimated += 1
        counts[finding.severity.value] = counts.get(finding.severity.value, 0) + 1
        penalty += weight
        dimension = DIMENSION_LABELS.get(finding.type.value, "其他")
        dim_penalty[dimension] += weight
        dim_counts[dimension] += 1

    per_page = penalty / pages
    score = _score_from_penalty(per_page, penalty_cap)

    dimensions = {
        name: {
            "score": _score_from_penalty(dim_penalty[name] / pages, penalty_cap),
            "count": dim_counts[name],
            "penalty": round(dim_penalty[name], 1),
        }
        for name in sorted(dim_penalty)
    }

    return {
        "score": score,
        "grade": _grade(score),
        "penalty": round(penalty, 1),
        "penalty_per_page": round(per_page, 2),
        "penalty_cap": penalty_cap,
        "pages": pages,
        "counts": counts,
        "dimensions": dimensions,
        "system_errors": system_errors,
        "estimated": estimated,
    }
