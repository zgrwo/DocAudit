# DocAudit &#8212; 本地离线文档审查系统

面向半导体行业团队的文档质量审查工具。支持 **PPTX / DOCX / PDF / Markdown** 四种格式，覆盖 **内容结构、格式规范、语言文字、事实精准** 四大审查维度，提供 Web UI 和命令行两种使用方式。

完全本地离线运行，无需联网。

---

## 何时使用本项目

当你需要在半导体团队中完成以下文档质量把关时：

- **技术评审 PPT** &#8212; 检查字体/字号/版式是否规范、标题层级是否递进
- **DOE 实验报告** &#8212; 检查图表编号是否连续、术语是否规范
- **工艺整合报告 (PIR)** &#8212; 检查数值跨页一致性、缩写是否首次定义
- **良率分析报告** &#8212; 检查文本密度、元素溢出、中英混排格式
- **项目批量交付** &#8212; 一键审查整个文件夹，输出合规报告
- **新手工程师文档** &#8212; 审查规则作为团队标准，帮助新人养成规范写作习惯

---

## 核心能力

### 四维审查

| 维度 | 检查内容 | 示例 |
|------|----------|------|
| &#128202; **内容结构** | 标题页检测、标题层级递进、图表编号连续、必含章节、重复标题、每页结论 | "缺少概述章节"、"图3跳过了图2" |
| &#127912; **格式规范** | 字体一致性 (Run级)、字号范围、对齐、元素溢出、段落长度、单页文本密度 | "非标准字体 +mj-lt"、"单页932字超限" |
| &#128221; **语言文字** | 语法拼写 (LanguageTool)、中英混排、半导体术语一致性、禁用词 | "TSV首次未标注全称"、"中英文间缺空格" |
| &#128300; **事实精准** | 数值跨页一致性、缩写定义管理、重复定义检测 | "良率95.3%在第3页为95.8%" |

### 亮点

- **完全离线** &#8212; 文档不上传任何服务器，工艺数据安全
- **配置驱动** &#8212; 通过 `rules.md` 调整审查规则，无需改代码
- **自定义规则引擎** &#8212; 支持正则匹配 + 检查委托两种模式
- **LanguageTool 三层降级** &#8212; Docker &#8594; Java 子进程 &#8594; Python 内置，零依赖也能跑
- **智能术语检查** &#8212; 3 本半导体术语表 (45+ 术语)，含自动跳过去重
- **批量审查** &#8212; 支持文件夹 + 多文件拖拽，按文件汇总
- **灵活豁免** &#8212; 规则/页面/类型/单条，四个层级豁免
- **自动修复** &#8212; 字体标准化、字号修正、中英文间距、元素溢出、标题标点、项目符号

---

## 快速开始

**三条路径，选一条即可：**

| 方案 | 适合 | 操作 |
|------|------|------|
| **&#128421;&#65039; 方案 A：一键启动** | 只想上传文档看审查结果，不关心 Python | 双击脚本 &#8594; 自动打开浏览器 |
| **&#9000;&#65039; 方案 B：手动安装** | 需要自定义参数、集成到已有项目 | pip install &#8594; 命令行启动 |
| **&#128230; 方案 C：离线安装** | 无互联网环境（内网/保密车间） | 有网机器下载 &#8594; 拷贝 &#8594; 本地安装 |

---

### &#128421;&#65039; 方案 A：一键启动（零门槛，推荐）

1. 下载并解压本项目
2. **Windows**：双击 `scripts/run.bat`
3. **macOS / Linux**：双击 `scripts/run.sh`（或 `bash scripts/run.sh`）

脚本自动完成所有配置（首次约 1-3 分钟），浏览器自动打开 `http://127.0.0.1:8501`。  
之后每次双击秒启动。

> 你只需要：**上传文档 &#8594; 点击审查 &#8594; 查看结果**。

---

### &#9000;&#65039; 方案 B：手动安装（灵活定制）

#### 环境要求

- Python &#8805; 3.10
- Windows / macOS / Linux
- (可选) Docker &#8212; LanguageTool 完整英文语法检查
- (可选) Java &#8212; LanguageTool 自动启动模式

#### 安装

```bash
# 创建虚拟环境
python -m venv .venv

# 安装 DocAudit（核心依赖 + PDF + 开发工具）
.venv\Scripts\pip install .[all]
# (Linux/macOS: .venv/bin/pip install .[all])

# (可选) LanguageTool 完整语法检查
docker-compose up -d                    # &#8594; http://localhost:8010
```

#### 可选依赖组

| 安装命令 | 包含 | 适用场景 |
|---------|------|---------|
| `pip install .` | streamlit, python-pptx, python-docx, pyyaml, requests, pyspellchecker | PPTX/DOCX/MD 审查 |
| `pip install .[pdf]` | 基础 + docling, pandas | + PDF 审查 |
| `pip install .[dev]` | 基础 + pytest, pytest-cov, ruff | 运行测试 / 代码检查 |
| `pip install .[all]` | 基础 + pdf + dev | 完整功能（推荐） |

