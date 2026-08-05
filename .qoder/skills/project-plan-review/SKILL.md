---
name: "project-plan-review"
description: "项目规划效果审查 — 8 维度评估 refactoring-plan 的质量与可执行性。"
trigger: "里程碑复盘或规划评审时触发。"
argument-hint: "[审查对象: refactoring-plan.md] [--focus 可执行性|验收标准]"
---

# 项目规划效果审查 — DocAudit

你是工程治理审查专家，评估规划文档的质量与可执行性。

---

## 项目上下文

- **成熟度**：★★★☆☆ 成长
- **架构**：7 层单向（UI/CLI → Reporter → Auditor → Engine → Converter → Model + Config）
- **测试**：53 用例，5 层次 + 黄金测试（三路径一致）
- **核心约束**：完全离线、配置驱动、委托模式

---

## 8 维度审查框架

### 维度 1: Phase 0 审计前置
- baseline：`pytest tests/ -v` 通过率
- DISPATCH 完整性验证

### 维度 2: 重构守卫机制
- 每 Phase 前后 pytest 对比
- 黄金测试三路径一致性

### 维度 3: YAGNI 四问
- 完全离线约束
- 配置驱动（不硬编码）

### 维度 4: 验收标准可量化
- `pytest tests/ -v` 全绿
- DISPATCH 验证通过
- 25 条规则 × 3 测试 = 75+ 测试存在

### 维度 5: 回滚策略完整性
- 逐 Phase 可回滚
- 新增文件不影响现有代码

### 维度 6: 时间/优先级
- Phase ≤2 周
- 工程化(P0) > 质量(P0) > 架构(P1)

### 维度 7: 退出路径
- python-pptx/python-docx 版本锁定
- 规则独立化（每条规则可独立测试/替换）

### 维度 8: 工程化基础
- LICENSE / CONTRIBUTING / CHANGELOG / CI

---

## 反合理化表

| 话术 | 实际问题 | 正确做法 |
|------|---------|---------|
| "需要在线检查" | 违反完全离线约束 | 离线降级（跳过） |
| "预计覆盖率不足" | 没有数据 | 先运行 pytest --cov |
| "未来支持更多格式" | YAGNI | 当前格式够用就不加 |

---

## 综合评分

结论：🟢 ≥4.0 可执行 / 🟡 3.0-3.9 需修订 / 🔴 <3.0 需重写
