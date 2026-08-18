# DocAudit — 重构计划

> **执行状态（2026-08-18 批注）**：本文件为 2026-07 制定的历史规划参考，非当前事实。
> 多数 Phase 已完成或决策已搁置——LICENSE/CONTRIBUTING/CHANGELOG 已补齐、CI 与
> DISPATCH/裸异常/文档数字门禁已上线、LanguageTool 降级已落地、插件化与七层重构已明确搁置；
> 文中"7 commits / 25 条规则 / 139 用例"等数字均为规划当时快照，不代表当前状态。
> **当前事实以 AGENTS.md / README.md / rules.md 为准**，本文件不再逐项更新。

> 基于 7 commits 全量历史分析（规划当时） | 目标：从"可用"到"稳定+易扩展"
> 项目成熟度：★☆☆☆☆（非常早期，先稳定再扩展，避免过度工程）
> 对标项目：markdownlint / proselint / retext / GitHub Content Linter
> ⚠️ 核心审查结论：架构合理但**层数偏多**（5 个 Auditor 不需要 7 层），规则生态薄弱

## 1. 现状评估

### 1.1 优势（必须保留）

| 维度 | 现状 | 评价 |
|------|------|------|
| 完全离线 | 文档不上传任何服务器 | ★★★★★ 核心卖点 |
| 配置驱动 | rules.md 声明规则 | ★★★★★ |
| 黄金测试 | CLI=WebUI=Python 三路径一致 | ★★★★★ |
| 七层架构 | 严格单向依赖 | ★★★★☆ |
| 委托模式 | CustomRulesAuditor 路由 | ★★★★☆ |

### 1.2 痛点（历史反复出错）

| 痛点 | 出现次数 | 根因 | 优先级 |
|------|----------|------|--------|
| 空值安全 | 11 项修复 | 边界情况未覆盖 | P0 |
| DISPATCH 注册遗漏 | 2+ 次 | 三步注册法未强制执行 | P0 |
| rules.md 格式同步 | 2+ 次 | 修改格式忘更新 rule_parser.py | P1 |
| context 截断 | 2+ 次 | HTML 报告显示异常 | P1 |
| Group 子元素漏检 | 1+ 次 | 未用 flattened_elements | P1 |

### 1.3 与 GitHub 同类项目的差距

| 维度 | 当前状态 | 卓越标准（markdownlint/proselint） | 差距等级 |
|------|---------|----------------------------------|---------|
| 规则生态 | 25 条规则，硬编码 | 80+ 规则，每条可独立启用/禁用/配置 | 🔴 高 |
| 自动修复 | 无 | markdownlint `--fix`；proselint JSON 输出 | 🔴 高 |
| 增量审查 | 全量扫描 | retext AST 级别增量（只检查变更段落） | 🟡 中 |
| 输出格式 | HTML + JSON | SARIF（GitHub Code Scanning 集成） | 🟡 中 |
| 性能 | 无基准 | 大文档（100+ 页）<10s | 🟡 中 |
| 规则测试 | 139 个用例（整体） | 每条规则至少 3 个测试（pass/fail/edge） | 🔴 高 |
| 开源基础 | ✅ 已完成 | MIT + 贡献指南 + Issue 模板 | ✅ |

### 1.4 技术债（需审计确认）

> ⚠️ 项目仅 7 commits，以下技术债为推测，需 Phase 0 审计确认实际范围

- [ ] 测试覆盖率 139 用例，但边界情况不足
- [ ] 缺少性能测试（大文档/批量审查）
- [ ] LanguageTool 依赖 Docker，部署复杂
- [ ] 报告模板硬编码，难以自定义
- [x] ~~无 LICENSE / CONTRIBUTING.md / CHANGELOG~~（已补齐）
- [ ] 规则无独立测试（25 条规则 × 3 = 75 个最低测试缺失）

### 1.5 关于"插件化"的决策

> **YAGNI 原则**：当前仅 5 个审查维度，插件化架构属于过度设计。
>
> **决策**：v1.0 采用"约定式扩展"（文档说明如何新增），v2.0 再考虑插件化。

### 1.6 关于"七层架构"的决策

