# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-11-05

5S 清理 + 审查修正版（不改变审查语义：清理死代码/错位目录/悬挂配置，补文档链接门禁）。
**736 个测试用例（23 个文件）**；新增 1 条链接完整性门禁。

### 整理 / 整顿（5S）

- **离线包目录归位** —— `scripts/packages/`（391MB 旧下载缓存，与文档声明的根 `packages/` 不符）
  迁移到根 `packages/`；`common.packages_dir()` 直接命中新位置，旧位置兼容逻辑保留。
- **删除死代码** —— `text_utils.masked_spans()`、`exemptions._extract_keys()`：重构后全仓库零引用
  （含文档），按 5S 移除；api-reference 同步删除对应条目。
- **删除未接入配置** —— `styles/custom/*.yml` + `.vale.ini`：Vale 未接入 CI 且无任何引用
  （git 历史可恢复）；project-structure 目录树同步。
- **历史文档归档** —— `handoff-2026-10-29.md`、`remediation-plan-2026-08.md` 移入
  `docs/governance/archive/`，新增归档 README 与索引；结构树/释放清单链接同步。
- **工具归位** —— `tests/fixtures/gen_sample_pdf.py` → `scripts/gen_sample_pdf.py`（fixture 只放数据）。
- **生成物清扫** —— 删除 `build/`、`docaudit.egg-info/`、全部 `__pycache__/`、`.pytest_cache/`、
  `.ruff_cache/`、`.coverage`；`git status --ignored` 仅剩 `.venv/ packages/ logs/`。

### Fixed

- **生成器路径回归** —— 移动后 `OUTPUT` 仍是 `Path(__file__).parent / "sample.pdf"`，会把
  `sample.pdf` 写到 `scripts/`；改为 `tests/fixtures/sample.pdf`（实测重生成后 git 无 diff）。
- **PR 模板悬挂链接** —— `.github/PULL_REQUEST_TEMPLATE.md` 中 `README.md` / `CHANGELOG.md`
  相对 `.github/` 解析失败；改为 `../README.md` / `../CHANGELOG.md`（全库 75 条链接 0 悬挂）。

### Added

- **文档链接门禁** —— `tests/test_gates.py::test_docs_links_gate`：扫描全库 Markdown 相对链接，
  移动/归档/删除文件后悬挂链接会 FAIL；负向注入（改坏 `docs/README.md` 一条链接）实测 FAIL→复原 PASS。
- **5S 例行清单** —— `docs/governance/release-checklist.md` §4.1（整理/整顿/清扫/清洁/素养 + 检查命令 +
  历史教训），作为每次发行前的固定动作。
## [0.3.0] - 2026-11-05

产品能力增强版（在 0.2.2 深度审查修复之上）：把"发现列表"升级为"可解释的质量评估"，
补 4 条内容级规则，并给批量/版本对比/配置治理加能力。**735 个测试用例（23 个文件）**；
80 条新回归用例，全部规则经 `rules validate` / `validate_dispatch()` / 门禁校验。

### Added

- **质量分（`src/engines/scoring.py`）** —— `compute_score()` 输出 0-100 分 + A/B/C/D 等级 +
  分维度子分；罚分 = Σ(严重度权重 × 条数) / 页数（满分罚分 20）；`SYS-ERROR` 不计罚分、
  单独统计；估算类发现（溢出/表格 fit/DPI，`metadata.estimated`）半权。HTML 头部质量分卡、
  JSON `score`、CLI `[SCORE]`、SARIF `run.properties.docAuditScore` 全链路展示。
- **审查范围/降级声明（`src/engines/coverage.py`）** —— `collect_coverage()` 输出语言检查
  后端层级、无版面几何/字体元数据、PPTX 专属检查未执行清单、执行失败的审计器、估算类
  发现计数；HTML「审查范围与可信度」区块 + CLI `[COVERAGE]` + JSON `coverage`
  + SARIF `docAuditCoverageComplete`。首次让"没问题"与"没查"可区分。
- **4 条内容级规则（26 → 30 条）** —— STR-009 图表须被正文引用、CON-005 结论须有量化支撑、
  CON-006 必含章节须有实体内容、CON-007 量词语境数值须带单位；`CHECK_REGISTRY` 19 → 23 条。
  只判断"信息是否给全"，不做语义评价；默认 info/warning，可按规则关闭。
- **全局阈值配置化** —— `rules.md` frontmatter `parameters:` 暴露 16 项原硬编码阈值
  （对齐容差/字体种类上限/近似重复页/结论门槛/表格行高列宽与内边距/文本溢出/图片 DPI/
  CON-001 长度单位/缩写豁免词）；`parse_rules_globals()` 解析、`rules validate` 校验未知键
  与类型/范围，运行时非法值告警回退默认。
- **配置装配 SSOT（`src/engines/auditor_config.py`）** —— `build_auditor_configs()` 统一
  `pipeline.build_auditors` 与 `CustomRulesAuditor` 回退路径的配置键集，消除两份手工 dict
  漂移（特检 #4 同族风险）。
- **批量跨文档一致性（`src/engines/batch.py`）** —— 目录审查时比对同一缩写全称（BATCH-TERM）
  与必含章节覆盖（BATCH-SECTION），输出 `[BATCH-CONSISTENCY]` 段并计入报告/退出码。
- **版本对比（`src/engines/baseline.py`）** —— `--baseline old.json` 输出「已修复 / 新引入 /
  仍存在」，按稳定 `exemption_key` 对齐（JSON 报告新增 `findings[].key`）；`--fail-on-new`
  把新引入 error 变成 CI 阻断。
- **规则 profile（`src/engines/profiles.py`）** —— `--profile strict|standard|relaxed`
  预设退出码阈值与报告最低严重度（relaxed 隐藏 info），`--fail-on` 显式覆盖。
- **豁免生命周期（`.docauditignore`）** —— 条目支持 `created` / `reviewer` / `expires`；
  过期条目自动失效，`exemption_stats()` 统计并在 CLI 提示复查。
