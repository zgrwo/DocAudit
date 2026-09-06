#!/usr/bin/env bash
set -e

# 2026-09-06 r5 审查 F-01/F-02: 派生项目根 + venv 绝对路径, 消除 CWD 强依赖
# (旧版 pip install "$SCRIPT_DIR[all]" 指向 scripts/ 自身, 无 pyproject 必失败;
#  相对 .venv + 裸 pip 从非项目根调用会装错位置 — 与 run.sh/install.py 对齐)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

echo ""
echo "============================================"
echo "  DocAudit - 本地离线文档审查系统"
echo "  安装脚本"
echo "============================================"
echo ""

# ── 检测 Python ──────────────────────────────────
echo "[1/3] 检测 Python 环境..."
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] 未找到 Python3，请先安装 Python 3.10+"
    exit 1
fi
PYVER=$(python3 --version 2>&1)
echo "        $PYVER"

# ── 创建虚拟环境 ──────────────────────────────────
echo ""
echo "[2/3] 创建虚拟环境..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "        虚拟环境已创建: $VENV_DIR"
else
    echo "        虚拟环境已存在，跳过创建"
fi

# ── 激活并升级 pip ────────────────────────────────
echo ""
echo "[3/3] 安装依赖..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q

# ── 安装依赖 ──────────────────────────────────────
pip install "$PROJECT_DIR[all]" -q
echo "        全部依赖安装完成 (核心 + PDF + 开发工具)"

# ── 验证安装 ──────────────────────────────────────
echo ""
echo "── 验证安装..."
# 2026-09-06 r5 审查 F-11: 验证导入与 install.py 对齐 (含 streamlit Web UI 依赖)
"$VENV_DIR/bin/python" -c "import streamlit; from src.converters import PptxConverter; from src.auditors import StructureAuditor; print('        核心模块导入成功')" 2>/dev/null || echo "[WARN] 模块导入验证失败"

# ── 完成 ──────────────────────────────────────────
echo ""
echo "============================================"
echo "  安装完成！"
echo ""
echo "  启动 Web UI:"
echo "    source .venv/bin/activate"
echo "    streamlit run app.py"
echo ""
echo "  CLI 审查:"
echo "    source .venv/bin/activate"
echo "    python src/cli.py 文档.pptx"
echo ""
echo "  启动 LanguageTool (可选):"
echo "    docker-compose up -d"
echo "============================================"
echo ""
