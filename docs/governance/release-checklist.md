# 发行标准与检查清单

> 本文是 DocAudit 的**发行唯一标准**（SSOT）。任何版本发布前必须逐项通过；
> 机器可判定部分由 `python scripts/check_release.py` 自动检查，其余为人工确认。
> 历史检查记录见 `docs/governance/handoff-*.md`（logs/ 内审查报告不入库）。

## 1. 发行标准（全部必须通过）

| # | 标准 | 验证方式 | 自动? |
|---|------|----------|-------|
| R1 | 全量测试通过（0 failed，skip 必须全部是环境性） | `pytest tests/ -q` | ✅ CI |
| R2 | 治理四门禁通过（裸异常/HTML 转义/api 同步/文档数字）+ 发行门禁（版本双源/CHANGELOG 发行头/3.10 语法） | `pytest tests/test_gates.py -q` | ✅ |
| R3 | 覆盖率不低于门槛（当前 82%，实测 87%） | `pytest --cov=src --cov-fail-under=82` | ✅ CI |
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

## 5. 当前发行状态

| 项 | 状态 |
|---|---|
| 版本 | `0.2.0`（2026-10-29） |
| 测试 | 597 passed, 2 skipped（599 collected，~63s） |
| 覆盖率 | 87%（门槛 82%） |
| ruff / 门禁 / 配置校验 | 全绿 |
| wheel 构建 | 已验证可离线构建（docaudit-0.2.0-py3-none-any.whl，41 文件，含 src/） |
| 源码包 | `MANIFEST.in` 覆盖 app.py/rules.md/glossary/vocab/docs/skills/scripts/tests |
| tag | `v0.2.0`（本地；未 push） |

<!-- last_updated: 2026-10-29 -->
