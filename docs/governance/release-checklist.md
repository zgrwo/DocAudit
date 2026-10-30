# 发行标准与检查清单

> 本文是 DocAudit 的**发行唯一标准**（SSOT）。任何版本发布前必须逐项通过；
> 机器可判定部分由 `python scripts/check_release.py` 自动检查，其余为人工确认。
> 历史检查记录见 `docs/governance/archive/handoff-*.md`（logs/ 内审查报告不入库）。

## 1. 发行标准（全部必须通过）

| # | 标准 | 验证方式 | 自动? |
|---|------|----------|-------|
| R1 | 全量测试通过（0 failed，skip 必须全部是环境性） | `pytest tests/ -q` | ✅ CI |
| R2 | 治理四门禁通过（裸异常/HTML 转义/api 同步/文档数字）+ 发行门禁（版本双源/CHANGELOG 发行头/3.10 语法） | `pytest tests/test_gates.py -q` | ✅ |
| R3 | 覆盖率不低于门槛（当前 82%，实测 89%） | `pytest --cov=src --cov-fail-under=82` | ✅ CI |
| R4 | ruff check + format 全绿 | `ruff check src/ tests/ scripts/ app.py` / `ruff format --check ...` | ✅ CI |
| R5 | DISPATCH 完整性 | `docaudit` 内 `validate_dispatch()` 返回 `[]` | ✅ CI |
| R6 | 配置校验零告警 | `python src/cli.py rules validate` | ✅ CI |
| R7 | 版本号双源一致（pyproject = `src.__version__`）且语义化 | `python scripts/check_release.py` | ✅ |
| R8 | CHANGELOG 顶部为当前版本段（`## [x.y.z] - 日期`），无 `[Unreleased]` 残留 | 同上 | ✅ |
| R9 | 版本号与 CHANGELOG/文档一致（specification 版本头、README 测试数等） | 文档数字门禁（R2） | ✅ |
| R10 | wheel 可离线构建且 CLI 可导入（wheel 只含 Python 包：CLI/库） | `python -m pip wheel . --no-deps --no-build-isolation -w dist/` | 人工 |
| R10b | 源码发行包（sdist/tag 归档）包含完整应用：`app.py`、`rules.md`、`glossary/`、`vocab/`、`docs/` | `git archive vX.Y.Z` 内容检查 + `MANIFEST.in` | 人工 |
| R11 | Python 3.10 语法兼容（CI 矩阵最低版本） | `tests/test_gates.py::test_python310_syntax_compatible` | ✅ |
| R12 | CLI 冒烟：`--version` / `doctor` / 单文件审查 / 四格式导出 | `python scripts/check_release.py` + 手工 4 命令 | 部分 |
| R13 | 全平台 CI 绿（Linux 3.10–3.14 + Windows 锁文件任务） | GitHub Actions | ✅ CI |
| R14 | 工作区干净、改动已提交；tag `vX.Y.Z` 指向发行提交 | `git status` / `git rev-parse` | 人工 |
| R15 | `git push` 已获得用户明确同意（红线） | — | 人工 |

## 2. 发行步骤

```bash
# 1) 定版：pyproject.toml 与 src/__init__.py 同步改版本
# 2) CHANGELOG：把 [Unreleased] 改为 ## [X.Y.Z] - YYYY-MM-DD 并补摘要
# 3) 机器自检
python scripts/check_release.py
# 4) 全量验证
pytest tests/ -q
pytest --cov=src --cov-fail-under=82
ruff check src/ tests/ scripts/ app.py && ruff format --check src/ tests/ scripts/ app.py
python -c "from src.auditors.custom_rules import CustomRulesAuditor; assert CustomRulesAuditor.validate_dispatch()==[]"
python src/cli.py rules validate
# 5) 打包验证（离线可用 --no-build-isolation）
python -m pip wheel . --no-deps --no-build-isolation -w dist/
# 6) 提交 + 打 tag
git add -A && git commit -m "release: vX.Y.Z"
git tag -a vX.Y.Z -m "DocAudit vX.Y.Z"
# 7) push 前必须获得用户明确同意
```

## 3. 版本策略

- 语义化版本 `MAJOR.MINOR.PATCH`；本项目 1.0 前：功能批次升 **MINOR**，修复升 PATCH。
- 发行提交后立即在 CHANGELOG 顶部新建 `## [Unreleased]` 段（下一轮变更入口）。
- 版本号唯一来源：`pyproject.toml`；`src/__init__.py.__version__` 必须与之同步（门禁强制）。

