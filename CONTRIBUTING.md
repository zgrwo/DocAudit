# 贡献指南

感谢你对 DocAudit 的关注！本指南帮助你快速上手贡献代码。

---

## 开发环境搭建

```bash
# 克隆项目
git clone https://github.com/zgrwo/DocAudit.git
cd DocAudit

# 创建虚拟环境 + 安装
python -m venv .venv
.venv\Scripts\pip install -e .[all]   # Windows
# .venv/bin/pip install -e .[all]     # Linux/macOS

# 运行测试确认环境正常
pytest tests/ -v
```

---

## 新增审查规则流程

新增一个 `check_type` 必须完成 **三步注册**，缺一不可：

### 步骤 1：在对应 Auditor 中实现方法

```python
# src/auditors/structure.py (或 format.py / factual.py)
def _check_xxx(self, page, doc) -> list[AuditFinding]:  # per_page=True
    """检查说明"""
    findings = []
    # ... 检查逻辑 ...
    return findings
```

方法签名由 `_DISPATCH` 中的 `per_page` 决定：
- `per_page=True` → `(self, page, doc)`
- `per_page=False` → `(self, doc)`

### 步骤 2：在 `_DISPATCH` 表中注册

```python
# src/auditors/custom_rules.py — _DISPATCH 字典
"xxx_check_type": ("sa", "_check_xxx", True, False),
#                   ↑       ↑            ↑     ↑
#               auditor_key  method_name  per_page  pptx_only
```

### 步骤 3：在 `_skip_checks` 中排除

```python
# src/engines/pipeline.py — build_auditors()
"_skip_checks": [..., "xxx_check_type"],
```

### 步骤 4：在 `rules.md` 中声明规则

```markdown
## STR-XXX: 规则描述
- 严重度: warning
- 说明: 规则详细说明
- 检查: xxx_check_type
```

### 步骤 5：验证

```bash
# DISPATCH 完整性
python -c "from src.auditors.custom_rules import CustomRulesAuditor; print(CustomRulesAuditor.validate_dispatch())"

# 全量测试
pytest tests/ -v
```

---

## Finding 编写规范

- `message`: 中文，简洁陈述问题，50 字以内
- `suggestion`: 中文，可操作的修改建议
- `rule_id`: 必须与 `rules.md` 中的规则 ID 一致
- `context`: 截断到 100-150 字符
- `location`: 格式 `第 {n} 页`

---

## PR 规范

1. **分支命名**: `feature/xxx` 或 `fix/xxx`
2. **Commit 格式**: `type: 简短描述`（type = feat/fix/docs/test/refactor）
3. **PR 描述**: 说明改了什么、为什么改、如何验证
4. **必须通过**:
   - `pytest tests/ -v` 全绿
   - DISPATCH 验证通过
   - 黄金测试三路径一致
   - 无裸 `except:` 或不记录日志的异常捕获
   - 所有用户文本已 `html.escape()`（如涉及报告输出）

---

## 代码风格

- 行宽 100 字符（ruff 配置）
- Python ≥ 3.10 语法（`X | Y` 联合类型）
- 类型注解覆盖所有公开接口
- 日志使用 `logging.getLogger(__name__)`
- 用户可见文本使用中文

---

## 架构约束

- **七层单向依赖**: UI/CLI → Reporter → Auditor → Engine → Converter → Model + Config 横切
- **CustomRulesAuditor 是路由器**，不含检查逻辑
- **配置驱动**: 阈值从 `extract_auditor_config()` 获取，不硬编码
- **完全离线**: 无网络调用、无数据上报

---

## 文档同步

| 变更类型 | 需同步的文档 |
|---------|------------|
| 新增 Public 接口 | `rules/api-reference.md` |
| 新增/删除/移动文件 | `rules/project-structure.md` |
| 修改 rules.md 格式 | `src/engines/rule_parser.py` |
| 用户可见功能变更 | `rules/user-manual.md` |