- **Windows CI job** —— `.github/workflows/ci.yml` 新增 windows-latest 快测（`-m "not slow"`）
  + 中文控制台配置校验 + 真实样例 CLI 冒烟（退出码/报告落盘），覆盖"只在 Windows 复现"的坑。

### Changed

- **报告器签名扩展（向后兼容）** —— `generate_html_report` / `generate_json_report` /
  `generate_sarif_report` 新增 keyword-only `score=` / `coverage=`；不传时输出与 0.2.2 一致。
- **CLI** —— `audit_document()` 新增（返回 context），`audit_file()` 保留为兼容包装；
  新增 `--profile` / `--baseline` / `--fail-on-new`；`--fail-on` 默认改为"按 profile"。
- **`extract_auditor_config(rules, globals_=None)`** —— 第二参数可选，向后兼容。
- **规则数 26 → 30**：`rules.md` / README / AGENTS / CLAUDE / api-reference / specification /
  ai-review-prompt / ci.yml 断言 / test_rules / test_validation 全链路同步；
  `--profile` 与规则参数文档补入用户手册。

### Fixed（同轮 max-level 审查，见 `docs/governance/ai-review-prompt.md`）

- **P1 STR-009 页码越界** —— `_check_figure_referenced` 用 `doc.pages[page.index]` 反查标签，
  页面 index 非连续时 `IndexError`（且标签可能错页）；改用遍历时的 page 对象与 `slide_number`。
- **P2 CON-006 表格章节误报** —— 非 PPTX 路径只统计段落，章节内只有表格/图片时被判"缺少实体内容"；
  改为把章节区间内 table/image/chart 计为实体内容。
- **P2 BATCH-TERM 前缀误报** —— 中文全称捕获会把"本方案采用/基于"等前缀吞入全称，同一术语
  因前缀不同被判"全称不一致"；新增归一化（剥离前缀/取"的"后本体/后缀兼容视为同一名称）。
- **P2 BATCH-SECTION 目录误判** —— 旧实现用全文子串，目录行"目录：概述 工艺流程 结论"被当成
  三个章节都存在（假阴性）；改为标题/heading 优先，无标题文档只认"独立成行"的章节名。
- **P2 Coverage 后端失真** —— 语言后端未探测（`backend=None`）时被写成"纯 Python 降级"；
  改为如实区分「尚未探测 / 不可用 / 未执行」，不再冒充 tier-3。
- **P2 旧版报告 baseline 失效** —— 0.2.x JSON 无 `key` 字段时回退重算漏了 `context`
  （dedup_key 含 context 哈希）→ 整份报告被误判"新引入"；回退补齐 context/location/message
  的 None 归一化后与当前键完全对齐。
- **P2 非法 frontmatter YAML 静默** —— `rules validate` 不检查 frontmatter 语法，`parameters:`
  写坏时全局阈值静默回退默认值；现显式报错（`frontmatter YAML 无法解析`）。
- **P3 `--fail-on-new` 空生效** —— 缺 `--baseline` 时静默 no-op；现输出警告。
- **P3 profile 口径不透明** —— `relaxed` 隐藏 info 后分数/报告按可见发现计算但无提示；
  CLI 增加 `[PROFILE]` 说明行，用户手册同步。
- **P3 文档回归** —— `specification.md` CON-005~007 三行表格被压成一行；`release-checklist`
  版本行被全局替换污染为"0.3.0（2026-10-30，第二轮修复版）"；api-reference「数据类」表混入常量；
  `scoring.py` docstring 声称 `score_penalty_cap` 可配置（实际未接入）。
- **P3 测试质量** —— `test_unknown_profile...` 的 `in (0, 1)` 零信息断言改为精确断言；
  `test_integration` 的 `PROJECT_ROOT` 从文件尾移到顶部；批量 context 的 `complete` 反映转换失败。

### 未做项（评估结论）

- **包名 `src` → `docaudit` 重构**：BREAKING（所有 import、CLI 路径、文档示例、第三方
  脚本均需改），当前无功能收益；实施需独立 PR + 兼容 shim，不建议与功能迭代混做。
- **`src/cli.py`（807 行）/ `app.py`（1011 行）拆分**：拆分本身不改变行为，但会打断
  `test_golden_paths` 的三路径锚点与既有覆盖率基线；建议在质量分/内容规则稳定后单独进行。
- **本地 LLM 语义评审**：需要 GB 级模型与推理运行时，与"完全离线、零上报、轻依赖"红线
  冲突，需产品决策；当前以"结构化内容检查"作为折中。

## [0.2.2] - 2026-10-30

第二轮全面深度审查修复版（P1 ×7 / P2 ×11 / P3 若干，含假阴性、假阳性、离线流程与文档漂移）。
**655 个测试用例（23 个文件）**；27 条新回归用例锚定本轮全部代码修复，另修正 7 处空转断言。

### Fixed

- **P1 缩写重复定义跨页漏报（CON-003-B）** —— `definition_count` 只用页内字符偏移去重，两页在
  同偏移各定义一次（模板句）被判为"同一定义站点" → 静默漏报。改为 `(页码, 页内偏移)` 二元组。
- **P1 定义后未再使用漏报（CON-003-A）** —— 旧实现用 `total_count` 比去重站点数，
  `TSV (硅通孔 TSV)` total=2 > def=1 → 永不报。改为统计"定义站点之外的出现次数"。
- **P1 中文推荐术语被误报** —— `_already_preferred` 对含汉字的 preferred 用 `\b`（汉字属 `\w`，
  「采用微凸块」无词边界）→ 已按推荐写法书写的文档报"术语不规范"。汉字词改子串匹配。
- **P1 Web UI 豁免基线失效** —— `_reset_batch_state()` 把启动时从 `.docauditignore` 载入的豁免
  置空 → 每次审查后团队基线失效，"保存豁免"还会用空基线覆写。改为重新从文件载入。