## 4. 回滚

- 未 push：`git tag -d vX.Y.Z` + `git reset --hard HEAD~1`（仅限本地，确认后执行）。
- 已发行：发 PATCH 版本回滚缺陷，不移动既有 tag（避免下游缓存不一致）。

## 4.1 5S 例行清理（每次发行前 / 大改动后）

| 步骤 | 动作 | 检查命令 |
| :--- | :--- | :--- |
| **整理** (Seiri) | 删除无引用文件/函数/配置：零引用的脚本、未被测试或文档引用的 fixture、未接入的可选配置（如未接 CI 的 Vale `styles/` + `.vale.ini`） | `Select-String <name> src/ tests/ docs/ scripts/ app.py` 零命中即候选 |
| **整顿** (Seiton) | 历史文档归档到 `docs/governance/archive/`；工具脚本进 `scripts/`、数据进 `tests/fixtures/`；生成物回到文档声明位置（`packages/` 在根） | 对照 `project-structure.md` 目录树 |
| **清扫** (Seiso) | 删除生成物：`build/`、`*.egg-info/`、`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`.coverage`；跑 `ruff format` + `ruff check` | `git status --ignored` 只剩 `.venv/ packages/ logs/` |
| **清洁** (Seiketsu) | `.gitignore` 覆盖全部生成物；无用配置/依赖同步删除；文档索引同步归档路径 | `python scripts/check_release.py` + 文档门禁 |
| **素养** (Shitsuke) | 5S 结果记入 `logs/reports/`；本表与 `project-structure.md` 同步；禁止把临时产物留在仓库根 | 本轮审查报告附录 |

> 历史教训：`scripts/packages/` 曾积累 391MB 旧离线包且与文档声明的根 `packages/` 不符；
> `styles/` + `.vale.ini` 为未接入 CI 的可选配置却长期占位；`masked_spans()` / `_extract_keys()`
> 重构后残留死代码。均已于 2026-11 5S 轮清理。

## 4.2 依赖刷新流程（Dependabot PR / 手动升级共用）

> 2026-11 教训：Dependabot 直接改**生成物** `requirements-*.txt`，与生成流程冲突
> （tokenizers/transformers 钉死冲突致 lockfile job 红）；且 `packages/` 曾缺 15 个锁文件
> pin，离线安装实际会失败。锁文件与缓存必须成对维护。

| 步骤 | 命令 | 通过标准 |
| :--- | :--- | :--- |
| 1. 补缓存 | `pip download --no-deps --dest packages <pkg>==<ver>`（连同其新版本依赖） | 新版本 wheel 落到 `packages/` |
| 2. 重建锁文件 | `python scripts/gen_requirements_lock.py` | 3 个 profile 均 `[OK]` |
| 3. 缓存完整性 | `python scripts/check_release.py` | `lock_cache` PASS（所有 pin 命中 packages/） |
| 4. 实装验证 | `pip install <升级包>` 后 `pytest tests/ -q` | 全绿（含 AppTest） |
| 5. 离线解析 | `pip install --dry-run --no-index --find-links=packages -r requirements-full.txt .` | `Would install` 出现 |
| 6. 提交 | `git add requirements-*.txt pyproject.toml`（packages/ 是 gitignore 生成物） | lockfile job 绿 |

- Dependabot 策略（`.github/dependabot.yml`）：仅 `dependency-type: direct` + `groups`，
  避免再产生"只改生成锁文件"的 PR；直接依赖 PR 也需走本流程。
- 大版本（如 docling-ibm-models 3→4、transformers 5.x 簇）需在**装了 pdf extra 的 ASCII 路径**
  环境做真实 PDF 回归后再合并，不能只看单元测试。

## 5. 当前发行状态

| 项 | 状态 |
|---|---|
| 版本 | `0.3.3`（2026-11-05，安全质量补齐版） |
| 测试 | 739 passed, 2 skipped（741 collected，~80s） |
| 覆盖率 | 89%（门槛 82%） |
| ruff / 门禁 / 配置校验 | 全绿 |
| wheel 构建 | 已验证可离线构建（当前 `src/` 布局，见 `pip wheel .`） |
| 源码包 | `MANIFEST.in` 覆盖 app.py/rules.md/glossary/vocab/docs/skills/scripts/tests |
| tag | `v0.3.3`（已 push） |

<!-- last_updated: 2026-11-05 -->
