"""配置校验测试 — rules.md / glossary / vocab 的静态校验 (docaudit rules validate)。"""

import subprocess
import sys
from pathlib import Path

from src.engines.validation import (
    validate_configuration,
    validate_glossary,
    validate_rules,
    validate_vocab,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _rules_md(*rule_blocks: str, section: str = "# 结构规则") -> str:
    return f"{section}\n\n" + "\n\n".join(rule_blocks) + "\n"


def _rule(rule_id: str, *, severity="warning", check=None, extra: str = "") -> str:
    lines = [f"## {rule_id}: 测试规则", f"- 严重度: {severity}"]
    if check is not None:
        lines.append(f"- 检查: {check}")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


class TestValidateRules:
    def test_project_rules_valid(self):
        result = validate_rules(PROJECT_ROOT / "rules.md")
        assert result.ok, result.errors

    def test_missing_file(self, tmp_path):
        result = validate_rules(tmp_path / "nope.md")
        assert not result.ok
        assert "不存在" in result.errors[0]

    def test_empty_rules(self, tmp_path):
        path = _write(tmp_path / "rules.md", "# 结构规则\n\n没有规则\n")
        result = validate_rules(path)
        assert not result.ok
        assert "未解析到任何规则" in result.errors[0]

    def test_invalid_rule_id(self, tmp_path):
        path = _write(tmp_path / "rules.md", _rules_md(_rule("BADID", check="duplicate_title")))
        result = validate_rules(path)
        assert any("ID 格式非法" in e for e in result.errors)

    def test_duplicate_rule_id(self, tmp_path):
        block = _rule("STR-001", check="duplicate_title")
        path = _write(tmp_path / "rules.md", _rules_md(block, block))
        result = validate_rules(path)
        assert any("重复" in e for e in result.errors)

    def test_invalid_severity(self, tmp_path):
        path = _write(
            tmp_path / "rules.md",
            _rules_md(_rule("STR-001", severity="critical", check="duplicate_title")),
        )
        result = validate_rules(path)
        assert any("严重度" in e for e in result.errors)

    def test_unknown_check_type(self, tmp_path):
        path = _write(tmp_path / "rules.md", _rules_md(_rule("STR-001", check="no_such_check")))
        result = validate_rules(path)
        assert any("未知 check_type" in e for e in result.errors)

    def test_regex_rule_requires_pattern(self, tmp_path):
        path = _write(
            tmp_path / "rules.md", _rules_md(_rule("TERM-001", check="regex"), section="# 术语规则")
        )
        result = validate_rules(path)
        assert any("缺少" in e and "模式" in e for e in result.errors)

    def test_invalid_regex(self, tmp_path):
        path = _write(
            tmp_path / "rules.md",
            _rules_md(
                _rule("TERM-001", check="regex", extra="- 模式: '[unclosed'"), section="# 术语规则"
            ),
        )
        result = validate_rules(path)
        assert any("正则无法编译" in e for e in result.errors)

    def test_title_range_min_greater_than_max(self, tmp_path):
        path = _write(
            tmp_path / "rules.md",
            _rules_md(
                _rule(
                    "FMT-002",
                    extra="- 标题: {min: 44, max: 28}\n- 正文: {min: 12, max: 32}",
                )
            ),
        )
        result = validate_rules(path)
        assert any("min > max" in e for e in result.errors)

    def test_contrast_out_of_range(self, tmp_path):
        path = _write(
            tmp_path / "rules.md",
            _rules_md(_rule("FMT-008", check="table_contrast", extra="- 最小对比度: 99")),
        )
        result = validate_rules(path)
        assert any("WCAG" in e for e in result.errors)

    def test_native_rule_without_check_is_not_error(self, tmp_path):
        """FMT-001 无 检查:/模式: 是内置参数驱动形态，只允许出现在允许清单内。"""
        path = _write(
            tmp_path / "rules.md",
            _rules_md(_rule("FMT-001", extra="- 字体: [微软雅黑]")),
        )
        result = validate_rules(path)
        assert result.ok, result.errors

    def test_unknown_native_rule_warns(self, tmp_path):
        path = _write(tmp_path / "rules.md", _rules_md(_rule("STR-099")))
        result = validate_rules(path)
        assert result.ok
        assert any("可能永不执行" in w for w in result.warnings)

    def test_bad_bool_param_warns(self, tmp_path):
        path = _write(
            tmp_path / "rules.md",
            _rules_md(
                _rule(
                    "TERM-003",
                    check="regex",
                    extra="- 模式: '[A-Z]{2,}'\n- 仅首次出现: maybe",
                ),
                section="# 术语规则",
            ),
        )
        result = validate_rules(path)
        assert result.ok
        assert any("不是布尔值" in w for w in result.warnings)


class TestValidateGlossary:
    def test_project_glossary_valid(self):
        result = validate_glossary(PROJECT_ROOT / "glossary")
        assert result.ok, result.errors

    def test_missing_dir(self, tmp_path):
        result = validate_glossary(tmp_path / "nope")
        assert not result.ok

    def test_missing_terms_key(self, tmp_path):
        _write(tmp_path / "g.yaml", "category: 测试\nversion: '1.0'\n")
        result = validate_glossary(tmp_path)
        assert any("缺少 terms" in e for e in result.errors)

    def test_invalid_regex(self, tmp_path):
        _write(
            tmp_path / "g.yaml",
            "category: 测试\nterms:\n  - pattern: '[oops'\n    preferred: x\n",
        )
        result = validate_glossary(tmp_path)
        assert any("正则无法编译" in e for e in result.errors)

    def test_unknown_field_warns(self, tmp_path):
        _write(
            tmp_path / "g.yaml",
            "category: 测试\nterms:\n  - pattern: foo\n    preferred: bar\n    unknown_key: 1\n",
        )
        result = validate_glossary(tmp_path)
        assert result.ok
        assert any("未知字段" in w for w in result.warnings)


class TestValidateVocab:
    def test_project_vocab_valid(self):
        result = validate_vocab(PROJECT_ROOT / "vocab")
        assert result.ok, result.errors

    def test_missing_dir(self, tmp_path):
        result = validate_vocab(tmp_path / "nope")
        assert not result.ok

    def test_invalid_reject_regex(self, tmp_path):
        _write(tmp_path / "reject.txt", "[bad(regex\n")
        result = validate_vocab(tmp_path)
        assert any("reject.txt" in e for e in result.errors)

    def test_duplicate_accept_warns(self, tmp_path):
        _write(tmp_path / "accept.txt", "FinFET\nfinfet\n")
        result = validate_vocab(tmp_path)
        assert result.ok
        assert any("重复条目" in w for w in result.warnings)


class TestValidateConfiguration:
    def test_project_all_valid(self):
        result = validate_configuration(
            PROJECT_ROOT / "rules.md", PROJECT_ROOT / "glossary", PROJECT_ROOT / "vocab"
        )
        assert result.ok, result.errors

    def test_merge_collects_all_errors(self, tmp_path):
        _write(tmp_path / "rules.md", _rules_md(_rule("BAD", check="duplicate_title")))
        _write(tmp_path / "bad-glob.yaml", "category: x\nterms: nope\n")
        (tmp_path / "vocab").mkdir()
        _write(tmp_path / "vocab" / "reject.txt", "])broken\n")
        result = validate_configuration(tmp_path / "rules.md", tmp_path, tmp_path / "vocab")
        assert len(result.errors) >= 3


class TestRulesValidateCli:
    def _run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "src" / "cli.py"), *args],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT_ROOT),
            encoding="utf-8",
            errors="replace",
        )

    def test_default_config_passes(self):
        result = self._run_cli("rules", "validate")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "[VALIDATE] OK" in result.stdout

    def test_errors_exit_1(self, tmp_path):
        bad = _write(tmp_path / "rules.md", _rules_md(_rule("BADID", check="duplicate_title")))
        result = self._run_cli("rules", "validate", "--rules", str(bad))
        assert result.returncode == 1
        assert "[VALIDATE] FAILED" in result.stdout
        assert "ID 格式非法" in result.stdout

    def test_missing_subcommand_exits_2(self):
        result = self._run_cli("rules")
        assert result.returncode == 2

    def test_rules_list_prints_rules(self):
        result = self._run_cli("rules", "list")
        assert result.returncode == 0, result.stdout[-400:]
        assert "[RULES] 共 30 条" in result.stdout
        assert "STR-001" in result.stdout and "FMT-008" in result.stdout

    def test_rules_list_missing_file_exits_1(self, tmp_path):
        result = self._run_cli("rules", "list", "--rules", str(tmp_path / "nope.md"))
        assert result.returncode == 1
        assert "未解析到规则" in result.stdout