- **P1 Markdown 围栏代码块被切断** —— 分页 `re.split(r"\n(?=(#{1,3})\s)")` 把代码块内的 `#` 注释
  行当标题：代码块跨页、注释行变成标题元素、后半段失去掩码保护（`--flag` 被报 PUNCT-007、
  代码标识符被报拼写错误）。分页改为围栏感知（`_split_pages_outside_fences`）。
- **P1 离线依赖缓存位置与说明不符** —— wheel 下到 `scripts/packages/`，而 README/脚本提示"复制到
  项目根 `packages/`"、HF 模型缓存在 `<项目根>/packages/hf_cache`。统一到项目根（旧位置自动沿用），
  `gen_requirements_lock.py` 改用 `common.packages_dir()` 单一真相，`setup_offline.sh` 同步语义。
- **P1 LanguageTool 段缓存跨文档泄漏** —— `_lt_segment_cache` 挂在审计器实例上，而 Web UI 用
  `@st.cache_resource` 复用实例 → 第二份文档里与第一份相同的英文段不再送检，LanguageTool 结果
  被静默吞掉（实测同文本第二份 0 请求）。改为 `audit()` 开始时按文档重置缓存。
- **P2 代码/URL/结构语法参与语言检查** —— 拼写（PY-SPELL）、中英混排（FMT-MIXED-001~003）、
  中文基础模式（PY-ZH-GRAMMAR）未掩码行内代码/围栏代码/URL。README 自审 96 条拼写命中中
  50 条来自代码/URL。掩码逻辑收敛到 `src/text_utils.py`（等长空格、位置不变）并补 Markdown
  分隔线 `---`、HTML 注释、行内代码；拼写/混排/中文模式统一使用。
- **P2 "括号内即定义"启发式误判** —— `（核心依赖 + PDF + 开发工具）` 让 PDF 被当成已定义 →
  CON-003 漏报、CON-003-A 假阳性（README 实测 19 处"定义"中 5 处误判）。括号内出现仅当缩写
  是括号内容最后一个 token 时才算 `全称 (ABBR)` 定义；同时补上全角括号
  `TSV（硅通孔）` 的定义识别（旧实现只认半角）。
- **P2 文件名/路径片段被当缩写** —— `AGENTS.md`、`MANIFEST.in`、`src/CHANGELOG` 曾被报 CON-003。
  文件名（`.md/.in/...` 扩展名）与路径片段不再进入缩写扫描。
- **P2 代码块内容进入事实/术语/图号检查** —— CON-001 数值、CON-003 缩写、TERM 正则规则、
  STR-002/STR-007 图号与图题原先把代码块/URL 内容当正文；现统一先掩码（位置不变）。
- **P2 Markdown 列表块被当成一个段落** —— `_make_element` 把整个列表块塞进一个 Paragraph
  （`\n` 连接）→ FMT-004 误报"段落过长"、FMT-007 / TXT-BULLET-PUNCT 只看得到首项。
  列表项逐条拆 Paragraph，与 PPTX"每个项目符号一个段落"语义对齐；FMT-004 另加围栏代码块豁免。
- **P2 版式复用检查只认中文版式** —— `_check_layout_consistency` 用 `"标题" in name` 字面判断，
  英文模板（"Title Slide"）完全不检查。提取 `src/auditors/base.py::is_cover_layout`（CON-004 与
  FormatAuditor 共用），`exempt_layouts` 经 `build_auditors` / `_create_auditor` 双路径注入。
- **P2 DOCX 合并单元格重复产出** —— python-docx 对横向合并的每个网格位返回同一 `w:tc`、纵向合并
  续行返回起始格 → 同一单元格审两次、colspan/rowspan 恒 1（FMT-TABLE-FIT 按单列宽估算合并表头
  → 误报列宽不足）。按 `w:tc` 元素去重并统计 span；行分组改用 `range(nrows)` 与行高数组对齐（PPTX 同改）。
- **P2 DOCX 页眉/页脚表格文本漏检** —— `header.paragraphs` 不含表格内文字，表单类页眉整块漏检；
  现同时提取页眉/页脚表格单元格文本。
- **P2 拼写检查顺序不确定** —— `spell.unknown()` 返回 set，直接遍历使 PY-SPELL 报告顺序随哈希
  种子漂移；改为 `sorted()`（确定性回归此前只比集合，未发现）。
- **P2 版式检查 finding 被去重折叠** —— `_check_layout_consistency` 的 finding 无 rule_id/页码/context
  → `dedup_key` 碰撞，多个标题版式只剩一条。补 context（版式名 + 次数）。
- **P2 CON-003-C 同页文案自相矛盾** —— 同页后文才定义时输出"在第 N 页使用，但在第 N 页才给出定义"，
  改为"同页后文才给出定义"。
- **P2 文档与代码漂移** —— glossary 45+→40（actual 19+4+17）、`general_tech` 9→4、Engine 8→9、
  api-reference 总模块 28→29 并补 `_check_table_fit`、6 个 LanguageAuditor 检查行与
  `BaseAuditor`/`is_cover_layout` 章节、`build_auditors` 默认参数、skills 目录树缺
  `rules.md`/`deep-code-review.md`、tooling-pitfalls 仍引用已删除的 `tools/check_bare_handlers.py`、
  AI 审查模板退出码说明（路径不存在 = 1）、user-manual 的 `_DISPATCH` 注册说明改为
  `CHECK_REGISTRY`、`.ppt`/`.doc` 标注为不支持。
- **P2 测试断言空转** —— CON-003 常见词用例读取从不写入的 `metadata["abbreviation"]`（恒真）、
  dispatch 异常用例 `or "模拟 dispatch" in message`（恒真）、`code in (0, 1)`、
  `isinstance(findings, list)`、`len(zh) >= 1`、确定性回归只比 `sorted()`（抹平顺序漂移）、
  docling label 只测 str 分支（`label.value` 从未执行）。已改为有效约束并补枚举分支用例。
- **P3 死代码/契约文案** —— `_matches_to_findings` 末尾重复 `return findings`；
  `_try_java` 超时分支读取 `stderr=DEVNULL` 的 `stderr`（死代码）；`_check_python` 中
  `len(word) <= 3 or isdigit()` 永假；`Paragraph.level` 注释称 MD 为 0-based（实际 1-based）；
  内置语言检查规则 ID 表补 VOCAB-REJECT。