> &#128161; **开发模式**：如需修改源码，加 `-e`（`pip install -e .[all]`），修改即时生效。

#### 启动

```bash
# Web UI
.venv\Scripts\streamlit run app.py      # &#8594; http://localhost:8501

# CLI 审查
.venv\Scripts\python src/cli.py 文档.pptx
```

---

### &#128230; 方案 C：离线安装（无互联网环境）

适用于内网、保密车间等无法连接 PyPI 的场景。一次下载，反复使用。

**第 1 步：在有网机器上下载依赖**

```bash
# Windows
scripts\setup_offline.bat download           # 核心依赖
scripts\setup_offline.bat download pdf       # 含 PDF 支持
scripts\setup_offline.bat download full      # 含 PDF + 开发工具

# macOS / Linux
bash scripts/setup_offline.sh download
bash scripts/setup_offline.sh download pdf
bash scripts/setup_offline.sh download full
```

下载脚本自动执行三步：

1. **按锁文件下载运行时依赖**（`requirements-core.txt` / `requirements-pdf.txt` / `requirements-full.txt`，版本钉死、跨机器可复现；锁文件由 `scripts/gen_requirements_lock.py` 生成，修改 `pyproject.toml` 后需重新生成）
2. **补下载构建依赖 `setuptools` / `wheel`** — `pip download` 不会保存它们，而离线安装本地项目（PEP 517 构建）必需
3. **离线自检** — 自动执行 `pip install --dry-run --ignore-installed --no-index --find-links=packages/`，若 packages/ 不完整会当场报错，避免把装不上的包拷贝到离线机器

> &#9888;&#65039; 个别依赖只提供源码包（sdist，如 `antlr4-python3-runtime`），下载后以 `.tar.gz` 形式存在于 packages/，离线安装时由 setuptools 现场构建，属正常现象。
>
> &#9888;&#65039; **packages/ 必须与锁文件一致**：若 `pyproject.toml` / `requirements-*.txt` 有更新（或 packages/ 来自旧版本），请**重新执行 download** 后再拷贝——下载步骤的"离线自检"会直接拦截不一致，避免把装不上的包带到离线机。

**第 2 步：拷贝到离线机器**

将整个项目文件夹（含 `packages/`）复制到离线机器。

**第 3 步：离线安装**

```bash
# Windows
scripts\setup_offline.bat install            # 安装到 .venv 虚拟环境

# macOS / Linux
bash scripts/setup_offline.sh install
```

脚本自动执行：
1. 创建 `.venv` 虚拟环境
2. `pip install --no-index --find-links=./packages/` &#8212; 从本地安装全部依赖
3. 验证核心模块导入

全程零网络请求，`packages/` 文件夹可重复用于多台机器。

> &#9888;&#65039; **Python 版本注意**：下载的 `.whl` 与下载时的 Python 版本和平台绑定。离线安装的机器必须使用相同的 Python 版本（如 3.12）和操作系统。
>
> &#9888;&#65039; **锁文件平台绑定**：`requirements-*.txt` 为 Windows 生成（含 `pywin32` 等平台专属依赖，`antlr4-python3-runtime` 仅 sdist）。macOS / Linux 用户请在目标平台运行 `python scripts/gen_requirements_lock.py` 重新生成后再下载。

---

## 如何使用

### Web UI

1. 浏览器打开 `http://localhost:8501`
2. **&#128196; 单文件** 模式：拖拽文件 &#8594; 点击审查 &#8594; 查看结果 &#8594; 过滤豁免 &#8594; 下载报告
3. **&#128194; 批量** 模式：输入文件夹路径 / 拖拽多个文件 &#8594; 批量审查 &#8594; 按文件汇总

> 详细操作 &#8594; [用户手册](rules/user-manual.md)

### CLI

```bash
# 单文件审查
python src/cli.py report.pptx

# 审查 + 导出 HTML
python src/cli.py report.pptx -o report.html

# 批量审查目录
python src/cli.py docs/ -o batch_report.html

# 审查 + 自动修复
python src/cli.py report.pptx --fix

# 仅修复字体
python src/cli.py report.pptx --fix --fix-type font
```

> 完整参数 &#8594; [用户手册](rules/user-manual.md)
>
> **退出码**（markdownlint 风格，便于 CI 集成）：发现 ERROR 级问题 → `1`；仅有 warning/info → `0`；任一文件处理失败（解析/转换异常，优先于严重度判断）→ `1`；路径不存在或目录中无支持文件 → `1`。

### Python API

```python
from src.cli import audit_file

doc, findings = audit_file("report.pptx", rules_path="rules.md", glossary_dir="glossary")
for f in findings:
    print(f.severity.value, f.message, f.location)
```

---

## 规则速览

共 26 条审查规则，分 4 个类别，全部通过 `rules.md` 配置：

