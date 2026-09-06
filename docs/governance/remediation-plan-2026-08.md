# DocAudit 审查整改实施计划（2026-08）

> 依据：综合评估（2026-08，评分 8.0/10）发现的 P0-P3 全部问题。
> 执行纪律：TDD（先写失败测试 → 验证 RED → 最小实现 → GREEN）、精准修改、
> 红线合规（html.escape / 禁裸 except / 完全离线 / 文档同步）、提交前跑门禁。
> 本文件为规划文档，check_doc_numbers 白名单不检查规划文档。

## 工作包划分（按文件所有权，互不冲突）

| WP | 负责人 | 文件所有权 | 内容 |
|----|--------|-----------|------|
| WP-A | Agent-1a | src/models/document.py, src/converters/docx_converter.py, src/converters/pptx_converter.py(字体部分), src/auditors/format.py, src/engines/autofix.py, rules/api-reference.md(相关节), tests/test_converters.py, tests/test_autofix.py, tests/test_auditors.py | P0-1 eastAsia 字体链路、docx shape_name→style_name、docx 嵌套文本日志、Run 新字段 |
| WP-D | Agent-1b | src/converters/pptx_converter.py(内存部分), src/converters/pdf_converter.py, tests/fixtures/sample.pdf, tests/test_converters.py(追加) | P1-5 image_blob/内嵌 Excel 内存、P1-6 docling 2.119 集成测试、md frontmatter/表格分隔行修复 |
| WP-B | Agent-2 | tests/test_integration.py, 新 tests/test_golden_paths.py, 新 tests/test_rule_coverage.py, tests/test_edge_cases.py, 新 tests/test_html_report_security.py | P0-2 黄金测试真实三路径、P1-7 12 条规则断言补齐、HTML 转义红线测试、弱断言加强、run_auditors SYS-ERROR/on_progress 测试 |
| WP-C | Agent-3 | app.py, .streamlit/config.toml, scripts/setup_offline.py, 新 tests/test_app_ui.py | P1-4 安全（路径沙箱、localhost 绑定、HF_HUB_OFFLINE）、P2 UI 修复 P5-P10 |
| WP-F | Agent-4 | src/engines/languagetool.py, tools/check_api_sync.py, tools/check_html_escape.py, 新 tools/check_skill_sync.py, tests/test_engines.py, 新 tests/test_check_api_sync.py, 新 tests/test_check_html_escape.py, 新 tests/test_check_skill_sync.py, .github/workflows/ci.yml, pyproject.toml, skills/python-SKILL.md | P2 LT 内部修复、P2 门禁升级+自身测试+新门禁、CI 增强（覆盖率/ruff format/新门禁）、falsy SSOT 链接 |
| WP-E | Agent-5 | rules/specification.md, rules/context.md, rules/user-manual.md, rules/refactoring-plan.md, README.md, CHANGELOG.md, src/cli.py, 新 tests/test_cli_exit_codes.py | P0-3 幻影规格重写、P1-8 文档事实冲突（README 退出码/命令名/jieba/CHANGELOG 合并）、cli.py 处理失败退出码 |
| WP-Z | 主代理 | AGENTS.md, CLAUDE.md, 最终门禁 | 文档数字同步、CLAUDE 副本、全量验证、收尾 commit |

## 各 WP 详细任务

### WP-A（Agent-1a）：eastAsia 中文字体链路（P0-1）

问题：python-docx font.name 只读 w:ascii/w:hAnsi；python-pptx font.name 只读 a:latin；
autofix 写字体同样不写 eastAsia → 中文文档字体检查盲、修复无效。

任务（TDD，每步先写失败测试）：
1. Run 增加 font_name_east_asia: str | None = None 字段（document.py）+ 同步 rules/api-reference.md Run 表。
2. docx_converter：读 w:eastAsia（rPr/rFonts @w:eastAsia），写入 font_name_east_asia；无 eastAsia 时保持 None。
3. pptx_converter：读 a:ea typeface（run.font._rPr 下），写入 font_name_east_asia。
4. format.py _check_font_consistency：font_name 与 font_name_east_asia 均须在 allowed_fonts 内（后者非 None 时检查），
   finding 的 metadata 标注 font_scope: "east_asia"|"latin"，message 说明是中文/西文。
5. autofix：替换字体时同时写 latin/ea（pptx 用 rPr.get_or_add_ea()，docx 用 rFonts.set(qn('w:eastAsia'), ...)）。
   需先验证 python-pptx 的 get_or_add_ea 是否存在（不存在则用 lxml 手工创建 a:ea 元素）。
6. docx_converter：shape_name 不再塞样式名，新增 style_name 字段放样式名（PageElement），
   调用处（format.py context、structure.py title 检测）同步；api-reference 同步。
7. docx_converter：顶层元素映射时对文本框/页眉页脚/脚注等未解析内容加 warning 日志。
8. 测试：test_converters（docx/pptx eastAsia 提取）、test_auditors（FMT-001 eastAsia 触发）、
   test_autofix（docx/pptx eastAsia 修复后重开文件验证生效 + 幂等）。