### Changed

- `vocab/accept.txt` 增补工具链/技术写作术语（docling、streamlit、pymupdf、frontmatter、noqa、
  dedup 等 49 条），抑制 pyspellchecker 词典缺口导致的假拼写错误；这些词同样不再被
  CON-003/TERM-003 误判。
- 审查门禁 `test_gates.py`：`src/auditors/base.py` 纳入 API 同步检查（公开接口须在 api-reference
  有条目 + 形参一致）。

## [0.2.1] - 2026-10-29

深度审查修复版（P0 ×1 / P1 ×8，含发行红线与静默失效）。**627 个测试用例（23 个文件）**，
覆盖率 **88%**；新增回归用例覆盖全部修复点。

### Fixed

- **P0 离线红线：PDF 首次转换仍会联网** —— `HF_HUB_OFFLINE`/`HF_HUB_CACHE` 是 huggingface_hub
  的**导入期常量**，旧实现先 import docling 再注入环境变量，两个常量已被冻结为用户默认值；
  `packages/hf_cache` 预下载模型因此不生效。现在在 `pdf_converter` 模块导入时即注入，
  `scripts/run.py`/`run.sh` 也在拉起 Streamlit 前下发变量；子进程实测 `HF_HUB_CACHE` 已指向项目缓存。
- **P1 豁免键跨文件碰撞** —— `exemption_key` 现纳入来源文件（basename），批量下两文件的同类发现
  不再共用键；Web UI 不再改写 location（改由显示层拼来源），UI/CLI 计算同一函数、语义一致。
- **P1 豁免文件编码** —— `.docauditignore` 读取增加 utf-8-sig → gbk → replace 回退，
  GBK/带 BOM 文件不再抛未捕获 `UnicodeDecodeError`（CLI 零报告崩溃）或被当损坏后静默失效；
  `save_exemptions` 返回 bool，Web UI 保存失败会显示错误而非「已保存」。
- **P1 CSV 落盘换行** —— Windows 文本模式把 `\r\n` 再翻译为 `\r\r\n`，落盘 CSV 出现空记录；
  改为二进制写入（`write_bytes`），回读行数 = 发现数 + 1。
- **P1 文档级标点检查在中文紧邻数字时失效** —— PUNCT-008/009/010 的 `\b`/`\w` 边界在汉字旁不成立：
  `自2026-10-29起` 漏报日期格式混用、日期连字符被误报范围混用、`厚度为10mm` 漏报单位空格混用。
  改为 `(?<!\d)`/`(?<![0-9A-Za-z_.])` 边界并扩大日期掩码。
- **P1 CON-002 多章节缺失被去重折叠** —— 多个缺失章节的 finding 现带 `context`（章节名），
  4 条缺失 → 4 条报告，不再只留第一条。
- **P1 DOCX 内容控件（SDT）文本被静默丢弃** —— 旧实现用 `para_map` 查 SDT 内段落（`Document.paragraphs`
  不含），改为 `Paragraph/Table(item, doc)` 包装并递归处理嵌套 SDT。
- **P1 配置校验放行 5 类参数错误** —— parser 不再把非法「最大字数」静默改写为 200；
  validation 新增整数/正数校验（FMT-003/004、STR-001/004）、未知参数键告警、
  `languagetool_url` 本地白名单、regex 规则章节归属校验、`豁免版式: []` 提示。
- **P1 LanguageTool 逐段 HTTP** —— 同页同语言合并为 1 次请求 + 文档级段缓存；
  技术页 17 次/页的请求量降到 ≤2 次/页。
- **P2 批量修复** —— 辅助文本 `page_index=-1` 哨兵改为 `None`（不再显示「第 0 页」）；
  0 字号不再触发除零导致整份格式审查变 SYS-ERROR；FMT-TABLE-FIT 按 colspan/rowspan 累加几何；
  DOCX 标题样式编号不再被当项目符号；重复句/近似页比较排除页眉页脚；SARIF 相对 URI 百分号编码
  与路径规范化缓存；LanguageTool stderr 改 DEVNULL、jar 缓存目录改用户目录并容错；
  Streamlit 报告文本增加 Markdown 中和（防图片/链接外联）；页面豁免改集合命中；
  审计器缓存键纳入 glossary/vocab mtime；`save_exemptions` 失败可见。
- **文档** —— 内置检查数 23→30；术语表 45+/20 条 → 40 条（19/4/17）；删除不存在的
  「可配置处理超时」声明；api-reference 修正 FormatAuditor 配置键清单与豁免签名；
  审查 Prompt 的 CI 事实（覆盖率门槛/规则断言/基线）同步；handoff 基线数字自相矛盾修正。

## [0.2.0] - 2026-10-29

首个功能完整发行版（0.1.0 → 0.2.0）。汇总 2026-10-28~29 四个批次：质量复核整改（R-01~R-24）、
第二批收尾（表格 fit/报告工作流/豁免持久化/规则注册表/配置校验/标点补全/DOCX 辅助文本/PDF 双后端）、
增强迭代（DOCX 列表/报告统计/exemption_key/--fail-on/分页）、Code Scanning 与工程化
（`--sarif-base`/pre-commit/性能基线/覆盖率补强）。

**发行基线**：**627 个测试用例（23 个文件）** · 覆盖率 **88%** · ruff 全绿 ·
26 条配置规则 + 30 项内置检查 · 报告 HTML/JSON/CSV/SARIF · 完全离线。

### Added

- **发行工程（2026-10-29）**：`--version` / `doctor` 版本行；`scripts/check_release.py` 发行自检
  （版本双源 / CHANGELOG 发行头 / 必备文件 / CLI 版本）；`MANIFEST.in` 保证源码包包含
  app.py/rules.md/glossary/vocab/docs/skills/scripts/tests；测试门禁新增发行三检（版本/3.10 语法/发行头）

