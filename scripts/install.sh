#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

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
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "        虚拟环境已创建: .venv/"
else
    echo "        虚拟环境已存在，跳过创建"
fi

# ── 激活并升级 pip ────────────────────────────────
echo ""
echo "[3/3] 安装依赖..."
source .venv/bin/activate
pip install --upgrade pip -q

# ── 安装依赖 ──────────────────────────────────────
pip install "$SCRIPT_DIR[all]" -q
echo "        全部依赖安装完成 (核心 + PDF + 开发工具)"

# ── 验证安装 ──────────────────────────────────────
echo ""
echo "── 验证安装..."
python -c "from src.converters import PptxConverter; from src.auditors import StructureAuditor; print('        核心模块导入成功')" 2>/dev/null || echo "[WARN] 模块导入验证失败"

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
