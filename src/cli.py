"""CLI 命令行入口 — 单文件和批量审查"""

import argparse
import logging
import sys
from pathlib import Path

# 修复 Windows GBK 终端输出问题
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

# 支持 `python src/cli.py` 直接运行 (pip 安装后 src/ 已在 path 中，仅直接运行时补充)
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engines.exemptions import apply_exemptions, load_exemptions
from src.engines.pipeline import build_auditors, find_converter, run_auditors
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity
from src.reporters.csv_reporter import generate_csv_report
from src.reporters.html_reporter import generate_html_report
from src.reporters.json_reporter import generate_json_report
from src.reporters.sarif_reporter import generate_sarif_report

REPORT_SUFFIXES = (".html", ".json", ".sarif", ".csv")

# 严重度排序 (--fail-on 阈值判定用)
_SEVERITY_RANK = {"error": 3, "warning": 2, "info": 1}


def _findings_exit_code(findings: list[AuditFinding], fail_on: str = "error") -> int:
    """按 --fail-on 阈值决定退出码：none → 0；否则任一 finding 达到阈值 → 1。"""
    if fail_on == "none":
        return 0
    min_rank = _SEVERITY_RANK.get(fail_on, 3)
    return 1 if any(_SEVERITY_RANK.get(f.severity.value, 0) >= min_rank for f in findings) else 0


logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("doc-audit")


def audit_file(
    file_path: str,
    rules_path: str = "rules.md",
    glossary_dir: str = "glossary",
    vocab_dir: str | None = None,
    verbose: bool = False,
) -> tuple[Document, list[AuditFinding]]:
    """审查单个文件，返回 (doc, findings)"""
    if verbose:
        logging.getLogger().setLevel(logging.INFO)

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    # 转换
    converter = find_converter(file_path)
    if converter is None:
        raise ValueError(f"不支持的文件格式: {path.suffix}")

    print(f"[DOC] 解析: {path.name}")
    doc = converter.convert(str(path))
    print(f"   格式: {doc.format.upper()}, 共 {len(doc.pages)} 页")

    # 审查 — 从 rules.md 加载配置 (使用共享流水线, 全部解析为绝对路径)
    auditors = build_auditors(
        str(Path(rules_path).resolve()),
        str(Path(glossary_dir).resolve()),
        str(Path(vocab_dir).resolve()) if vocab_dir else None,
    )

    all_findings = run_auditors(doc, auditors)

    # 按发现类型统计（CustomRulesAuditor dispatch 的结果保留原始类型，无法按审计器拆分）
    type_counts: dict[str, int] = {}
    for f in all_findings:
        type_counts[f.type.value] = type_counts.get(f.type.value, 0) + 1
    type_labels = {
        "structure": "结构审查",
        "format": "格式审查",
        "language": "语言审查",
        "terminology": "术语检查",
        "factual": "事实审查",
        "custom": "自定义规则",
        "system": "系统错误",
    }
    for t, count in sorted(type_counts.items()):
        label = type_labels.get(t, t)
        print(f"   {label}: {count} 个发现")

    return doc, all_findings


def print_summary(findings: list[AuditFinding]) -> None:
    """打印审查结果摘要"""
    errors = [f for f in findings if f.severity == FindingSeverity.ERROR]
    warnings = [f for f in findings if f.severity == FindingSeverity.WARNING]
    infos = [f for f in findings if f.severity == FindingSeverity.INFO]

    print(f"\n{'=' * 60}")
    print(f"[SUMMARY] Audit complete: {len(findings)} findings")
    print(f"   [ERROR] {len(errors)}")
    print(f"   [WARN]  {len(warnings)}")
    print(f"   [INFO]  {len(infos)}")
    print(f"{'=' * 60}")

    if errors:
        print("\n--- Errors ---")
        for f in errors[:10]:
            print(f"   [{f.rule_id or '?'}] {f.message[:100]}")
            if f.location:
                print(f"        @ {f.location}")
        if len(errors) > 10:
            print(f"   ... {len(errors)} total, showing first 10")

    if warnings:
        print("\n--- Warnings ---")
        for f in warnings[:5]:
            print(f"   [{f.rule_id or '?'}] {f.message[:100]}")
        if len(warnings) > 5:
            print(f"   ... {len(warnings)} total, showing first 5")

    if infos:
        print(f"\n--- Info: {len(infos)} items ---")


