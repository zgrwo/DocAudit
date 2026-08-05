# agents.md — DocAudit 项目宪法

> 本地离线文档审查系统：PPTX/DOCX/PDF/MD → 25 条规则 → HTML/JSON 报告。完全离线，零数据上报。
> 本文件面向 AI 编程助手，编码细节按需加载 Skill。

## 元数据

- **项目名**：DocAudit
- **GitHub**：https://github.com/zgrwo/DocAudit
- **语言**：Python（文档中文）
- **数字唯一基准**：`rules/api-reference.md` — 函数签名以此为准
- **SSOT**：每个事实只在一处定义，其余仅链接引用

## 四条核心准则

### 1. 先想后写 (Think Before Coding)

- **不确定就提问**。不要猜测业务规则——去查 specification。
- **说出来你做假设了**。
- **发现架构偏离时停下来**。例如：发现自己在 CustomRulesAuditor 中写了检查逻辑 → 停下，它只是路由器。

### 2. 简洁至上 (Simplicity First)

- **最少代码解决问题**。
- **不为一成不变的场景建抽象层**。
- **自检**：一个资深开发者看这段代码会觉得过度设计吗？

### 3. 精准修改 (Surgical Changes)

- **只改该改的**。不要顺带重构无关代码。
- **匹配现有风格**。
- **发现无关问题时提出来，不擅自改**。

### 4. 目标驱动 (Goal-Driven Execution)

- **先定义验证方式，再开始写代码**。

| 而不是 | 而是 |
|--------|------|
| "添加审查规则" | "新规则通过 3 步注册 + 黄金测试三路径一致。去验证。" |
| "修复 Bug" | "复现测试 FAILS → 修复后 PASSES + 无回归。去验证。" |

## 技能加载

> 以下 Skill 已注册为平台资产（`.qoder/skills/`），代理可通过平台机制自动发现和加载。
> 规范源文件保留在 `skills/` 目录，修改后需同步到 `.qoder/skills/`。

| 范围 | Skill | 内容 |
| :--- | :--- | :--- |
| 编写/审查 Python 代码 | `python` | 编码规范、陷阱 |
| 新增/修改审查规则 | `rules/rules.md` | 规则声明格式 |
| 深度审查 | `deep-code-review` | 审查 Prompt 模板 |

### 专家 Skill（重构生命周期）

| 阶段 | Skill | 触发时机 |
|------|-------|----------|
| 决策前 | `architecture-reviewer` | 新增组件/层级/依赖前 |
| 执行中 | `refactoring-guardian` | 每个 Phase 开始/结束时 |
| 执行后 | `project-plan-review` | 里程碑复盘/规划评审时 |

## 架构分层

```
7 层单向依赖：
UI/CLI → Reporter → Auditor → Engine → Converter → Model
                                    + Config 层（横切）
```

- ✅ 底层不感知上层（Model 不引用 Auditor，Engine 不引用 UI）
- ✅ CustomRulesAuditor 是"路由器"，不含检查逻辑
- ❌ 禁止反向依赖或跨层调用

## 仓库目录树

> 路由地图：所有文件路径均以此为基准。详细结构见 [project-structure.md](rules/project-structure.md)。

```
DocAudit/
├── src/                              # 源码（models / converters / engines / auditors / reporters）
├── app.py                            # Streamlit Web UI
├── tests/                            # 119 个用例（5 个层次）
├── rules/                            # 规范文档
├── skills/                           # Skill 定义
├── agents.md                         # 本文件
├── readme.md                         # 用户向功能指南
└── .gitignore
```

## 红线规则

### 1. 完全离线

- 🔴 文档不上传任何服务器
- 🔴 所有处理在本地完成，无数据上报逻辑

### 2. HTML 安全

- 🔴 报告中所有用户文本必须 `html.escape()`
- 包括：message, context, suggestion, location, source_path, title

### 3. 配置驱动

- 🔴 `rules.md` 是规则配置的唯一入口
- 不在代码中硬编码规则参数（字体列表、字号范围、关键词）
- 所有阈值从 `extract_auditor_config()` 获取

### 4. 新增 check_type 三步注册

1. Auditor 方法实现
2. `_DISPATCH` 表注册
3. `_skip_checks` 添加

> 缺一不可。遗漏 _DISPATCH → 检查不执行；遗漏 _skip_checks → 重复执行。

### 5. 文档同步

- 新增 Public 接口 → 同步 `rules/api-reference.md`
- 修改 rules.md 格式 → 同步 `rule_parser.py`

### 6. git push 前必须获得用户明确同意

## 关键设计模式

