#!/usr/bin/env bash
# ============================================================
# DocAudit 离线安装脚本（macOS / Linux）
# 用法:
#   联网下载:  bash setup_offline.sh download [core|pdf|full]
#   离线安装:  bash setup_offline.sh install   [core|pdf|full]
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PACKAGES_DIR="$SCRIPT_DIR/packages"
PROFILE="${2:-core}"

case "$PROFILE" in
    core) EXTRAS="" ;;
    pdf)  EXTRAS="[pdf]" ;;
    full) EXTRAS="[all]" ;;
    *)
        echo "[错误] 未知 profile: $PROFILE (可选: core, pdf, full)"
        exit 1
        ;;
esac

download_deps() {
    echo "[DocAudit] 下载依赖 profile=$PROFILE 到 packages/ ..."
    echo ""
    mkdir -p "$PACKAGES_DIR"
    LOCK="$SCRIPT_DIR/requirements-$PROFILE.txt"
    if [ -f "$LOCK" ]; then
        echo "[1/3] 按锁文件下载运行时依赖: $(basename "$LOCK")"
        pip download -r "$LOCK" -d "$PACKAGES_DIR"
    else
        echo "[警告] 未找到 requirements-$PROFILE.txt，回退到 pyproject 声明解析（结果不可复现）"
        pip download "$SCRIPT_DIR$EXTRAS" -d "$PACKAGES_DIR"
    fi

    echo "[2/3] 下载构建依赖 setuptools/wheel（离线安装本地项目必需，pip download 不会自动保存）"
    pip download setuptools wheel -d "$PACKAGES_DIR"

    echo "[3/3] 离线自检：dry-run 安装解析..."
    if [ -f "$LOCK" ]; then
        pip install --dry-run --ignore-installed --no-index --find-links="$PACKAGES_DIR" \
            -r "$LOCK" "$SCRIPT_DIR" \
            || { echo "[错误] 离线自检失败：packages/ 不完整，请勿拷贝到离线机器"; exit 1; }
    else
        pip install --dry-run --ignore-installed --no-index --find-links="$PACKAGES_DIR" \
            "$SCRIPT_DIR$EXTRAS" \
            || { echo "[错误] 离线自检失败：packages/ 不完整，请勿拷贝到离线机器"; exit 1; }
    fi

    echo ""
    echo "========================================"
    echo " 下载完成！packages/ 文件数量:"
    ls "$PACKAGES_DIR"/*.whl 2>/dev/null | wc -l
    echo "========================================"
    echo ""
    echo "请将 packages/ 文件夹复制到离线机器的项目根目录，"
    echo "然后在离线机器上运行: bash setup_offline.sh install $PROFILE"
}

install_offline() {
    if [ ! -d "$PACKAGES_DIR" ]; then
        echo "[错误] packages/ 文件夹不存在，请先在有网机器上运行:"
        echo "       bash setup_offline.sh download $PROFILE"
        exit 1
    fi

    if [ ! -d ".venv" ]; then
        echo "[0/2] 创建虚拟环境..."
        python3 -m venv .venv
    else
        echo "[0/2] 虚拟环境已存在"
    fi

    echo "[1/2] 从本地 packages/ 安装依赖 (profile=$PROFILE)..."
    source .venv/bin/activate
    pip install --upgrade pip -q
    pip install --no-index --find-links="$PACKAGES_DIR" "$SCRIPT_DIR$EXTRAS"

    echo "[2/2] 验证安装..."
    python -c "import streamlit; from src.converters import PptxConverter; from src.auditors import StructureAuditor; print('        核心模块导入成功')" || echo "[警告] 模块导入验证失败"

    echo ""
    echo "========================================"
    echo " 离线安装完成！"
    echo "========================================"
    echo " 启动 Web UI:"
    echo "   source .venv/bin/activate"
    echo "   streamlit run app.py"
    echo ""
    echo " CLI 审查:"
    echo "   source .venv/bin/activate"
    echo "   python src/cli.py 文档.pptx"
    echo "========================================"
}

case "${1:-}" in
    download)
        download_deps
        ;;
    install)
        install_offline
        ;;
    *)
        echo "DocAudit 离线安装脚本"
        echo "========================================"
        echo "用法:"
        echo "  bash setup_offline.sh download [profile]  - 下载依赖到 packages/"
        echo "  bash setup_offline.sh install  [profile]  - 从本地 packages/ 安装"
        echo ""
        echo "profile 选项:"
        echo "  core  (默认) - PPTX/DOCX/MD 审查"
        echo "  pdf           - core + PDF 支持"
        echo "  full          - core + PDF + 开发工具"
        echo "========================================"
        echo ""
        echo "典型流程:"
        echo "  联网机器: bash setup_offline.sh download core"
        echo "  拷到离线: 复制整个项目文件夹（含 packages/）"
        echo "  离线机器: bash setup_offline.sh install core"
        ;;
esac
