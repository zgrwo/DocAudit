# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **两轮 max level 审查（diff + 全量）修复批次**（2026-08，code-review-prompt + deep-code-review 模板）：
  - STR-003 页首标题不再误报跳级（按标题分页的 MD/DOCX 每页页首 H2/H3 曾必报假阳性）
  - TERM-003 中英混排规则降噪：纯英文页跳过 + 仅标记术语特征（全大写缩写/首字母大写词）+
    已附 (中文) 翻译的术语豁免 + 大小写敏感可配置
  - FactualAuditor 缩写扫描缓存绑定文档身份（独立模式跨文档曾串档）
  - Vocabulary 词汇表编码回退 UTF-8→GBK→replace（GBK 文件曾打穿 build_auditors）
  - STR-002 同页编号按出现次序检查（倒退不再被重排掩盖成跳号）
  - MD 列表项含竖线不再误判为表格
  - setup_offline 离线安装的 pip 升级改为 --no-index（完全离线红线）
  - min_title_font_size / FMT-008 阈值配置链打通（rules.md 声明 → parser → auditor）
  - 规则执行异常不再静默吞掉，转为 SYS-ERROR finding（UI 可见）
  - FMT-008 dedup 折叠修复：context 含行列坐标，同页同文本单元格不合并
  - STR-007 图表标题指纹对空格不敏感；PDF 转换器正路径 mock 测试补齐
  - check_api_sync 门禁扩展至全部 auditors/converters/engines（补齐 3 个缺失文档）
  - 文档数字统一：25→26 条规则、测试数 →179、format.py 检查数 →11
- 离线安装：`setup_offline` 下载步骤不再产出"装不上的 packages/" —
  显式补下载构建依赖 `setuptools` / `wheel`（`pip download` 不会保存它们，
  而离线安装本地项目必需），并新增下载后 dry-run 自检，在联网端拦截不完整包集
- 文档数字漂移：CHANGELOG 测试用例数 53 → 181（实际 12 个测试文件）
- dependabot 锁文件 bump 引入的版本约束冲突已回退：
  pyarrow 25（streamlit 要求 <25）、typer 0.27（docling-core 要求 <0.27）、
  starlette 1.6（streamlit 要求 <1.4）、pydantic-core 2.48（pydantic 精确钉死 2.46.4）、
  mpmath 1.4（sympy 要求 <1.4）——保留 docling-parse/docling-ibm-models/
  mail-parser/marko/typing-inspection 五个合法 bump

### Added

- **FMT-008 表格文字与底色对比度规则**：深色底色配浅色文字、浅色底色配深色文字
  （WCAG AA，正文 4.5:1 / 大字 3:1，阈值经 rules.md 配置）；覆盖 PPTX/DOCX 原生表格，
  仅对 solid 纯色底色判定，无填充/渐变/主题色/嵌入 Excel 降级跳过不误报；
  `TableCell` 新增 `fill_color` / `font_color` 字段，新增 `tests/test_contrast.py`（17 用例）
- 锁定文件 `requirements-core.txt` / `requirements-pdf.txt` / `requirements-full.txt`
  （由 `scripts/gen_requirements_lock.py` 生成），下载步骤按锁文件解析，版本可复现
- `tools/check_bare_handlers.py`：AST 感知的裸异常处理器检查（CI 强制），
  既有 14 处刻意降级路径已附 `# bare-handler-ok` 理由注释
- `tests/test_scripts.py` 与 `tests/test_check_bare_handlers.py`：脚本与门禁工具测试
- `rules/tooling-pitfalls.md`、`rules/falsy-pitfalls.md`：工具与 falsy 陷阱清单
- CI：Python 3.14 加入矩阵；裸异常处理器检查步骤；锁文件解析门禁
  （windows-latest job，`pip install --dry-run --ignore-installed -r requirements-*.txt .`，
  防 dependabot 冲突 pin 合入；锁文件为 Windows 生成契约，见 tooling-pitfalls #6b-6d）
- 项目宪法由 `agents.md` 更名为 `AGENTS.md`（2026 跨工具标准），附 `CLAUDE.md` 兼容副本
- 依赖自动更新配置（dependabot）与 docs/refactor 两类 Issue 模板

## [0.1.0] - 2026-07-26

### Added

- 完整四维审查系统：结构审查、格式审查、语言审查、事实审查
- CustomRulesAuditor 自定义规则引擎（委托模式 + regex 匹配）
- 25 条配置驱动审查规则（rules.md 声明式）
- PPTX/DOCX/PDF/Markdown 四格式转换器
- Streamlit Web UI（单文件 + 批量审查 + 过滤豁免）
- CLI 命令行（单文件/批量 + --fix 自动修复 + 报告导出）
- HTML/JSON 双格式报告输出
- LanguageTool 三层降级（Docker → Java → Python 内置）
- 半导体术语表（3 本 YAML，45+ 术语）
- 词汇白名单/黑名单（accept.txt + reject.txt）
- AutoFixer 自动修复（字体/字号/间距/溢出/标点/项目符号）
- 黄金测试：CLI = WebUI = Python API 三路径结果一致
- 119 个测试用例（模型/审计器/引擎/规则/集成）

<!-- [0.1.0]: https://github.com/zgrwo/DocAudit/releases/tag/v0.1.0 -->