- **委托模式**：CustomRulesAuditor 通过 `_DISPATCH` 表委托到对应 Auditor
- **配置流**：rules.md → rule_parser → extract_auditor_config → Auditor
- **降级策略**：LanguageTool 不可用时跳过语法检查，不阻塞整体审查

## 测试

119 个用例，5 个层次：

| 文件 | 内容 |
|------|------|
| test_models.py | Document + AuditFinding 模型 |
| test_auditors.py | Structure + Format + Factual 审计器 |
| test_engines.py | Terminology + Vocabulary + 语言分段 |
| test_rules.py | 规则解析 + DISPATCH 验证 |
| test_integration.py | 全流水线 + 黄金测试（CLI=WebUI=Python） |

### 黄金测试

验证 3 个执行路径（CLI / Web UI / Python API）为同一输入产生完全相同的发现。

## 构建与测试

| 场景 | 命令 |
| :--- | :--- |
| 安装 | `pip install .[all]` |
| 运行测试 | `pytest tests/ -v` |
| 启动 Web UI | `streamlit run app.py` |
| CLI 审查 | `python src/cli.py report.pptx --rules rules.md` |
| DISPATCH 验证 | `python -c "from src.auditors.custom_rules import CustomRulesAuditor; print(CustomRulesAuditor.validate_dispatch())"` |

## 历史经验（从 diff 提炼）

### 高频修复模式

| 模式 | 出现次数 | 根因 |
|------|----------|------|
| DISPATCH 注册遗漏 | 3 | 新增 check 只写方法忘注册 |
| html.escape 遗漏 | 2 | 新增字段未转义 |
| 空值安全 | 4 | None 输入未守卫 |
| rules.md 格式变更未同步 parser | 2 | 新属性键无法解析 |
| PPTX EMU vs pt 单位混淆 | 2 | python-pptx 用 EMU，Document 用 pt |
| Group 子元素未递归展开 | 2 | 直接遍历 page.elements 漏检嵌套 |

### 关键设计决策

- 完全离线：Streamlit 本地运行，无网络依赖
- 配置驱动：rules.md 声明式规则，代码不硬编码
- 委托模式：CustomRulesAuditor 路由，各 Auditor 专注单一职责
- 黄金测试：三路径一致性保证

## 开发流程

### 修改前（强制）

1. **Read** 对应 Skill 文件（Skill-first）
2. 检查调用者与影响范围
3. 确认不违反红线规则

### 遇到 Bug 时

1. 写最小复现测试 → confirm: FAILS
2. 修复 → confirm: PASSES + 无回归
3. **保留复现测试**
4. 检查是否需要更新 spec / skill

### 提交前必检

- [ ] `pytest tests/ -v` 全绿
- [ ] 无裸 `except:` 或 `except Exception:` 不记录日志
- [ ] 新增 check_type 已完成 3 步注册（Auditor方法 + _DISPATCH + _skip_checks）
- [ ] 所有用户文本已 `html.escape()`
- [ ] 新增 Public 接口已同步 api-reference.md

## 防幻觉铁律

| 铁律 | 说明 |
|------|------|
| **不靠记忆引用文档** | 先 Read/Grep 确认 |
| **不确定 = 承认** | 去查 spec |
| **写过的 = 读过的** | Read 它再改 |
| **版本号是事实锚点** | 每个结论标注来源文档版本，防止误用过时信息 |

## 会话管理

### 何时自查

- **每完成一个独立功能点** — 对照四条核心准则自检
- **上下文超过 5 个文件 / 20 轮对话** — 提醒用户开新会话

### 跨会话接力

```
上一个会话结束时 → 简述：
  ✅ 已完成 / 🔜 下一步 / ⚠️ 待决策 / 📄 关键上下文
```

### 基本原则

- 新会话先读本文件 + `skills/python-SKILL.md`
- 跨会话通过 git commit 衔接
- 会话结束前将进度写入 memory，不写入本文件

## 参考

| 文档 | 角色 |
| :--- | :--- |
| [readme.md](readme.md) | 用户入口、模块速览、使用模式 |
| [api-reference.md](rules/api-reference.md) | 签名唯一信源 |
| [user-manual.md](rules/user-manual.md) | 用户手册 |
| [context.md](rules/context.md) | 术语表 |
| [project-structure.md](rules/project-structure.md) | 结构地图 |
| [documentation.md](rules/documentation.md) | 文档职责 |
| [code-review-prompt.md](rules/code-review-prompt.md) | 审查模板 |
| [deep-code-review.prompt.md](skills/deep-code-review.prompt.md) | 深度审查 Prompt |
| [refactoring-plan.md](rules/refactoring-plan.md) | 重构计划 |