- **Code Scanning / 工程化批次（2026-10-29 第四轮）**：
  - **SARIF 对接 Code Scanning**：`generate_sarif_report()` 新增 `uri_base`；CLI `--sarif-base`
    输出仓库相对 URI；修复**批量聚合 SARIF 把所有 finding 归到最后一个文件**的 artifact 归属 bug
    （批量时给 finding 标注 `metadata["source_file"]`）；README/用户手册补 Code Scanning 工作流示例
  - **pre-commit**：`.pre-commit-config.yaml`（commit: ruff + `rules validate`；pre-push: `pytest -m "not slow"` 快测 ~40s）；
    pytest 注册 `slow` 标记（子进程/AppTest/真实 docling/LanguageTool 集成）
  - **性能基线**：新增 `scripts/benchmark.py`（10/50/100 页 docx+pptx，分段计时/JSON，带预热）；
    实测 100 页全流程 DOCX 0.71s / PPTX 1.54s，写入 README/specification 基线表
  - **覆盖率补强**：新增 `tests/test_cli_inprocess.py`（18 个测试，进程内 main() 分支；subprocess 不计 coverage）
  - **性能修复**：LanguageTool 探活 localhost→127.0.0.1（Windows IPv6 白等 ~2s）、探活超时 1s、
    30s 进程级缓存（重复审查不再重探）、拼写词典类级共享；测试套件 4m16s → ~2m
  - 覆盖率 82% → **87%**（cli.py 48%→86%，子进程不计 coverage 的缺口由进程内测试补上）；CI 门槛 75% → 82%
  - 测试 553 → **585**（22 文件）

- **增强迭代（2026-10-29 第三轮）** —— 实测驱动的易用性/正确性增强：
  - **DOCX 列表符号**：新增 `_DocxNumberingResolver`（`w:numPr` + `numbering.xml`，段落级与样式级回退），
    列表段落获得 `bullet_type`/`bullet_char`（Symbol/Wingdings 私有区字形归一为 `•`）；
    修复 DOCX 列表对 `FMT-007`（项目符号混用）与 `TXT-BULLET-PUNCT`（末尾标点不一致）完全失明的问题
  - **豁免基线工作流**：`AuditFinding.to_dict()` 与 CSV 报告输出稳定 `exemption_key`
    （CSV 末列），CLI/表格用户可直接据此构造 `.docauditignore`
  - **CLI `--fail-on`**：`error`（默认，保持历史行为）/ `warning` / `info` / `none`，
    便于 CI 按团队标准设阈值；新增可单测的 `_findings_exit_code()`
  - **HTML 报告**：摘要增加「按类型分布」（结构/格式/语言/术语…）；缩略图增加单页 200 /
    总计 3000 元素上限，避免超大文档报告膨胀
  - **Web UI**：发现列表分页（每页 100 条，上一页/下一页），数百条 finding 不再一次渲染全部卡片；
    新审查/批量审查/新文件时自动回到第 1 页
  - **doctor**：新增「Configuration validation」检查（rules/glossary/vocab schema），
    配置错误在环境诊断中直接暴露
  - **`rules list`**：`docaudit rules list` 打印解析到的规则表（ID/严重度/检查/说明）；
    `.docauditignore` 改为原子写（临时文件 + `os.replace`），中断不再留下半截 JSON
  - **CI**：新增 `docaudit rules validate` 步骤；覆盖率门槛 70% → 75%（实测 82%）
  - 测试 529 → **553**（新增 DOCX 编号、fail-on、exemption_key、HTML 统计/上限、分页、rules list 用例）

- **第二批收尾（2026-10-29）** —— 完成 handoff §5 全部建议项：
  - **表格 fit**：新增内置检查 `FMT-TABLE-FIT`（行高不足 / 长词超列宽 / 表格估算越界）；
    `TableCell` 增加单元格边距，`PageElement` 增加 `table_row_heights` / `table_col_widths`，
    PPTX（EMU→pt）与 DOCX（Length）均提取行列几何；复用 FMT-TEXT-OVERFLOW 的估算器（抽取为模块级 SSOT）
  - **报告工作流**：HTML 报告内联 SVG 页面线框缩略图（上限 80 页）+ 批量按文件分组（含每文件严重度计数）；
    新增 `src/reporters/csv_reporter.py`（UTF-8 BOM、防 Excel 公式注入）与
    `src/reporters/sarif_reporter.py`（SARIF v2.1.0、稳定 partialFingerprints）；
    CLI `-o` 支持 `.csv` / `.sarif`（批量 SARIF 聚合为单文件）；`--thumbnails/--no-thumbnails`；
    Web UI 增加 CSV/SARIF 下载按钮
  - **豁免持久化**：新增 `src/engines/exemptions.py`（`.docauditignore` JSON v1，读取只信任稳定
    `exemption_key`，文件损坏 fail-open 到多报）；CLI `--exempt-file`；Web UI「💾 保存豁免到 .docauditignore」
    并在启动时自动载入
  - **规则注册表**：`CHECK_REGISTRY`（`CheckSpec`）成为 dispatch 检查唯一真相来源，
    `_DISPATCH` 与 pipeline `_skip_checks` 自动派生 —— 新增 check_type 由三步降为两步
  - **配置校验**：新增 `src/engines/validation.py`（rules/glossary/vocab schema 校验：ID/严重度/
    check_type/正则/数值范围/重复项/未知字段）+ CLI `docaudit rules validate`（错误时 exit 1）；
    修复 `vocab/accept.txt` 两条大小写重复条目
  - **标点/文字补全**：`PUNCT-008`（日期格式混用）、`PUNCT-009`（范围连接符混用，先掩码 ISO 日期）、
    `PUNCT-010`（数值与单位空格不一致）、`TXT-BULLET-PUNCT`（项目符号末尾标点不一致）、
    `TXT-DUP-SENTENCE`（跨页重复句）、`TXT-NEAR-DUP`（近似重复页，字符二元组 Jaccard ≥ 0.90）
  - **DOCX 辅助文本**：页眉/页脚/脚注提取到 `Document.auxiliary_elements`（按类型+文本去重），
    参与中英混排/标点/冗余/术语/禁用词检查（位置显示「页眉/页脚/脚注」），不再只告警跳过
  - **PDF 双后端**：`PdfConverter` 支持 PyMuPDF（可选安装，文本块+书签层级+bbox，规避 docling
    非 ASCII 路径限制）；`DOCAUDIT_PDF_BACKEND=auto|pymupdf|docling` 可覆盖；缺 PyMuPDF 时回退 Docling
  - 测试 427 → **529**（新增报告工作流/豁免/配置校验三文件及审计器、转换器补测），文档同步

