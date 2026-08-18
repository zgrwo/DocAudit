"""HTML 报告转义红线测试 — 用户文本必须 html.escape() (项目红线 #2)。

构造含 <script>alert(1)</script> / <img src=x onerror=...> / & / " 载荷的
findings 与 Document.source_path，断言 generate_html_report 输出中载荷被转义、
原始载荷不出现；同时覆盖空 findings 与 None 字段不崩溃。
"""

from src.models.document import Document, DocumentMetadata, Page, PageElement, Paragraph
from src.models.finding import AuditFinding, FindingSeverity, FindingType
from src.reporters.html_reporter import generate_html_report

XSS_SCRIPT = "<script>alert(1)</script>"
XSS_IMG = '<img src=x onerror="alert(1)">'
XSS_QUOTE = 'onclick="alert(1)"'


def _doc(source_path: str = "safe.pptx") -> Document:
    """构造带单个文本元素的 PPTX 文档。"""
    page = Page(
        index=0,
        elements=[PageElement(type="text_frame", paragraphs=[Paragraph(text="内容", runs=[])])],
    )
    return Document(
        source_path=source_path, format="pptx", metadata=DocumentMetadata(), pages=[page]
    )


def _finding(
    message: str = XSS_SCRIPT,
    context: str = XSS_SCRIPT,
    suggestion: str = XSS_SCRIPT,
    location: str = XSS_SCRIPT,
    rule_id: str = "SEC-TEST",
) -> AuditFinding:
    """构造含 XSS 载荷的 finding。"""
    return AuditFinding(
        type=FindingType.STRUCTURE,
        severity=FindingSeverity.ERROR,
        message=message,
        rule_id=rule_id,
        page_index=0,
        context=context,
        suggestion=suggestion,
        location=location,
    )


class TestPayloadEscaping:
    """核心红线: message/context/suggestion/location/source_path 全部转义。"""

    def test_script_payload_escaped_in_all_fields(self):
        """message/context/suggestion/location 四字段的 <script> 载荷全部转义。"""
        html = generate_html_report(_doc(), [_finding()])
        escaped = "&lt;script&gt;alert(1)&lt;/script&gt;"
        # 四个字段各渲染一次
        assert html.count(escaped) == 4, (
            f"四个用户字段都应转义渲染, 实际出现 {html.count(escaped)} 次"
        )
        assert XSS_SCRIPT not in html, "原始 <script> 载荷不得出现在报告中"

    def test_img_payload_escaped(self):
        """<img src=x onerror=...> 载荷被转义。"""
        html = generate_html_report(_doc(), [_finding(message=XSS_IMG)])
        assert "&lt;img" in html, "img 载荷应转义为 &lt;img"
        assert XSS_IMG not in html, "原始 img 载荷不得出现在报告中"

    def test_amp_and_quote_escaped(self):
        """& 与 " 载荷被转义 (&amp; / &quot;)。"""
        f = _finding(message='A & B "quoted"')
        html = generate_html_report(_doc(), [f])
        assert "&amp;" in html, "& 应转义为 &amp;"
        assert "&quot;" in html, '" 应转义为 &quot;'

    def test_source_path_escaped(self):
        """Document.source_path 含载荷 → 报告头部转义。"""
        doc = _doc(source_path=XSS_SCRIPT)
        html = generate_html_report(doc, [_finding()])
        assert XSS_SCRIPT not in html, "原始 <script> 载荷不得出现在 source_path 渲染中"
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    def test_title_escaped(self):
        """title 参数含 HTML → 转义。"""
        html = generate_html_report(_doc(), [_finding()], title="<b>标题</b>")
        assert "&lt;b&gt;标题&lt;/b&gt;" in html
        assert "<b>标题</b>" not in html

    def test_file_label_escaped(self):
        """file_label 参数 (批量模式头部) 含载荷 → 转义。"""
        html = generate_html_report(_doc(), [_finding()], file_label=XSS_SCRIPT)
        assert XSS_SCRIPT not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


class TestEdgeCases:
    """空 findings 与 None 字段不崩溃。"""

    def test_empty_findings(self):
        """无 findings → 正常生成 (显示「未发现任何问题」)。"""
        html = generate_html_report(_doc(), [])
        assert "未发现任何问题" in html
        assert "<!DOCTYPE html>" in html

    def test_none_fields_no_crash(self):
        """context/suggestion/location 为 None → 不崩溃且正常渲染。"""
        f = AuditFinding(
            type=FindingType.STRUCTURE,
            severity=FindingSeverity.ERROR,
            message="测试发现",
            rule_id="SEC-NONE",
            page_index=0,
            context=None,
            suggestion=None,
            location=None,
        )
        html = generate_html_report(_doc(), [f])
        assert "审查发现" in html
        assert "测试发现" in html
