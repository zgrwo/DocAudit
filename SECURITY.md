# 安全策略（Security Policy）

## 支持版本

| 版本 | 支持 |
| :--- | :--- |
| 0.3.x | ✅ 接收安全报告与修复 |
| < 0.3 | ❌ 建议升级到最新 0.3.x |

## 报告漏洞

**请勿通过公开 Issue 报告安全问题。** 请使用 GitHub 的私密漏洞报告：

> <https://github.com/zgrwo/DocAudit/security/advisories/new>

报告请包含：影响版本、复现步骤（最小文档/命令）、影响面（数据外传 / 任意文件读写 / XSS / DoS）、
以及你建议的修复方向。我们会在 7 天内确认、30 天内给出修复或缓解计划（本地单人维护项目，
以实际排期为准）。

## 威胁模型（重要）

DocAudit 是**本地离线桌面工具**，不是多租户网络服务：

- Streamlit 默认只绑定 `localhost`（`.streamlit/config.toml`），文档不上传任何服务器；
- 使用者 = 本机用户，本身已具备该机器的文件读取权限；
- 因此"用户选择一个本地文件夹进行扫描"（`app.py::scan_folder`）是**产品功能**，不是越权；
  但仍做最小化沙箱：拒绝 `..` 路径段、必须为已存在目录、只取单层且仅支持扩展名，
  并对路径做 `expanduser().resolve()` 归一化后再进行文件系统操作。
- 若你把 Web UI 暴露到非本机网络（不推荐），请自行加认证/反代，并视"可指定任意本地路径"
  为已知风险（建议只允许固定的文档根目录）。

## 安全设计要点

| 面 | 措施 |
| :--- | :--- |
| 离线 | 无遥测/无云端 API；LanguageTool 仅连 localhost；PDF/HF 模型离线缓存 |
| 报告 XSS | 所有用户可控文本经 `html.escape()`（`tests/test_html_report_security.py` 载荷测试 + 门禁） |
| 路径 | 扫描路径沙箱（`..`/非目录/单层）；临时文件用后即删 |
| 依赖 | `requirements-*.txt` 锁文件 + `check_release.py` 的 lock_cache 完整性检查；Dependabot 告警/安全更新已启用；CodeQL 每周 + PR 扫描 |
| 供应链 | Actions 固定 commit SHA；PR 合并需通过 CI 必需检查与线性历史（main 分支保护） |
| 上传 | Streamlit 文件上传仅写临时文件并转换后删除；显示原始文件名 |

## 已知限制 / 非目标

- 审查结果是**启发式**的（正则/计数/几何估算），不构成内容正确性或合规性担保；
- `--fix` 自动修复只做格式层修正，不校验业务语义；
- 大版本 PDF 依赖栈升级需在 ASCII 路径环境做真实回归（见 Issue #43）。