class TestParamValidationRegressions:
    """2026-10-29 深度审查回归：此前 5 类参数错误全部 exit 0。"""

    def test_fmt003_non_integer_flagged(self, tmp_path):
        path = _write(
            tmp_path / "rules.md",
            _rules_md(_rule("FMT-003", check="per_page_char_limit", extra="- 最大字数: 二百")),
        )
        result = validate_rules(path)
        assert any("不是整数" in e for e in result.errors), result.errors

    def test_unknown_param_key_warns(self, tmp_path):
        path = _write(
            tmp_path / "rules.md",
            _rules_md(_rule("FMT-003", check="per_page_char_limit", extra="- 最大字树: 111")),
        )
        result = validate_rules(path)
        assert any("未知参数" in w for w in result.warnings), result.warnings

    def test_str001_non_integer_flagged(self, tmp_path):
        path = _write(
            tmp_path / "rules.md",
            _rules_md(_rule("STR-001", check="duplicate_title", extra="- 最小标题字号: 超大")),
        )
        result = validate_rules(path)
        assert any("最小标题字号" in e for e in result.errors), result.errors

    def test_negative_max_words_flagged(self, tmp_path):
        path = _write(
            tmp_path / "rules.md",
            _rules_md(_rule("STR-004", check="title_length", extra="- 最大英文词数: -5")),
        )
        result = validate_rules(path)
        assert any("最大英文词数" in e for e in result.errors), result.errors

    def test_exempt_layouts_empty_warns(self, tmp_path):
        path = _write(
            tmp_path / "rules.md",
            _rules_md(_rule("CON-004", check="conclusion_section", extra="- 豁免版式: []")),
        )
        result = validate_rules(path)
        assert any("豁免版式" in w for w in result.warnings), result.warnings

    def test_external_languagetool_url_flagged(self, tmp_path):
        path = _write(
            tmp_path / "rules.md",
            _rules_md(
                _rule(
                    "CON-001",
                    check="numeric_cross_reference",
                    extra="- languagetool_url: http://192.168.1.9:8010/v2",
                )
            ),
        )
        result = validate_rules(path)
        assert any("仅允许本地" in e for e in result.errors), result.errors

    def test_regex_outside_terminology_flagged(self, tmp_path):
        path = _write(
            tmp_path / "rules.md",
            _rules_md(_rule("CON-009", check="regex", extra="- 模式: foo"), section="# 内容规则"),
        )
        result = validate_rules(path)
        assert any("术语规则" in e for e in result.errors), result.errors


