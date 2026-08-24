# 工具与脚本坑位清单（Windows / cmd / pip / git）

> 从 DocAudit 实际踩坑与跨项目经验（VibeCodingTemplate 模板）提炼。修改 `scripts/`、执行安装/离线流程、处理 git 操作前必读。

## pip / 离线安装陷阱

| # | 陷阱 | 正确做法 |
|---|------|----------|
| 1 | **`pip download <本地项目目录>` 不保存项目自身的 wheel**（2026-08 实证：`--no-deps` 下载后目标目录为空，仅打印 "Successfully downloaded"） | 离线安装仍从源码目录构建项目，因此 packages/ 必须含构建依赖（见 #2）；不要指望 packages/ 里有 docaudit 的 wheel |
| 2 | **`pip download` 不保存构建依赖 setuptools/wheel**（2026-08 实证：只保存运行时依赖 wheel）→ 离线 `pip install --no-index` 构建本地项目（PEP 517）时报 "No matching distribution found for setuptools>=68.0" | download 步骤显式补：`pip download setuptools wheel -d packages/`（setup_offline.py/.sh 已内置） |
| 3 | **只提供 sdist 的依赖**（如 `antlr4-python3-runtime==4.9.3` 无 wheel）→ 离线安装需现场构建，依赖构建工具链 | 属正常现象，但 packages/ 必须含 setuptools/wheel；下载后跑 dry-run 自检拦截 |
| 4 | **`pip download` 结果与解释器版本/平台绑定**（cp314 win_amd64 的 wheel 装不到其他版本/系统） | README 已提醒：离线机器必须与下载机同 Python 版本、同 OS；锁文件只锁版本，不跨平台 |
| 5 | **`>=` 未锁版本导致下载结果不可复现**（docling 依赖链极长，两次解析结果可能不同） | 用 `requirements-{core,pdf,full}.txt` 锁文件（`scripts/gen_requirements_lock.py` 生成），download 走 `-r` |
| 6 | **离线安装解析不校验 packages/ 完整性**（缺失 wheel 到离线机才暴露） | download 完成后立即 `pip install --dry-run --ignore-installed --no-index --find-links=packages/ ...` 自检（setup_offline 已内置，第 3 步） |
| 6b | **dependabot 单点 bump 锁文件 pin 会破坏版本约束**（2026-08 实测：pyarrow 25 违反 streamlit `pyarrow<25`、typer 0.27 违反 docling-core `typer<0.27`、starlette 1.6 违反 streamlit `starlette<1.4`、pydantic-core 2.48 违反 pydantic 精确钉 `==2.46.4`、mpmath 1.4 违反 sympy `mpmath<1.4`；dependabot PR 的 CI 只测 `pip install .[dev]`（未钉版本），从不验证锁文件自洽） | CI 门禁（windows-latest job）：`pip install --dry-run --ignore-installed -r requirements-*.txt .`；冲突 pin 回退或升级约束方后再合 |
| 6c | **离线 dry-run 自检无法发现 pin 冲突**（packages/ 是旧版本缓存，`--no-index` 只验证缓存完整性） | 锁文件自洽性由 CI 门禁（6b）守护；packages/ 与锁文件版本在重新 download 前短暂不一致属正常 |
| 6d | **锁文件平台绑定**：Windows 生成的锁文件含 pywin32（rapidocr 条件依赖）等平台专属包，Linux/macOS 解析必然失败；antlr4-python3-runtime 被 omegaconf 精确钉 `==4.9.*` 且无 wheel | 门禁跑在 windows-latest；macOS/Linux 用户在目标平台用 `gen_requirements_lock.py` 重新生成（README 已注明） |

## Windows / cmd / bat 陷阱