### Fixed

- **质量复核整改批次**（2026-10-28，`logs/reports/deep-review-quality-2026-10-28.md` R-01~R-24）：
  - **误报控制**：CON-004 版式豁免改为精确匹配 + 封面专用短语（`Title and Content` 不再被 `Title` 子串豁免）；结论关键词只扫非标题正文、备注不再单独作为结论；对齐检查改为角色感知，标题/正文不再互比；TERM-003 收紧为全大写技术缩写并支持 `排除白名单`/`仅首次出现`；CON-003 接入 `vocab/accept.txt`；CON-001 将年份/季度/工艺节点作为限定词保留，不再误报跨年/跨季度/跨节点数值
  - **继承格式**：PPTX 解析 theme/master/layout/txStyles，DOCX 解析 style/based-on/docDefaults；模型增加 `effective_font_name*` / `effective_font_size` / `font_size_inherited`，FMT-001/002 不再因继承字号 None 静默漏检
  - **格式作用域**：FMT-001/002/003/005 收敛为 PPTX 专属，DOCX 16pt 标题、300 字页、宋体正文不再误报；`_DISPATCH` 同步 `pptx_only`
  - **PPT 版面**：新增元素重叠（FMT-OVERLAP，25% 阈值、排除嵌套/空占位/全屏背景）与安全边距（FMT-SAFE-MARGIN，1%）；Group 子元素按 `off/ext/chOff/chExt` 递归变换为绝对坐标；真实项目符号从 `a:buChar`/`a:buAutoNum` 提取，FMT-007 与 AutoFixer 不再依赖文本前缀
  - **文字规范**：新增 PUNCT-001~007（重复/冲突标点、中英标点混用、全半角、括号配对、省略号/破折号）与 TXT-REDUNDANT；中文基础模式改为始终执行，不再只存在于 LanguageTool Tier-3；移除 `general_tech.yaml` 中与 FMT-MIXED/PUNCT 重复的模式
  - **可见性/工作流**：干净文档（findings=[]）也渲染 0 问题摘要与报告下载；稳定豁免键 `exemption_key` 替代随机 id；批量页面豁免按 `(文件, 页码)`；批量 finding 增加 `metadata["source_file"]`；无效正则转 `SYS-ERROR`；doctor 可选依赖缺失不再 exit 1；旧版 `.ppt/.doc` 给出“另存为”提示
  - **AutoFix**：支持 Group/表格/页眉页脚遍历，跳过 `+mj-lt`/`+mn-lt` 主题字体，真实 `a:buChar` 走 XML 修复
  - **2026-10-29 续修**：FMT-002 默认上限调整为标题 28-44pt / 正文 12-32pt（对齐 Office 默认主题 44/32）；新增 FMT-TEXT-OVERFLOW（估算）、FMT-FOOTER、FMT-IMAGE（宽高比/DPI/alt text）、FMT-CHART（标题）、STR-MASTER（多母版）；Converter 增加 `master_name`/`placeholder_type`/`auto_size`/`word_wrap`/文本框边距/图片像素尺寸/图表标题图例元数据
  - 测试用例 369→427（白名单文档已同步）

- **五轮审查整改批次**（2026-09-06，r5 报告 F-01~F-11 全数处理）：
  - `scripts/install.sh` 安装目标修复（F-01）：曾 `pip install "$SCRIPT_DIR[all]"`
    指向 scripts/ 自身（无 pyproject，macOS/Linux 手动安装必失败）；派生
    `PROJECT_DIR` + `VENV_DIR` 绝对路径，与 run.sh/install.py 双轨对齐
  - 脚本 CWD 强依赖消除（F-02/F-03）：install.sh 与 setup_offline.sh 的 venv
    创建/激活/pip 调用全部改 `$VENV_DIR` 绝对路径；install.sh 验证导入补
    streamlit（F-11，与 install.py 对齐）
  - `scripts/common.py` find_python 版本扫描 glob 化（F-04）：`Python3*/python.exe`
    全版本扫描替代硬编码清单（Python 3.14 曾被漏扫），免支持矩阵前移再漂移
  - test_gates 三门禁负向锚定（F-05）：裸异常/(api-reference 同步)/文档数字
    门禁各补「注入违例必 FAIL」负测试（门禁实现腐化时不再假绿）；
    RULE_COUNT_RES 兼容 `**规则**: N 条` 粗体形态（F-06：api-reference 头部
    声明曾因粗体零命中而脱保），并加「白名单文档至少命中一类数字声明」断言
  - 黄金测试比对键纳入 metadata（F-07）：CON-001 values / SYS-ERROR error 等
    细节漂移不再漏拦；WebUI 三用例补 `assert baseline` 空守卫（与 CLI 孪生对称）
  - LanguageTool 降级测试 mock 探活（F-08）：测试套件零真实 socket
  - FMT-001 默认严重度断言改从 rules.md 声明读取（F-09，用户调整 rules.md
    不再误报测试失败）；补建 AGENTS.md 声明的两个薄 skill（F-10：
    `skills/rules.md`、`skills/deep-code-review.md`，均指针型保 SSOT）
  - test_scripts.py 新增 .sh 路径语义静态断言（PROJECT_DIR 派生/绝对 venv/
    禁 scripts/ 自身安装目标，防「脚本双轨制失配」同族复发）
  - 测试用例 368→369（白名单文档已同步）