class TestValidateGlobalParameters:
    """2026-11: rules.md frontmatter `parameters:` 的静态校验。"""

    @staticmethod
    def _file(tmp_path: Path, parameters: str) -> Path:
        return _write(
            tmp_path / "rules.md",
            "---\n"
            'version: "1.0"\n'
            f"{parameters}\n"
            "---\n\n"
            "# 结构规则\n\n"
            "## STR-001: 必须有标题页\n"
            "- 严重度: error\n"
            "- 检查: first_slide_has_title_layout\n",
        )

    def test_valid_parameters_pass(self, tmp_path):
        path = self._file(
            tmp_path,
            "parameters:\n  alignment_tolerance: 6.0\n  numeric_length_units: [nm, mm]\n",
        )
        result = validate_rules(path)
        assert result.ok, result.errors

    def test_unknown_parameter_warns(self, tmp_path):
        path = self._file(tmp_path, "parameters:\n  typo_threshold: 1\n")
        result = validate_rules(path)
        assert result.ok
        assert any("typo_threshold" in w for w in result.warnings), result.warnings

    def test_non_numeric_parameter_errors(self, tmp_path):
        path = self._file(tmp_path, "parameters:\n  alignment_tolerance: abc\n")
        result = validate_rules(path)
        assert not result.ok
        assert any("alignment_tolerance" in e for e in result.errors), result.errors

    def test_out_of_range_parameter_errors(self, tmp_path):
        path = self._file(tmp_path, "parameters:\n  image_min_dpi: 0\n")
        result = validate_rules(path)
        assert not result.ok
        assert any("image_min_dpi" in e for e in result.errors), result.errors

    def test_list_parameter_accepts_comma_string(self, tmp_path):
        path = self._file(tmp_path, "parameters:\n  numeric_length_units: nm, mm\n")
        result = validate_rules(path)
        assert result.ok, result.errors

    def test_list_parameter_rejects_scalar(self, tmp_path):
        path = self._file(tmp_path, "parameters:\n  numeric_length_units: 3\n")
        result = validate_rules(path)
        assert not result.ok
        assert any("numeric_length_units" in e for e in result.errors), result.errors