> **审查结论**：7 层对 5 个 Auditor 偏多，但已实现且运行正常，**不重构层数**。
>
> **决策**：保持现有 7 层，但新增功能不再增加层数。未来如果 Auditor >10 个再评估。

## 2. 重构目标

### 2.1 核心目标

1. **健壮性**（P0）：空值/边界情况覆盖，消除 11 项修复类问题
2. **工程化基础设施**（P0）：CI/CD + LICENSE + CHANGELOG + 贡献指南
3. **规则独立化**（P1）：每条规则独立文件 + 独立测试 + 可配置
4. **自动修复**（P1）：至少支持术语替换自动修复
5. **SARIF 输出**（P1）：可集成到 GitHub Code Scanning
6. **部署简化**（P2）：LanguageTool 可选，不阻断流程

### 2.2 非目标

- ❌ 不支持在线协作（保持离线优先）
- ❌ 不支持更多文档格式（v1.0 仅 PPTX/DOCX/PDF/MD）
- ❌ 不重写 Streamlit UI（已满足需求）
- ❌ **不做插件化架构**（v2.0 再议，当前 5 个 Auditor 不需要）
- ❌ **不重构七层架构**（已实现且运行正常）
- ❌ **不设定性能目标**（先有 baseline 再说）

## 3. 重构方案

### 3.0 Phase 0: 重构前审计（2-3 天）【P0，必须先做】

**目标**：建立 baseline，确认实际技术债范围

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| 空值风险审计 | `grep -rn "\.elements" src/` | 记录直接遍历 page.elements 的位置 |
| DISPATCH 完整性检查 | 运行 `validate_dispatch()` | 记录遗漏数量 |
| 测试覆盖率审计 | `pytest --cov=src` | 记录当前覆盖率百分比 |
| 性能 baseline 测量 | 审查 10/50/100 页文档 | 记录耗时（秒） |
| 全量测试 baseline | `pytest tests/ -v` | 记录通过/失败数 |
| 规则测试覆盖审计 | 检查 25 条规则各有几个测试 | 记录缺失数量 |

**决策点**：
- 如果空值风险点 >20 处，Phase 1 需要系统性修复
- 如果 DISPATCH 有遗漏，Phase 1 优先修复
- 如果 100 页文档 >60s，Phase 3 需要考虑性能优化
- 如果规则测试 <50 个，Phase 2 需要补全

### 3.1 Phase 1: 工程化基础 + 健壮性加固（1-2 周）【P0，核心】

**目标**：补齐开源基本要素 + 空值/边界情况覆盖

| 任务 | 产出 | 验收标准 | 依赖 |
|------|------|----------|------|
| 添加 LICENSE | `LICENSE`（MIT） | 文件存在 | — |
| 添加 CONTRIBUTING.md | `CONTRIBUTING.md` | 含新增规则流程/PR 规范 | — |
| 添加 CHANGELOG.md | `CHANGELOG.md`（keepachangelog） | 含 v0.1.0 记录 | — |
| GitHub Actions CI | `.github/workflows/ci.yml` | PR 触发 pytest + 黄金测试 | — |
| Issue/PR 模板 | `.github/ISSUE_TEMPLATE/` | bug/rule-request 模板 | — |
| 空值安全修复 | 源码修复 | 所有遍历用 flattened_elements | Phase 0 |
| DISPATCH 完整性修复 | 源码修复 | validate_dispatch() 返回 [] | Phase 0 |
| 边界测试补全 | `tests/test_edge_cases.py` | 空文档/单页/超大文档 | — |
| context 截断统一 | `src/utils/text.py` | 所有输出统一截断（50-150 字符） | — |

**常见空值陷阱**：
```python
# ❌ 错误：page.elements 可能为 None，且漏检 Group 子元素
for elem in page.elements:
    process(elem)

# ✅ 正确：用 flattened_elements + 空值保护
for elem in (page.flattened_elements or []):
    process(elem)
```

**回滚策略**：基础设施是新增文件；空值修复逐文件提交；边界测试是新增文件。

### 3.2 Phase 2: 规则独立化 + 自动修复（1-2 周）【P1】

**目标**：每条规则独立文件 + 独立测试 + 术语替换自动修复