- **四轮发行前深度审查整改批次**（2026-09-06，四轮审查 5 项发现全数处理）：
  - CON-001 章节式图表编号子号误报修复（N-1）：编号跳过守卫扩展，`图2-1`/`表3-1`/
    `Fig. 2.1` 的子号与点分隔图号不再漏过滤 —— 同句式跨页引用不同子号时不再误报
    ERROR「数值不一致」；关键词与分隔符间兼容 ≤8 非数字字符（`to fig. 2-` 等长前缀）
  - CON-001 截断防护补强（N-2）：小数/千分位延续（`3.3Vs`→`3`、`1,000`→`000`）与
    版本号残缺值（`2.5.1`→`2.5`）一律整值跳过，宁缺毋滥不出错值
  - SYS-ERROR 同异常文本折叠补测（N-3）：两条不同规则抛逐字节相同异常文本不再折叠
    （context 前缀带 rule_id 的修复此前仅不同异常文本场景有测试锚定）
  - rule_severities 提取测试去耦合（N-4）：改自引用断言（值 = rules.md 规则自身声明），
    用户合理修改 rules.md 严重度不再误报测试失败
  - ai-review-prompt 事实基准 HEAD 括注校准（N-5）
  - 测试用例 363→369（四轮补测；白名单文档已同步）

- **三轮发行前深度审查整改批次**（2026-09-06，全量审查 14 项发现全数处理）：
  - STR-002 图表编号正则防回溯：`(?!\d|-\d)` 双重负向断言替代 `(?![-–—]\d)`，
    两位数章节号（图11-2/图10-1）不再被回溯截为「图1」产生 ERROR 级「编号重复」
    误报；补重复编号正报 + 两位数不误报双用例（该分支曾零测试锚定，负向注入实证）
  - CON-001 数值提取单位表扩充（pt/kg/g/km/dB/Hz/ms 等）+ 截断防护兜底：
    「28pt→2」「500g→50」类截断漏报与数值失真消除，表外单位整值跳过不出错值
  - FMT-001/002/004 严重度配置驱动：无 `检查:` 键的 format 规则经
    `rule_severities` 通道由 FormatAuditor.audit() 统一覆盖（rules.md 是严重度
    唯一来源；parser/pipeline/format/custom_rules 四处联动，回退路径键集同步）
  - SYS-ERROR context 前缀带 rule_id：不同规则抛相同异常文本时 dedup 不再折叠
  - AutoFix 元素溢出修复对 left/top/width/height 为 None 的形状跳过（防御
    继承链无 xfrm 的 TypeError 中止）
  - rules.md/术语表编码回退 utf-8→gbk（与 vocabulary 对齐，误存 GBK 不再
    整配置失效/整表静默丢失）；pptx_converter 单 shape 异常捕获放宽为
    Exception（与 docx_converter 对齐，损坏 shape 不中断整文件转换）
  - font_size 判断规范化 `is not None`（structure.py/pptx_converter.py，
    对齐 falsy-pitfalls 约定）；CI 与 test_rules 规则数断言改精确 `== 26`
    （宽松下限拦不住缓慢缩减）；Streamlit 显式 `maxUploadSize = 100`
  - 文档：rules.md 内置检查表补录代码内置不可配阈值（对齐容差/字体种类上限/
    画布基准/CON-004 门槛/分段门槛/上下文窗口）；api-reference 同步
    FormatAuditor `rule_severities` 参数；嵌套 Group 转换、metadata.title 与
    rule_id XSS 载荷补测（用例 353→363）

### Changed

- **5S 整改批次**（2026-09-06）：
  - 目录重组：`rules/` 文档并入 `docs/` 三分区（governance / specification / user-manual，
    参照 Harmonization 治理体系），新增 `docs/README.md` 索引；审查报告统一归档
    `logs/reports/`（logs/ 已 gitignore，不入库）
  - 移除 `.claude/`（本机配置）、`.qoder/`（含 .qoder/skills 注册副本——skills/ 成为技能
    唯一定义处；.qoder/prompts 历史审查模板语义已并入 docs/governance/ai-review-prompt.md）、
    `tools/` 五门禁及其 5 个 test_check_* 测试文件；四个仍有意义的门禁
    （裸异常 / HTML 转义 / api-reference 同步 / 文档数字）已原逻辑 pytest 化为
    `tests/test_gates.py` 持续强制，skill 双份同步门禁因 .qoder/ 移除不再需要
  - CI lint job 收敛为 ruff check + format（移除 5 个门禁步骤，门禁由 test job 的
    pytest 承接）；test job 的 pytest 矩阵 / DISPATCH 验证 / rules 解析断言不变
  - 移除本地生成物 `docaudit.egg-info/`（setuptools 构建元数据，gitignore 排除，下次构建自动重建）

### Fixed

- **STR-003 标题层级检查在流水线中静默失效**（2026-08 引入，2026-09-06 复活）：
  `_skip_checks` 屏蔽 audit() 直调路径后，`_DISPATCH` 是 STR-003 唯一执行通道，而
  `heading_level_sequential` 的 `pptx_only=True` 标志与方法内 PPTX 守卫（para.level 是
  缩进级别非标题层级，早退）叠加，导致非 PPTX 文档的标题跳级检查彻底不再触发。
  修复：dispatch 标志改为 False（方法内守卫保留，PPTX 行为不变），补 dispatch 级
  回归测试（`test_str003_fires_through_dispatch_for_non_pptx`）；api-reference DISPATCH 表
  同步（CON-004 行 PPTX only ✓，两方法说明标注适用格式）
