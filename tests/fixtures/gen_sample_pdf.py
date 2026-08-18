"""生成 tests/fixtures/sample.pdf — 最小合法单页 PDF，含文本 "DocAuditTest"。

程序化构造（P1-6 docling 集成测试用）：
1. 先按对象顺序拼装全部 PDF 对象字节；
2. 记录每个 "N 0 obj" 的实际字节偏移；
3. 最后写 xref 表 / trailer / startxref，保证偏移正确。

用法: python tests/fixtures/gen_sample_pdf.py
"""

from pathlib import Path

OUTPUT = Path(__file__).parent / "sample.pdf"


def _build() -> bytes:
    # 对象内容 (1..5): Catalog / Pages / Page / Contents(流) / Font
    content_stream = b"BT /F1 24 Tf 72 720 Td (DocAuditTest) Tj ET"
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        # 流数据 = content + 换行 (Length 含末尾换行，与 "stream\n" 后数据一致)
        b"<< /Length "
        + str(len(content_stream) + 1).encode()
        + b" >>\nstream\n"
        + content_stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{idx} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref_pos = len(out)
    count = len(objects) + 1  # 0 号空闲对象 + 5 个对象
    out += f"xref\n0 {count}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    return bytes(out)


def main() -> None:
    data = _build()
    OUTPUT.write_bytes(data)
    print(f"wrote {OUTPUT} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