def doctor_check() -> int:
    """环境诊断：检查运行环境健康状态。"""
    import importlib

    checks_passed = 0
    checks_failed = 0
    checks_optional_failed = 0

    def _check(name: str, ok: bool, detail: str = "", optional: bool = False) -> None:
        nonlocal checks_passed, checks_failed, checks_optional_failed
        if not ok and optional:
            # 可选依赖/服务缺失不应让 core-only 环境整体失败 (exit 1)。
            checks_optional_failed += 1
            suffix = f" ({detail})" if detail else ""
            print(f"  [WARN] {name}{suffix}")
            return
        status = "PASS" if ok else "FAIL"
        if not ok:
            checks_failed += 1
        else:
            checks_passed += 1
        suffix = f" ({detail})" if detail else ""
        print(f"  [{status}] {name}{suffix}")

    print("DocAudit Environment Doctor")
    print("=" * 40)

    # 1. Python version
    py_version = sys.version_info
    py_ok = py_version >= (3, 10)
    _check(
        "Python version",
        py_ok,
        f"{py_version.major}.{py_version.minor}.{py_version.micro} (>= 3.10 required)",
    )

    # 2. Core dependencies
    core_deps = [
        ("streamlit", "streamlit"),
        ("python-pptx", "pptx"),
        ("python-docx", "docx"),
        ("pyyaml", "yaml"),
        ("requests", "requests"),
        ("pyspellchecker", "spellchecker"),
    ]
    for display_name, module_name in core_deps:
        try:
            importlib.import_module(module_name)
            _check(f"Dependency: {display_name}", True)
        except ImportError:
            _check(f"Dependency: {display_name}", False, "pip install docaudit")

    # 3. Optional dependencies
    optional_deps = [("docling (PDF)", "docling"), ("pandas", "pandas")]
    for display_name, module_name in optional_deps:
        try:
            importlib.import_module(module_name)
            _check(f"Optional: {display_name}", True, optional=True)
        except ImportError:
            _check(
                f"Optional: {display_name}",
                False,
                "pip install docaudit[pdf]",
                optional=True,
            )

    # 4. rules.md parseable
    rules_path = Path("rules.md")
    if rules_path.exists():
        try:
            from src.engines.rule_parser import parse_rules_md

            rules = parse_rules_md(str(rules_path))
            _check("rules.md parsing", True, f"{len(rules)} rules loaded")
        except Exception as e:
            _check("rules.md parsing", False, str(e)[:80])
    else:
        _check("rules.md parsing", False, "file not found")

    # 5. Glossary YAML files
    glossary_path = Path("glossary")
    if glossary_path.is_dir():
        yaml_files = list(glossary_path.glob("*.yaml"))
        if yaml_files:
            try:
                import yaml

                for yf in yaml_files:
                    yaml.safe_load(yf.read_text(encoding="utf-8"))
                _check("Glossary YAML files", True, f"{len(yaml_files)} files loaded")
            except Exception as e:
                _check("Glossary YAML files", False, str(e)[:80])
        else:
            _check("Glossary YAML files", False, "no .yaml files found")
    else:
        _check("Glossary YAML files", False, "glossary/ directory not found")

    # 6. LanguageTool connectivity (optional)
    try:
        import requests as req

        resp = req.get("http://localhost:8010/v2/languages", timeout=3)
        if resp.status_code == 200:
            _check("LanguageTool server", True, "localhost:8010 reachable", optional=True)
        else:
            _check("LanguageTool server", False, f"HTTP {resp.status_code}", optional=True)
    except Exception:
        _check(
            "LanguageTool server",
            False,
            "not reachable (optional: docker-compose up)",
            optional=True,
        )

    # 7. Configuration validation (rules/glossary/vocab, 2026-10-29)
    if rules_path.exists():
        try:
            from src.engines.validation import validate_configuration

            vocab_path = Path("vocab")
            result = validate_configuration(
                rules_path,
                glossary_path if glossary_path.is_dir() else None,
                vocab_path if vocab_path.is_dir() else None,
            )
            detail = (
                f"{len(result.warnings)} warning(s)"
                if result.ok
                else f"{len(result.errors)} error(s)"
            )
            _check("Configuration validation", result.ok, detail)
            for err in result.errors[:3]:
                print(f"       - {err}")
        except Exception as e:
            _check("Configuration validation", False, str(e)[:80])

    # Summary
    print(f"\n{'=' * 40}")
    print(
        f"Result: {checks_passed} passed, {checks_failed} failed"
        + (f", {checks_optional_failed} optional unavailable" if checks_optional_failed else "")
    )
    return 1 if checks_failed > 0 else 0


