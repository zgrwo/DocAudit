# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- 53 个测试用例（模型/审计器/引擎/规则/集成）

<!-- [0.1.0]: https://github.com/zgrwo/DocAudit/releases/tag/v0.1.0 -->