9. 若存在依赖 _DISPATCH/_skip_checks 的断言（test_rules 三向守卫），确认不受影响。

### WP-D（Agent-1b）：内存与 docling（P1-5/P1-6）

1. pptx_converter _convert_image：不再把 image_blob 载入内存——PageElement 移除 image_blob 字段
   （先 grep 全项目确认无消费者；Page.image_blob 同样处理），保留 image_ext；api-reference 同步。
2. _extract_chart_data：不读整包 blob——grep 确认 chart_data 消费者后决定：无消费者则移除装载，
   chart_type 保留。
3. pdf_converter：docling 2.119.0 已装；写真实集成测试：
   - 新增 tests/fixtures/sample.pdf（程序化生成的最小合法 PDF，含 "DocAuditTest" 文本，xref 正确）
   - 测试：docling 可导入时真实转换，断言 pages>=1、文本包含 DocAuditTest；断言走的是结构路径
     （元素含 text_frame 而非纯 fallback）；docling 缺失时 pytest.importorskip 跳过。
   - 注意：评估环境沙箱会拦截 docling-parse 的 C fopen（伪"文件不存在"），真实环境不受影响；
     测试失败需人工判断是否为沙箱伪影。
4. md_converter：frontmatter 误判修复（严格三行式 --- 判定）；表格分隔行正则 ^[\|\s\-:]+$ 对纯 "-"
   数据行误判修复；前缀空格标题与页面分割正则不一致修复。
5. 追加测试至 test_converters.py。

### WP-B（Agent-2）：黄金测试与测试补盲（P0-2/P1-7）

1. 新 tests/test_golden_paths.py：真实三路径黄金测试：
   - 路径1 Python API：现有方式。
   - 路径2 真实 CLI：subprocess 运行 python src/cli.py <file> -o <tmp>.json --rules ...，
     读取 JSON 报告的 findings，与 API findings 按 (type,severity,rule_id,page_index,message,context,suggestion,location)
     排序后集合比较（排除随机 id）。sample.pptx 与程序化生成的 docx/md 各跑一遍。
   - 路径3 真实 WebUI：streamlit.testing.v1.AppTest 运行 app.py，file_uploader 注入文件，点击"开始审查"，
     读 session_state["findings"] 与 API 比较。若 AppTest 交互不可行，退化为验证 app.py 的
     convert_file_path/_get_auditors 纯函数路径并明确注释。
   - 旧 test_integration.py 中的间接"三路径"测试保留但改名/注释说明其定位（流水线确定性）。
2. 新 tests/test_rule_coverage.py：12 条零断言规则补定向测试：
   STR-005 重复标题、STR-006 标题尾随标点、STR-008 版式多样性、CON-001 数值一致性、
   CON-002 必含章节、CON-003-A/B/C 缩写生命周期、FMT-003 单页字数、FMT-004 段落过长、
   FMT-005 元素溢出、FMT-006 空占位符、FMT-007 项目符号混用。用程序化构造 Document/PPTX 触发与不触发。
3. 新 tests/test_html_report_security.py：html.escape 红线——message/context/suggestion/location/source_path
   注入 <script>alert(1)</script> 等载荷，断言输出 HTML 中载荷被转义、无原始 <script>。
4. test_edge_cases.py 弱断言加强：空文档断言具体语义（如 CON-004 空页触发/0 页不崩溃且有具体断言）。
5. run_auditors 测试：on_progress 回调调用序列、审计器抛异常 → SYS-ERROR finding 且多条不折叠。
6. 测试数量变化汇报给主代理（不自行改 AGENTS.md/README 数字）。

### WP-C（Agent-3）：安全与 UI（P1-4/P2）

1. .streamlit/config.toml： [server] address = "localhost"（防 0.0.0.0 暴露）。
2. app.py 路径沙箱：folder_path 含 ".." 路径段或非目录 → st.error 阻止（由 warning 改为拒绝）；
   扫描仅限存在的目录；注释更新。
3. scripts/setup_offline.py：下载/安装命令设置 HF_HUB_OFFLINE=1（离线红线）；README 方案 C 已有描述则同步。
4. app.py UI 修复：
   - P5 severity checkbox 滞后：重构为 widget 渲染后再计算 filtered（消除顶部预计算时序错位），保持单次计算。
   - P6 批量元数据：批量报告用聚合元数据（页数=sum、file_label="N 个文件"）；html_reporter 支持 page_count
     覆盖参数（向后兼容默认 None）。
   - P7 清除豁免残留：multiselect 加显式 key，清除/重置时同步清 widget state。
   - P8 同名覆盖：批量 key 用完整路径或 name+序号。
   - P9 缓存：_get_auditors 用 @st.cache_resource 包装（按 rules.md 等路径做 key）。
   - P10：exempted_finding_ids 统一整体赋值风格。
