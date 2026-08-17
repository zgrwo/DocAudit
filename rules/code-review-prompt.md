# 深度代码审查 Prompt — DocAudit

> 从最小审查（min）到最大审查（max）的分级模板。根据变更范围选择对应级别。

## 审查级别

| 级别 | 适用场景 | 维度数 | 预计耗时 |
|------|----------|--------|----------|
| **Min** | 单文件小修复 | 3 | 5 min |
| **Standard** | 功能迭代（≤5 文件） | 6 | 15 min |
| **Max** | 发版前全量审查 | 10 | 30+ min |

---

## Min 审查（3 维度）

```
请对以下变更执行 3 维度审查：

1. **正确性**：逻辑是否正确？边界条件是否覆盖？
2. **防御性**：None/空字符串/空列表是否有守卫？
3. **一致性**：与现有代码风格、命名、架构是否一致？

输出格式：
- P0（必须修复）：会导致崩溃/数据错误
- P1（建议修复）：潜在风险
- P2（改善）：可读性/性能优化
```

---

## Standard 审查（6 维度）

```
请对以下变更执行 6 维度并行审查：

1. **正确性**：算法逻辑、边界条件、规则匹配准确性
2. **防御性**：None/空值/空列表守卫完整性；html.escape 覆盖所有用户文本字段
3. **安全性**：离线保证（无网络调用）；路径遍历防护；注入防护
4. **一致性**：架构分层（7层单向依赖）；命名规范；文档同步
5. **性能**：大文件处理（PPTX/DOCX >50MB）；不必要的内存拷贝；循环优化
6. **测试覆盖**：新增代码是否有对应测试？黄金测试是否三路径一致？

输出格式：
- 按 P0→P3 分级
- 每项包含：文件:行号 | 问题描述 | 修复建议
- 最后给出总结：通过/有条件通过/需返工
```

---

## Max 审查（10 维度）

```
请对 DocAudit 项目执行发版前全量深度审查，覆盖以下 10 个维度：

1. **规则正确性**：26 条审查规则逻辑正确；检查覆盖范围无遗漏
2. **防御编程**：None/空值守卫；html.escape 全覆盖（message/context/suggestion/location/source_path/title）
3. **安全**：完全离线保证（零网络调用、零数据上报）；路径沙箱；文件类型白名单
4. **架构合规**：7 层单向依赖（UI→Reporter→Auditor→Engine→Converter→Model）；Config 横切层
5. **注册完整性**：CustomRulesAuditor._DISPATCH 注册完整；_skip_checks 匹配；rule_parser 同步 rules.md
6. **文档一致性**：api-reference 签名与代码一致；rules.md 格式与 parser 一致
7. **测试完备性**：黄金测试三路径一致（CLI=WebUI=Python）；139 个用例全绿；边界/退化输入覆盖
8. **性能**：大文档处理（>100 MB PPTX）；不必要的内容重解析；内存峰值控制
9. **错误处理**：无裸 except；LanguageTool 不可用降级；文件格式不支持时的优雅错误提示
10. **工程规范**：无死代码；命名一致；commit 粒度合理

输出格式：
[P{级别}] {文件}:{行号} — {问题} → {修复建议}
统计 + 结论：🟢/🟡/🔴
```

---

## 审查前置条件

- [ ] 已加载 AGENTS.md（了解 7 层架构、红线规则）
- [ ] 已加载 `skills/python/SKILL.md`（了解 Python 陷阱）
- [ ] 已运行 `pytest tests/ -v`（确认当前基线）
- [ ] 已确认 `_DISPATCH` 和 `_skip_checks` 完整性

## 审查后行动

| 发现级别 | 行动 |
|----------|------|
| P0 | 立即修复，不可跳过 |
| P1 | 本次修复，除非有明确豁免理由 |
| P2 | 记录到改进计划，下次迭代处理 |
| P3 | 可选修复，不阻塞发版 |

---

## DocAudit 专项检查清单

### 新增规则审查

```
新增 check_type 时必须逐一验证：
□ Auditor 方法实现完整
□ _DISPATCH 表已注册
□ _skip_checks 已添加
□ rules.md 规则声明已添加
□ rule_parser 可正确解析
□ 黄金测试覆盖（三路径一致）
□ html.escape 覆盖所有输出字段
```

### HTML 安全审查

```
所有用户文本字段必须 html.escape()：
□ message
□ context
□ suggestion
□ location
□ source_path
□ title
□ 任何从文档内容派生的字符串

grep 检查: grep -rn "html\.escape" src/ --include="*.py"
反模式检查: grep -rn "f\"{.*(message|context|suggestion|location|title)" src/ --include="*.py"
```

### 离线安全审查

```
□ 无 import requests / urllib / socket
□ 无 http:// 或 https:// URL 硬编码
□ 无数据上报/遥测逻辑
□ 文件路径限定在用户指定目录
□ 第三方库（LanguageTool 等）可降级
```

### DISPATCH 完整性验证

```bash
# 验证 _DISPATCH 与 _skip_checks 一致性
python -c "
from src.auditors.custom_rules import CustomRulesAuditor
print(CustomRulesAuditor.validate_dispatch())
"
# 预期: ✓ 所有 check_type 注册完整
```