- **二轮发行前深度审查整改批次**（2026-08-24，发行前复审）：
  - PDF 中文路径防护：`pdf_converter` 非 ASCII 安装路径检测（限 Windows，docling C++ ANSI fopen 限制），提前抛可操作错误替代晦涩报错；真实 docling 集成测试在非 ASCII 路径自动 skip
  - 门禁健壮性：`check_doc_numbers` 收集含 error（如缺 streamlit）时跳过测试数检查，不再误报数字漂移；`check_bare_handlers` 豁免窗口扩展含 except 上一行（常见「# 降级」注释习惯）
  - 配置流：CON-002 严重度由 rules.md 声明驱动（曾硬编码 ERROR）；`_create_auditor` 回退路径 `exempt_layouts` 默认值对齐 `build_auditors`（曾空列表覆盖默认豁免）
  - 一致性：CON-003 独立模式兜底 severity 对齐 rules.md（WARNING→error）；架构文档 `project-structure.md` 依赖表修正（pipeline 跨层编排例外）
  - 清理：删除死代码 `LATIN_RE`；图/表编号、图表标题、标题英文词、autofix 标题标点/项目符号正则提升为模块级预编译

- **max level 深度审查整改批次**（2026-08-19，HEAD 94bf3b0 复审）：
  - DOCX 标题层级提取补样式级回退（styles.xml outlineLvl + Heading N 样式名正则），修复 add_heading 等样式型标题 level=None 导致的标题类检查/语义分页静默盲区
  - setup_offline.sh 项目根路径修复（PROJECT_DIR 派生）；run.sh grep -oP 改 grep -Eo（macOS 兼容）
  - CON-004/STR-003 加格式守卫（非 PPTX 不再误报每页须结论；PPTX 缩进级别不再冒充标题层级）
  - languagetool_url 接线为 rules.md 可配置（仅限 localhost 白名单）
  - 运行期 HF_HUB_OFFLINE/CACHE 注入 pdf_converter（离线 PDF 转换不再尝试联网）
  - CLI：-o 导出失败显性化（exit 1）、不支持扩展名报错（exit 2）、--fix 不支持格式提示
  - Web UI：rules.md 热更新（缓存键含 mtime）、上传文件显示原始名、st.expander 标题转义
  - AutoFix：os.replace 原子覆盖、eastAsia 缺失元素创建
  - 门禁：check_api_sync 签名一致性、check_html_escape 覆盖 app.py、check_doc_numbers 否定语境、check_skill_sync 双向+BOM 容错
  - 其他：factual 缓存 weakref、缩写定义窗口修复、全局字体统计纳入 eastAsia、md 表格行号/页面序号连续化、pdf 跨页归属、模型死字段清理（详见 2026-08-19 审查报告）

### Added

- **审查整改批次（2026-08-18，fix）**：eastAsia 中文字体链路打通（docx/pptx 读写字型）、
  黄金测试升级为真实三路径（CLI/WebUI/Python 同一输入产生相同发现）、幻影规格重写
  （规则清单逐条对齐 rules.md，删除 LANG/CUSTOM 幻影条目）、安全加固（路径沙箱、
  localhost 绑定、离线环境变量）、门禁升级与自身测试、CLI 处理失败退出码修复、
  文档事实冲突修正（命令名统一 docaudit、context.md 移除 jieba 幻影、README 退出码表述对齐）。
  数字类声明由主代理统一同步。
- **文档数字一致性 CI 门禁**：`tools/check_doc_numbers.py` 校验白名单文档中的当前事实
  数字（测试用例数/规则数/测试文件数/format.py 检查数）与代码实际值一致；
  历史语境自动排除（「」引号内、CHANGELOG 历史区、规划文档）；已接入 CI lint job，
  首次运行即捕获 2 处真实漂移（测试文件数 12→13、用例数 189→200）
- **文档数字一致性门禁测试**：`tests/test_check_doc_numbers.py`（TDD，含历史语境排除/多写法识别）
- **FMT-008 表格文字与底色对比度规则**：深色底色配浅色文字、浅色底色配深色文字
  （WCAG AA，正文 4.5:1 / 大字 3:1，阈值经 rules.md 配置）；覆盖 PPTX/DOCX 原生表格，
  仅对 solid 纯色底色判定，无填充/渐变/主题色/嵌入 Excel 降级跳过不误报；
  `TableCell` 新增 `fill_color` / `font_color` 字段，新增 `tests/test_contrast.py`（含算法/边界/降级用例）
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

### Fixed

- **5S 整理：Prompt/审查报告归位 .qoder（平台本地资产，不入库）**：
  - `rules/code-review-prompt.md`、`skills/deep-code-review.prompt.md` 移至
    `.qoder/prompts/`（git rm --cached + gitignore；prompt 修改后同步 `.qoder/skills/` 注册副本）
  - `.claude/` 本地配置加入 gitignore（本机路径白名单不入库）
  - 文档引用同步（AGENTS/CLAUDE/documentation/project-structure），check_doc_numbers 白名单移除已迁移文件
- **第二轮 max level 全量审查修复批次**（2026-08，HEAD d0637ff 复审）：
  - PDF mock 测试封闭化（sys.modules 注入假 docling/pandas，CI 无 pdf extra 也通过；
    原实现依赖真实安装，CI 必红）
  - SYS-ERROR 多条失败不再被 deduplicate 折叠（context 带错误摘要进 dedup_key）
  - STR-002 章节式编号（图1-1/表2-2）不再误报"编号重复"
  - TERM-003 边界收紧：字母数字复合词前缀（CDMA2000/TSVstack）不误报；
    括号内全称定义词（TSV (Through Silicon Via)）不误报；仅中文页面参数
    布尔解析统一（"false" 字符串不再误判为真）
  - 未知 check_type 转 SYS-ERROR finding（rules.md 拼写错误 UI 可见）
  - setup_offline 离线 pip 升级命令提为纯函数 + 回归测试
  - api-reference dedup_key 描述修正；code-review-prompt 测试数同步

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
- 文档数字漂移：CHANGELOG 测试用例数 53 → 200（实际 12 个测试文件）
- dependabot 锁文件 bump 引入的版本约束冲突已回退：
  pyarrow 25（streamlit 要求 <25）、typer 0.27（docling-core 要求 <0.27）、
  starlette 1.6（streamlit 要求 <1.4）、pydantic-core 2.48（pydantic 精确钉死 2.46.4）、
  mpmath 1.4（sympy 要求 <1.4）——保留 docling-parse/docling-ibm-models/
  mail-parser/marko/typing-inspection 五个合法 bump

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