| 类别 | 规则 | 示例 |
|------|------|------|
| **结构** (8条) | STR-001~008 | 标题页、编号连续、层级递进、标题长度/重复/标点、图表格式、结构一致性 |
| **格式** (8条) | FMT-001~008 | 字体、字号、文本密度、段落长度、溢出、占位符、项目符号、表格对比度 |
| **术语** (3条) | TERM-001~003 | 先进封装术语、硅通孔术语、中英混排 (regex 驱动) |
| **内容** (7条) | CON-001~004 + 子规则 | 数值一致性、必含章节、缩写定义 + 生命周期管理、每页结论 |

> 所有规则定义 &#8594; [rules.md](rules.md) &nbsp;|&nbsp; 规则对应检查方法 &#8594; [API 参考](rules/api-reference.md)

---

## 架构特点

```
UI/CLI &#8594; Reporter &#8594; Auditor &#8594; Engine &#8594; Converter &#8594; Model
                                    + Config 层（横切）
```

- **7 层单向依赖**：底层不感知上层，每一层可独立替换
- **委托模式**：CustomRulesAuditor 通过 `_DISPATCH` 表路由到对应 Auditor
- **配置驱动**：`rules.md` &#8594; rule_parser &#8594; extract_auditor_config &#8594; Auditor
- **黄金测试**：CLI = Web UI = Python API 三路径一致

---

## 错误处理

- **LanguageTool 不可用**：自动跳过语法检查，不阻塞整体审查
- **文件格式不支持**：返回明确的格式错误，列出支持的格式
- **大文件超时**：可配置的处理超时，保护内存

---

## 安全

- &#128308; **完全离线**：文档不上传任何服务器，所有处理在本地完成
- &#128308; **HTML 转义**：报告中所有用户文本必须 `html.escape()`
- **路径限定**：文件路径限定在用户指定目录
- **无数据上报**：代码中不存在任何网络请求

---

## 质量保证

- **328 个测试用例**：models / auditors / engines / rules / integration / golden paths / scripts / gates
- **真实三路径黄金测试**：Python API = 真实 CLI subprocess = Web UI (AppTest) 结果完全一致
- **DISPATCH 验证**：自动化检查 `_DISPATCH` 与 `_skip_checks` 完整性
- **裸异常处理器检查**：CI 强制无 `except Exception: pass` 静默吞异常（`tools/check_bare_handlers.py`）
- **技能双份同步检查**：skills/ 与 .qoder/skills/ 注册副本正文一致性门禁（`tools/check_skill_sync.py`）

---

## 已知限制

- **在线语法检查**：LanguageTool 需连接本地 Java 服务（不可用时可跳过）
- **大文件处理**：>100 MB 的 PPTX/DOCX 需要较多内存
- **PDF 格式**：仅支持文本型 PDF，扫描版需 OCR 预处理
- **PDF 转换依赖 docling 本地完整安装**：docling 未安装或其本地数据文件（如 docling-parse 依赖）不完整时报错，需完整安装 `[pdf]` 依赖组
- **Windows 上 pytest 清理临时目录偶发权限错误**：会话结束时清理 `%TEMP%` 下 pytest symlink 偶发 PermissionError，属环境性噪音，不影响测试结果

---

## 贡献

请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 了解贡献流程（fork &#8594; PR &#8594; review）。

---

## 许可证

[MIT](LICENSE) &copy; zgrwo

---

## 测试命令

```bash
# 运行所有测试
pytest tests/ -v

# DISPATCH 完整性验证
python -c "from src.auditors.custom_rules import CustomRulesAuditor; print(CustomRulesAuditor.validate_dispatch())"

# 单文件审查
python src/cli.py tests/fixtures/sample.pptx --rules rules.md
```

---

## 文档索引

| 文档 | 角色 | 内容 |
|------|------|------|
| [API 参考](rules/api-reference.md) | 数字唯一信源 | 函数签名、参数说明 |
| [用户手册](rules/user-manual.md) | 学习教程 | 每个功能详细示例 + 结果解读 |
| [context.md](rules/context.md) | 术语表 | 所有领域术语唯一定义 |
| [project-structure.md](rules/project-structure.md) | 结构地图 | 文件职责与层级关系 |
| [AGENTS.md](AGENTS.md) | 项目宪法 | 架构分层、红线规则、开发流程 |
| [rules.md](rules.md) | 人+AI | 审查规则声明 |

---

## 治理体系说明

本项目遵循 [Harmonization 治理规范](https://github.com/zgrwo/Harmonization) 模板体系：

| 文件 | 面向 | 职责 |
|------|------|------|
| `AGENTS.md` | AI 编程助手 | 项目宪法——架构、红线、编码准则、防幻觉铁律 |
| `README.md` | 人类用户 | 功能指南——安装、模块速览、使用模式（本文件） |
| `rules/` | AI + 人类 | 规范文档——API 参考、用户手册、术语表、审查模板 |
| `skills/` | AI 编码 | 技能定义——语言陷阱、编码模式、重构守则 |

**核心原则**：SSOT（信息只在一处定义）、Skill-first（修改代码前加载技能）、四条核心准则。

<!-- last_updated: 2026-08-18 -->