5. 新 tests/test_app_ui.py：_apply_filters 纯函数测试（AppTest 可行的加 AppTest 冒烟）。

### WP-F（Agent-4）：LanguageTool 与门禁（P2）

1. languagetool.py：
   - base_url 主机白名单：构造时校验 host ∈ {localhost, 127.0.0.1, ::1}，否则 ValueError（封死外发通道）。
   - _check_chinese_patterns context 补 offset/length（与英文分支对齐，恢复 accept.txt 白名单过滤）。
   - _check_http 失败时记录已检查字符/总字符的 warning（不静默丢剩余 chunk）。
   - reset() 还原初始 base_url（保存构造时值）。
2. 门禁：
   - check_api_sync.py：白名单加入 src/models/document.py、src/models/finding.py；
     匹配方式升级为"模块/类/函数名在文档表格行或代码块中以条目形式出现"（保守实现+测试）。
   - check_html_escape.py：支持"转义结果先存变量再插入"的间接引用模式检测；字段集中为常量；新增自身测试。
   - 新 tools/check_skill_sync.py：校验 skills/*.md 与 .qoder/skills/*/SKILL.md 去 frontmatter 正文一致；
     接入 CI；自身测试。
3. .github/workflows/ci.yml：lint job 增加新门禁步骤；test job 加 --cov=src --cov-report=term
   （先本地实测覆盖率再决定是否加 fail-under 阈值，阈值宜 60-70，若实测不足则只上报不加阈值）；
   ruff format --check 步骤（若仓库当前不符合 ruff format 则先格式化并提交，再启用检查）。
4. pyproject.toml：ruff 配置保持；pytest addopts 谨慎，避免影响现有。
5. skills/python-SKILL.md：补 falsy-pitfalls.md 引用（兑现 SSOT 声明）。

### WP-E（Agent-5）：文档与 CLI（P0-3/P1-8）

1. rules/specification.md 重写：以 rules.md 为唯一真相——
   §2.2 规则清单 = STR-001~008 / FMT-001~008 / TERM-001~003 / CON-001~004+003-A/B/C（26 条，逐条对齐 rules.md）；
   删除 LANG-001/002、CUSTOM-001~016 幻影行；版本 0.1.0；commits 33；§4.1 测试文件 13+新增；
   标注最后更新日期与"以 rules.md/AGENTS.md 为准"声明。
2. rules/context.md：删除 jieba 技术选型行（全仓库零引用），补真实实现（_segment_by_language）说明。
3. README.md：退出码表述改为实测语义（处理失败的文件会使本次运行退出码为 1）——先改 cli.py 行为再改 README；
   "200 个测试用例"等数字由主代理最后统一同步（不要在 Agent-5 里改测试数相关声明）。
4. rules/user-manual.md：命令名 docaudit（与 pyproject console script 一致）。
5. src/cli.py：处理失败退出码——main() 统计处理失败文件数，任一失败 → exit 1（与 README 声明一致，
   markdownlint 风格）；不支持的格式/路径不存在已 exit 1 保持。新 tests/test_cli_exit_codes.py：
   损坏文件 exit 1、成功无 error exit 0、有 error exit 1。
6. CHANGELOG.md：合并重复的 ### Added 块；新增本批次整改条目（Unreleased）。
7. rules/refactoring-plan.md：顶部加"执行状态"批注（已完成/搁置），过期数字修正或标注历史快照。

### WP-Z（主代理收尾）

1. AGENTS.md：测试文件表/用例数/门禁清单（check_skill_sync）更新 + 历史经验表补充本批次教训；
   Copy-Item AGENTS.md CLAUDE.md 保持同步。
2. 全量验证：pytest（200+ 新用例）、4+1 门禁、ruff、DISPATCH 验证、CLI 端到端。
3. check_doc_numbers 确认通过（数字同步）。
4. 收尾 commit（不 push）。

## 延后项与理由（用户许可范围）

| 项 | 理由 |
|----|------|
| pptx Paragraph.level 缩进级与标题级语义完全统一 | 涉及 STR-003 在 PPTX 上的产品语义决策（缩进层级是否代表标题层级），属行为变更，需用户决策；本轮只做 md 0-based 归一化与语义注释 |
| 报告输出绝对路径（单文件） | 本地工具有意设计（便于定位文件），无外发通道；README 安全说明注明 |
| md 大文件流式读取 | 解析依赖全文（frontmatter/跨行表格/正则），流式改造风险>收益；>100MB md 罕见 |
| pytest %TEMP% symlink 清理 PermissionError | 评估环境沙箱伪影（C fopen 同因），非项目缺陷；README 已知限制加排查指引 |
| st.file_uploader 流式上传 | 平台 API 限制（getvalue 全量），需换上传方案；仅加审计器缓存 |
| docx 页眉页脚/脚注内容审查 | 转换器当前不支持，加解析属新功能（范围外）；本轮仅加缺失日志 |
