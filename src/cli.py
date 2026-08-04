"""CLI 命令行入口 — 单文件和批量审查"""

import sys
import logging
import argparse
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

from src.engines.pipeline import CONVERTERS, find_converter, build_auditors, run_auditors
from src.models.document import Document
from src.models.finding import AuditFinding, FindingSeverity
from src.reporters.html_reporter import generate_html_report
from src.reporters.json_reporter import generate_json_report

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
        "structure": "结构审查", "format": "格式审查", "language": "语言审查",
        "terminology": "术语检查", "factual": "事实审查", "custom": "自定义规则",
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

    print(f"\n{'='*60}")
    print(f"[SUMMARY] Audit complete: {len(findings)} findings")
    print(f"   [ERROR] {len(errors)}")
    print(f"   [WARN]  {len(warnings)}")
    print(f"   [INFO]  {len(infos)}")
    print(f"{'='*60}")

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


def main():
    parser = argparse.ArgumentParser(
        description="DocAudit — 本地离线文档审查系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  doc-audit report.pptx                    审查单个文件
  doc-audit report.pptx -o report.html     导出 HTML 报告
  doc-audit docs/ --rules my-rules.md      批量审查目录，使用自定义规则
  doc-audit report.pptx --fix              审查并自动修复格式问题
        """,
    )
    parser.add_argument("path", help="文件或目录路径")
    parser.add_argument("--rules", default="rules.md", help="自定义规则文件 (默认: rules.md)")
    parser.add_argument("--glossary", default="glossary", help="术语表目录 (默认: glossary)")
    parser.add_argument("--vocab", default=None, help="词汇表目录 (默认: glossary 同级 vocab/ 目录)")
    parser.add_argument("-o", "--output", help="输出报告文件 (.html 或 .json)")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    parser.add_argument("--format", choices=["pptx", "docx", "pdf", "md", "all"],
                        default="all", help="按格式过滤 (批量模式)")
    parser.add_argument("--fix", action="store_true",
                        help="自动修复简单格式问题 (字体标准化、字号修正)")
    parser.add_argument("--fix-type", choices=["all", "font", "spacing", "overflow", "title_punct", "bullet"],
                        default="all",
                        help="指定修复类型 (默认: all)。font=字体+字号, spacing=中英文间距, "
                             "overflow=元素溢出, title_punct=标题标点, bullet=项目符号")

    args = parser.parse_args()

    # 收集文件
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
            print(f"[ERROR] No supported documents found in directory")
            sys.exit(1)
        print(f"[SCAN] Found {len(files)} files")
    else:
        print(f"[ERROR] Path not found: {args.path}")
        sys.exit(1)

    # 处理每个文件
    total_findings = []
    for i, file_path in enumerate(files, 1):
        if len(files) > 1:
            print(f"\n[{i}/{len(files)}] {'='*40}")

        try:
            doc, findings = audit_file(
                str(file_path),
                rules_path=args.rules,
                glossary_dir=args.glossary,
                vocab_dir=args.vocab,
                verbose=args.verbose,
            )
            total_findings.extend(findings)
            print_summary(findings)

            # Auto-fix (inspired by intern)
            if args.fix and doc.format in ("pptx", "docx"):
                from src.engines.autofix import AutoFixer
                from src.engines.rule_parser import parse_rules_md, extract_auditor_config
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

            # 导出报告 — 批量模式每文件独立命名，单文件保持不变
            if args.output:
                out_path = Path(args.output)
                if len(files) > 1:
                    # 仅多文件时添加序号后缀
                    stem, suffix = out_path.stem, out_path.suffix
                    out_path = out_path.parent / f"{stem}_{i:02d}{suffix}"
                if out_path.suffix == ".html":
                    generate_html_report(doc, findings, output_path=out_path)
                    print(f"\n[EXPORT] HTML report saved: {out_path}")
                elif out_path.suffix == ".json":
                    generate_json_report(doc, findings, output_path=out_path)
                    print(f"\n[EXPORT] JSON report saved: {out_path}")

        except Exception as e:
            print(f"[ERROR] Processing failed: {file_path} -- {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()

    # 批量总结
    if len(files) > 1:
        print(f"\n{'='*60}")
        print(f"[BATCH] {len(files)} files audited, {len(total_findings)} total findings")
        print(f"{'='*60}")

    # ── Exit code 按严重度 (inspired by markdownlint) ──
    errors = [f for f in total_findings if f.severity == FindingSeverity.ERROR]
    warnings = [f for f in total_findings if f.severity == FindingSeverity.WARNING]
    if errors:
        print(f"\n[EXIT] {len(errors)} error(s) found → exit 1")
        sys.exit(1)
    elif warnings:
        print(f"\n[EXIT] {len(warnings)} warning(s), no errors → exit 0")
        sys.exit(0)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