def main():
    parser = argparse.ArgumentParser(
        description="DocAudit — 本地离线文档审查系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  docaudit report.pptx                    审查单个文件
  docaudit report.pptx -o report.html     导出 HTML 报告
  docaudit docs/ --rules my-rules.md      批量审查目录，使用自定义规则
  docaudit report.pptx --fix              审查并自动修复格式问题
  docaudit report.pptx --fail-on none     从不因问题失败（仅处理失败时 exit 1）
  docaudit doctor                         环境诊断
  docaudit rules validate                 校验 rules.md / glossary / vocab 配置
        """,
    )
    subparsers = parser.add_subparsers(dest="command")

    # doctor subcommand
    subparsers.add_parser("doctor", help="环境诊断：检查运行环境健康状态")

    # rules subcommand (配置工具)
    rules_parser = subparsers.add_parser("rules", help="规则配置工具")
    rules_sub = rules_parser.add_subparsers(dest="rules_command")
    validate_parser = rules_sub.add_parser("validate", help="静态校验配置（退出码 1 = 有错误）")
    validate_parser.add_argument("--rules", default="rules.md", help="规则文件 (默认: rules.md)")
    validate_parser.add_argument("--glossary", default="glossary", help="术语表目录")
    validate_parser.add_argument("--vocab", default="vocab", help="词汇表目录")
    list_parser = rules_sub.add_parser("list", help="列出 rules.md 中的规则")
    list_parser.add_argument("--rules", default="rules.md", help="规则文件 (默认: rules.md)")

    # audit (default) arguments
    audit_parser = subparsers.add_parser("audit", help="审查文档")
    audit_parser.add_argument("path", help="文件或目录路径")
    audit_parser.add_argument("--rules", default="rules.md", help="自定义规则文件 (默认: rules.md)")
    audit_parser.add_argument("--glossary", default="glossary", help="术语表目录 (默认: glossary)")
    audit_parser.add_argument("--vocab", default=None, help="词汇表目录")
    audit_parser.add_argument("-o", "--output", help="输出报告文件 (.html 或 .json)")
    audit_parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    audit_parser.add_argument(
        "--format",
        choices=["pptx", "docx", "pdf", "md", "all"],
        default="all",
        help="按格式过滤 (批量模式)",
    )
    audit_parser.add_argument("--fix", action="store_true", help="自动修复简单格式问题")
    audit_parser.add_argument(
        "--fail-on",
        choices=["error", "warning", "info", "none"],
        default="error",
        help="达到该严重度即退出码 1（默认 error；none 表示从不因问题失败，仅处理失败时 1）",
    )
    audit_parser.add_argument(
        "--exempt-file",
        default=None,
        help="豁免文件路径 (如 .docauditignore)；命中的 exemption_key 不计入报告与退出码",
    )
    audit_parser.add_argument(
        "--sarif-base",
        default=None,
        help="SARIF artifact 路径基准目录（CI 传仓库根如 .，输出仓库相对路径供 Code Scanning 关联）",
    )
    audit_parser.add_argument(
        "--thumbnails",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="HTML 报告是否内嵌页面 SVG 线框缩略图 (默认开启)",
    )
    audit_parser.add_argument(
        "--fix-type",
        choices=["all", "font", "spacing", "overflow", "title_punct", "bullet"],
        default="all",
        help="指定修复类型 (默认: all)",
    )

    # Backward compat: if first arg looks like a path, treat as audit
    try:
        # 抑制首次解析的报错噪音 (此阶段唯一报错场景是位置参数被误判为
        # 子命令的 invalid choice，由下方回退接管；--help 正常输出不受影响)
        import contextlib
        import io

        with contextlib.redirect_stderr(io.StringIO()):
            args, remaining = parser.parse_known_args()
    except SystemExit as e:
        # --help 正常输出后直接退出；参数错误 (exit code 2) 才回退
        if e.code == 0:
            raise
        # 显式子命令 (audit/doctor) 的参数错误 → 严格重解析，
        # 交还 argparse 报标准用法错误 (exit 2)，不回退为 audit
        first = sys.argv[1] if len(sys.argv) > 1 else ""
        if first in ("audit", "doctor", "rules"):
            parser.parse_args()
        # 位置参数 (如 "docaudit report.pptx") 会被子命令解析器视为
        # invalid choice 而报错退出 → 回退为按 audit 子命令重新解析
        args = audit_parser.parse_args()
        args.command = "audit"

    if args.command == "doctor":
        sys.exit(doctor_check())

    if args.command == "rules":
        rules_command = getattr(args, "rules_command", None)
        if rules_command == "list":
            from src.engines.rule_parser import parse_rules_md

            rules = parse_rules_md(args.rules)
            if not rules:
                print(f"[ERROR] 未解析到规则: {args.rules}")
                sys.exit(1)
            print(f"[RULES] 共 {len(rules)} 条 · {args.rules}")
            print(f"{'规则ID':<12} {'严重度':<8} {'检查/模式':<32} 说明")
            print("-" * 96)
            for rule in rules:
                kind = rule.check_type or "（内置参数）"
                print(f"{rule.rule_id:<12} {rule.severity:<8} {kind:<32} {rule.description[:40]}")
            sys.exit(0)
        if rules_command != "validate":
            rules_parser.print_help()
            print("\n[ERROR] 需要子命令: docaudit rules validate | list")
            sys.exit(2)
        from src.engines.validation import validate_configuration

        result = validate_configuration(args.rules, args.glossary, args.vocab)
        print(f"[VALIDATE] rules={args.rules} glossary={args.glossary} vocab={args.vocab}")
        for line in result.to_lines():
            print(line)
        if not result.ok:
            print(
                f"[VALIDATE] FAILED — {len(result.errors)} error(s), "
                f"{len(result.warnings)} warning(s)"
            )
            sys.exit(1)
        print(f"[VALIDATE] OK — {len(result.warnings)} warning(s)")
        sys.exit(0)

    # 无子命令但存在未知选项 → 严格报错 (exit 2)，不静默接受
    if args.command is None and remaining:
        parser.error(f"unrecognized arguments: {' '.join(remaining)}")

    if args.command != "audit":
        parser.print_help()
        sys.exit(0)

    # -o 仅支持 .html/.json/.sarif/.csv (M9: 其他扩展名 → 用法错误 exit 2)
    if args.output and Path(args.output).suffix not in REPORT_SUFFIXES:
        print(
            f"[ERROR] 不支持的输出格式: {Path(args.output).suffix}"
            f"（仅支持 {' / '.join(REPORT_SUFFIXES)}）"
        )
        sys.exit(2)

    # Collect files
    path = Path(args.path)
    files: list[Path] = []

    if path.is_file():
        files = [path]
    elif path.is_dir():
        from src.engines.pipeline import SUPPORTED_EXTENSIONS

        if args.format != "all":
            patterns = [f"*.{args.format}"]
        else:
            patterns = [f"*{ext}" for ext in SUPPORTED_EXTENSIONS]
        for pat in patterns:
            files.extend(path.glob(pat))
        files = sorted(files)
        if not files:
            print("[ERROR] No supported documents found in directory")
            sys.exit(1)
        print(f"[SCAN] Found {len(files)} files")
    else:
        print(f"[ERROR] Path not found: {args.path}")
        sys.exit(1)

    # 处理每个文件
    total_findings = []
    failed_files = 0  # 处理失败的文件数 (README: 处理失败 → 退出码 1)
    last_doc: Document | None = None  # SARIF 聚合写入需要文档元数据 (工具/artifact)
    exempt_keys = load_exemptions(args.exempt_file) if args.exempt_file else set()
    exempted_total = 0
    for i, file_path in enumerate(files, 1):
        if len(files) > 1:
            print(f"\n[{i}/{len(files)}] {'=' * 40}")

        try:
            doc, findings = audit_file(
                str(file_path),
                rules_path=args.rules,
                glossary_dir=args.glossary,
                vocab_dir=args.vocab,
                verbose=args.verbose,
            )
            # 豁免文件命中项不计入报告/退出码 (--exempt-file)
            if exempt_keys:
                findings, exempted = apply_exemptions(findings, exempt_keys)
                exempted_total += exempted
                if exempted:
                    print(f"[EXEMPT] {exempted} finding(s) exempted by {args.exempt_file}")
            # 批量时给 finding 标注来源文件 (2026-10-29)：
            # 聚合 SARIF 的 artifact 归属依赖它；否则全部指向最后一个文件。
            if len(files) > 1:
                for _f in findings:
                    if _f.metadata is None:
                        _f.metadata = {}
                    _f.metadata["source_file"] = str(file_path)
            total_findings.extend(findings)
            print_summary(findings)

            # Auto-fix (inspired by intern)
            if args.fix and doc.format in ("pptx", "docx"):
                from src.engines.autofix import AutoFixer
                from src.engines.rule_parser import extract_auditor_config, parse_rules_md

                out = file_path.parent / f"{file_path.stem}_fixed{file_path.suffix}"
                # 从 rules.md 读取允许字体列表（配置驱动，非硬编码）
                rules = parse_rules_md(args.rules)
                auditor_config = extract_auditor_config(rules)
                fix_allowed_fonts = auditor_config.get("allowed_fonts")
                fixer = AutoFixer(allowed_fonts=fix_allowed_fonts)
                total_fixes = 0
                output_written = False  # 跟踪 out 文件是否已被写（首个 fix 步骤后置 True）
                fix_type = args.fix_type
                fix_details: list[str] = []  # 每步修复明细

                # 1. 字体 + 字号修复
                if fix_type in ("all", "font"):
                    if doc.format == "pptx":
                        fixer.fix_pptx(file_path, out)
                    else:
                        fixer.fix_docx(file_path, out)
                    total_fixes += fixer.fix_count
                    if fixer.fix_count:
                        fix_details.append(f"字体/字号: {fixer.fix_count} 处")
                    output_written = True

                # 2. 中英文间距修复
                if fix_type in ("all", "spacing"):
                    if output_written:
                        # 链式修复: 在前一步输出基础上继续
                        fixer.fix_spacing(out, out)
                    else:
                        fixer.fix_spacing(file_path, out)
                        output_written = True
                    total_fixes += fixer.fix_count
                    if fixer.fix_count:
                        fix_details.append(f"中英文间距: {fixer.fix_count} 处")

                # 3. 元素溢出修复 (PPTX only)
                if fix_type in ("all", "overflow") and doc.format == "pptx":
                    if output_written:
                        fixer.fix_element_overflow(out, out)
                    else:
                        fixer.fix_element_overflow(file_path, out)
                        output_written = True
                    total_fixes += fixer.fix_count
                    if fixer.fix_count:
                        fix_details.append(f"元素溢出: {fixer.fix_count} 处")

                # 4. 标题标点修复 (PPTX only)
                if fix_type in ("all", "title_punct") and doc.format == "pptx":
                    if output_written:
                        fixer.fix_title_punctuation(out, out)
                    else:
                        fixer.fix_title_punctuation(file_path, out)
                        output_written = True
                    total_fixes += fixer.fix_count
                    if fixer.fix_count:
                        fix_details.append(f"标题标点: {fixer.fix_count} 处")

                # 5. 项目符号统一 (PPTX only)
                if fix_type in ("all", "bullet") and doc.format == "pptx":
                    if output_written:
                        fixer.fix_bullet_style(out, out)
                    else:
                        fixer.fix_bullet_style(file_path, out)
                        output_written = True
                    total_fixes += fixer.fix_count
                    if fixer.fix_count:
                        fix_details.append(f"项目符号: {fixer.fix_count} 处")

                if total_fixes > 0:
                    detail_str = " | ".join(fix_details) if fix_details else ""
                    print(f"\n[FIX] 自动修复 {total_fixes} 处问题 ({fix_type})")
                    if detail_str:
                        print(f"      明细: {detail_str}")
                    print(f"      输出: {out}")
                else:
                    print(f"\n[FIX] 未发现可自动修复的问题 ({fix_type})")
            elif args.fix:
                print(f"[FIX] 格式 {doc.format.upper()} 暂不支持自动修复（仅支持 PPTX/DOCX）")

            # 导出报告 — 批量模式每文件独立命名，单文件保持不变。
            # .sarif 例外：批量聚合到循环后写入一个文件 (CI 集成通常一次运行一个 SARIF)。
            if args.output and Path(args.output).suffix != ".sarif":
                out_path = Path(args.output)
                if len(files) > 1:
                    # 仅多文件时添加序号后缀
                    stem, suffix = out_path.stem, out_path.suffix
                    out_path = out_path.parent / f"{stem}_{i:02d}{suffix}"
                if out_path.suffix == ".html":
                    generate_html_report(
                        doc,
                        findings,
                        output_path=out_path,
                        show_thumbnails=args.thumbnails,
                    )
                    print(f"\n[EXPORT] HTML report saved: {out_path}")
                elif out_path.suffix == ".json":
                    generate_json_report(doc, findings, output_path=out_path)
                    print(f"\n[EXPORT] JSON report saved: {out_path}")
                elif out_path.suffix == ".csv":
                    generate_csv_report(findings, output_path=out_path)
                    print(f"\n[EXPORT] CSV report saved: {out_path}")
                # M6: 报告器内部吞掉 OSError，导出后必须校验产物存在，失败 → exit 1
                if not out_path.exists():
                    raise OSError(f"报告导出失败，输出文件未生成: {out_path}")
            last_doc = doc

        except Exception as e:
            failed_files += 1
            print(f"[ERROR] Processing failed: {file_path} -- {e}")
            if args.verbose:
                import traceback

                traceback.print_exc()

    # SARIF: 一次运行聚合为一个文件 (含批量所有 finding)
    if args.output and Path(args.output).suffix == ".sarif" and last_doc is not None:
        sarif_path = Path(args.output)
        try:
            generate_sarif_report(
                last_doc,
                total_findings,
                output_path=sarif_path,
                uri_base=args.sarif_base,
            )
            if not sarif_path.exists():
                raise OSError(f"报告导出失败，输出文件未生成: {sarif_path}")
            print(f"\n[EXPORT] SARIF report saved: {sarif_path}")
        except Exception as e:
            failed_files += 1
            print(f"[ERROR] Processing failed: {sarif_path} -- {e}")

    # 批量总结
    if len(files) > 1:
        print(f"\n{'=' * 60}")
        print(f"[BATCH] {len(files)} files audited, {len(total_findings)} total findings")
        print(f"{'=' * 60}")
    if exempted_total:
        print(f"[EXEMPT] 共豁免 {exempted_total} 条 finding（来源: {args.exempt_file}）")

    # ── Exit code 按严重度阈值 (默认 error，与历史行为一致；2026-10-29 增加 --fail-on) ──
    # 处理失败的文件优先置 1 (README: 处理失败 → 退出码 1)
    if failed_files:
        print(f"\n[EXIT] {failed_files} file(s) failed to process → exit 1")
        sys.exit(1)
    threshold = getattr(args, "fail_on", "error")
    errors = [f for f in total_findings if f.severity == FindingSeverity.ERROR]
    warnings = [f for f in total_findings if f.severity == FindingSeverity.WARNING]
    infos = [f for f in total_findings if f.severity == FindingSeverity.INFO]
    summary = f"{len(errors)} error(s), {len(warnings)} warning(s), {len(infos)} info"
    code = _findings_exit_code(total_findings, threshold)
    reached = code == 1
    print(
        f"\n[EXIT] {summary}; {'达到' if reached else '未达到'} --fail-on {threshold} → exit {code}"
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