| # | 陷阱 | 正确做法 |
|---|------|----------|
| 7 | **批处理文件含中文注释时编码敏感**（cmd 按系统代码页解析，GBK/UTF-8 无 BOM 都可能导致乱码或命令错位；git log ff46e1c/622d1cc/15cc32d 三次修复） | 批处理只做 ASCII 启动器，逻辑放 `.py`（`scripts/common.py` + 各 .py 主逻辑，`reconfigure_utf8()` 保证输出编码） |
| 8 | **cmd 中 `if errorlevel` / 括号块内变量展开坑**（`%VAR%` 在块内是解析时值） | 需要动态值用 `!VAR!`（延迟展开）或把逻辑移入 Python；避免在 bat 里写复杂逻辑 |
| 9 | **PowerShell 5.1 读写 UTF-8 文件按 ANSI 处理**（中文乱码） | `Get-Content -Encoding UTF8` / `Set-Content -Encoding UTF8`；含中文的 .ps1 必须 UTF-8 with BOM |
| 10 | **PowerShell 5.1 不支持 `&&` 分隔符** | 用 `;` 或 `if ($LASTEXITCODE -eq 0)` |

## git 陷阱

| # | 陷阱 | 正确做法 |
|---|------|----------|
| 11 | **Windows 上 `git mv agents.md AGENTS.md` 失败**（core.ignorecase 默认 true 视为同名） | 两步改名：`git mv agents.md AGENTS.md.tmp && git mv AGENTS.md.tmp AGENTS.md`（2026-08 实证） |
| 12 | **push 前未确认测试全绿** | AGENTS.md 红线：未经用户明确同意不 push；提交前跑 `pytest tests/ -v` + 三门禁 |
| 13 | **`git add` 无法记录未跟踪文件的"删除"** | 未跟踪文件删除无需 git 操作；已跟踪的用 `git rm` |

## 验证脚本陷阱

| # | 陷阱 | 正确做法 |
|---|------|----------|
| 14 | **裸 grep 搜 `except:` 误伤 docstring/注释中的教学文字**（模板 #20 教训；本项目曾有"禁止写 except:"这类文字） | 用 AST 解析（`tools/check_bare_handlers.py`），天然跳过注释与字符串；不要用 grep 实现语义检查 |
| 15 | **门禁工具自身违反门禁**（检查器若用 `except Exception: pass` 处理读取失败，CI 自检即说谎） | 门禁工具也被自身扫描（check_bare_handlers 的默认扫描范围含 tools/） |
| 16 | **测试文件命名不匹配框架 glob** → 测试永不运行、CI 静默通过 | 本项目 pytest `python_files = ["test_*.py"]`，新测试必须 `test_*.py` 命名（tests/ 根目录） |
| 17 | **ruff per-file-ignores / noqa 无理由注释** | 每条豁免必须附中文理由（如 `# bare-handler-ok — 降级路径...`），防止 copy-paste 豁免 |

## 运行时陷阱（第三方库）

| # | 陷阱 | 正确做法 |
|---|------|----------|
| 18 | **docling-parse C++ 层无法处理含非 ASCII 字符的安装路径**（Windows ANSI fopen）：项目/虚拟环境路径含中文时，docling 加载自身资源文件（`pdf_resources/glyphs/*.dat`）会报 `filename does not exists`，PDF 转换 100% 失败（2026-08 实测） | ① 项目与 venv 放在纯英文 (ASCII) 目录；② `pdf_converter.convert()` 已在非 ASCII 路径下提前抛可操作错误（非 docling 晦涩报错）；③ `test_real_conversion_with_docling` 在非 ASCII 路径下自动 skip |

## 提交前自查

```bash
python tools/check_bare_handlers.py      # 裸异常检查
python tools/check_html_escape.py        # HTML 转义合规
python tools/check_api_sync.py           # api-reference 同步
pytest tests/ -v                         # 全量测试
```

## 维护规则

- 新踩坑并验证修复后，**立即追加到本表**（附真实案例与正确做法）
- 语言级陷阱（Python falsy 等）维护在 `rules/falsy-pitfalls.md` 与 `skills/python-SKILL.md`，本表不重复
- 项目专属坑位（非通用）写入 AGENTS.md「历史经验」章节，不放本文件