| 任务 | 产出 | 验收标准 | 依赖 |
|------|------|----------|------|
| 规则文件独立化 | `src/rules/STRUCT_001.py` 等 | 25 条规则各自独立文件 | Phase 1 |
| 规则 YAML 配置 | 每条规则文件头部 YAML front-matter | 可独立启用/禁用/配置严重级别 | 上一项 |
| 规则独立测试 | `tests/rules/test_STRUCT_001.py` 等 | 每条规则 ≥3 测试（pass/fail/edge） | 上一项 |
| 术语替换自动修复 | `--fix` CLI 参数 | 术语黑名单自动替换为白名单 | Phase 1 |
| 三步注册法自动化检查 | `scripts/check_dispatch.py` | pre-commit 检查 DISPATCH 完整性 | Phase 1 |
| Auditor 开发指南 | `docs/auditor-guide.md` | 逐步说明如何新增规则 | — |

**规则文件设计**：
```python
# src/rules/STRUCT_001.py
"""
---
id: STRUCT-001
name: 标题层级不跳跃
severity: warning
enabled: true
fixable: false
---
"""

def check(document, config) -> list[Finding]:
    """检查标题层级是否连续（不跳跃）"""
    findings = []
    prev_level = 0
    for elem in document.flattened_elements:
        if elem.type == "heading":
            if elem.level > prev_level + 1:
                findings.append(Finding(
                    rule_id="STRUCT-001",
                    message=f"标题从 L{prev_level} 跳到 L{elem.level}",
                    severity="warning",
                    location=elem.location,
                ))
            prev_level = elem.level
    return findings
```

**规则测试模板**：
```python
# tests/rules/test_STRUCT_001.py
def test_pass_consecutive_levels():
    """L1→L2→L3 不报错"""

def test_fail_skipped_level():
    """L1→L3 报 warning"""

def test_edge_empty_document():
    """空文档不报错"""
```

**回滚策略**：规则独立化在分支进行；自动修复是新增 CLI 参数，不影响现有行为。

### 3.3 Phase 3: SARIF 输出 + 报告自定义（1 周）【P1】

**目标**：可集成到 GitHub Code Scanning + 用户可自定义报告

| 任务 | 产出 | 验收标准 | 依赖 |
|------|------|----------|------|
| SARIF 输出格式 | `src/reporters/sarif.py` | 符合 SARIF v2.1.0 规范 | Phase 1 |
| CLI `--format sarif` | CLI 参数扩展 | 输出可被 GitHub 解析 | 上一项 |
| Jinja2 模板引擎 | `templates/report.html.j2` | HTML 报告可自定义 | Phase 1 |
| 默认模板 | `templates/` | 2-3 个预设模板 | — |
| 配置支持 | rules.md 扩展 | 指定模板路径 + 输出格式 | — |

**SARIF 输出示例**：
```json
{
  "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
  "version": "2.1.0",
  "runs": [{
    "tool": { "driver": { "name": "DocAudit", "version": "0.2.0" } },
    "results": [{
      "ruleId": "STRUCT-001",
      "level": "warning",
      "message": { "text": "标题从 L1 跳到 L3" },
      "locations": [{ "physicalLocation": { "artifactLocation": { "uri": "report.pptx" } } }]
    }]
  }]
}
```

**回滚策略**：SARIF 是新增输出格式；模板是新增文件；配置扩展向后兼容。

### 3.4 Phase 4: 部署简化 + 性能（按需）【P2】

| 任务 | 产出 | 验收标准 | 依赖 |
|------|------|----------|------|
| LanguageTool 可选 | 降级策略完善 | 无 Docker 也可运行 | — |
| 一键安装脚本 | `scripts/install.ps1` | 自动配置环境 | — |
| Docker Compose | `docker-compose.yml` | 一键启动全套 | — |
| 增量审查（可选） | 文件 hash 缓存 | 未修改文档跳过审查 | Phase 0 数据 |
| 并行审查（可选） | multiprocessing | 多文档并行处理 | Phase 0 数据 |
| Semantic Versioning | git tag `v0.2.0` | 版本号与 CHANGELOG 一致 | — |

**增量审查设计**：
```python
# 基于文件 hash 的增量审查
cache_file = Path(".docaudit_cache.json")

def should_audit(file_path: Path) -> bool:
    """文件未修改则跳过"""
    current_hash = hashlib.md5(file_path.read_bytes()).hexdigest()
    cached = load_cache().get(str(file_path))
    return cached != current_hash
```

## 4. 里程碑与时间线

```
Phase 0 (2-3天): 重构前审计 — 建立 baseline 【必须先做】
  ├─ Day 1: 空值风险 + DISPATCH 完整性
  └─ Day 2: 测试覆盖率 + 性能 baseline + 规则测试审计

Phase 1 (1-2周): 工程化 + 健壮性 【P0，核心】
  ├─ LICENSE + CONTRIBUTING + CHANGELOG + CI
  ├─ 空值安全修复 + DISPATCH 修复
  └─ 边界测试 + context 截断

Phase 2 (1-2周): 规则独立化 + 自动修复 【P1】
  ├─ 25 条规则独立文件 + YAML 配置
  ├─ 每条规则 ≥3 测试（75+ 测试）
  └─ --fix 术语替换 + Auditor 开发指南

Phase 3 (1周): SARIF + 报告自定义 【P1】
  ├─ SARIF v2.1.0 输出
  ├─ Jinja2 模板
  └─ 配置支持

Phase 4 (按需): 部署 + 性能 【P2】
  ├─ LanguageTool 可选 + Docker Compose
  └─ 增量审查 + 并行审查（有 baseline 后再决定）
```

## 5. 重构守卫（每 Phase 必须执行）

```
Phase 开始前：
  ① pytest tests/ -v（139 用例全通过）
  ② python -c "from src.auditors.custom_rules import CustomRulesAuditor; print(CustomRulesAuditor.validate_dispatch())"
  → 记录通过数/失败数

Phase 结束后：
  ①② 同上
  → 对比：任何新增失败 = 立即回滚该 Phase 的修改
  → 黄金测试必须通过：CLI=WebUI=Python 三路径一致
```

## 6. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 空值修复引入回归 | 中 | 高 | 黄金测试全量运行 |
| 规则独立化破坏 DISPATCH | 中 | 高 | 分支开发 + validate_dispatch() 验证 |
| 模板引擎性能 | 低 | 中 | 大文档基准测试（Phase 0 数据） |
| LanguageTool 兼容性 | 中 | 低 | 降级策略 + 版本锁定 |
| SARIF 格式不合规 | 低 | 中 | 用 sarif-tools 验证输出 |
| 约定式扩展不够用 | 低 | 低 | v2.0 再考虑插件化 |

## 7. 验收标准

重构完成后，以下指标必须达成：

- [ ] 空值风险点清零（Phase 0 baseline → 0）
- [ ] DISPATCH 完整性检查通过（validate_dispatch() 返回 []）
- [ ] 边界测试覆盖：空文档/单页/超大文档
- [ ] 25 条规则独立文件 + 每条 ≥3 测试（75+ 测试）
- [ ] `--fix` 支持术语替换自动修复
- [ ] SARIF v2.1.0 输出可被 GitHub Code Scanning 解析
- [ ] 报告模板可自定义（Jinja2）
- [ ] 黄金测试三路径一致（零回归）
- [ ] LICENSE + CONTRIBUTING + CHANGELOG 完整
- [ ] CI PR 自动触发（pytest + 黄金测试）

## 8. 历史经验教训（必须铭记）

### 8.1 DISPATCH 注册遗漏的教训

**根因**：三步注册法（Auditor 方法 + _DISPATCH + _skip_checks）未强制执行

**对策**：
- 约定式扩展文档明确说明三步
- pre-commit 脚本检查 DISPATCH 完整性
- v2.0 再考虑自动注册的插件化

### 8.2 rules.md 格式同步的教训

**根因**：修改 rules.md 格式忘更新 rule_parser.py

**对策**：
- 格式变更必须同步更新 parse_rules_md() + extract_auditor_config()
- 添加格式变更测试（解析旧格式 + 新格式）

### 8.3 Group 子元素漏检的教训

**根因**：直接遍历 page.elements，未递归展开 Group

**对策**：
- 所有遍历必须用 page.flattened_elements
- 静态检查拦截 page.elements 直接遍历

### 8.4 context 截断的教训

**根因**：HTML 报告中 context 过长导致显示异常

**对策**：
- 统一截断工具函数（50-150 字符）
- 所有输出点调用截断函数
