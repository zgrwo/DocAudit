@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

set "PROJECT_DIR=%~dp0.."

echo.
echo ============================================
echo   DocAudit - 本地离线文档审查系统
echo   安装脚本
echo ============================================
echo.

:: ── 检测 Python ──────────────────────────────────
echo [1/3] 检测 Python 环境...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.10+
    echo         下载: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo         Python %PYVER%

:: ── 创建虚拟环境 ──────────────────────────────────
echo.
echo [2/3] 创建虚拟环境...
if not exist "%PROJECT_DIR%\.venv" (
    python -m venv "%PROJECT_DIR%\.venv"
    if %errorlevel% neq 0 (
        echo [ERROR] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo         虚拟环境已创建: %PROJECT_DIR%\.venv\
) else (
    echo         虚拟环境已存在，跳过创建
)

:: ── 激活并升级 pip ────────────────────────────────
echo.
echo [3/3] 安装依赖...
call "%PROJECT_DIR%\.venv\Scripts\activate.bat" >nul 2>&1
"%PROJECT_DIR%\.venv\Scripts\python" -m pip install --upgrade pip -q

:: ── 安装依赖 ──────────────────────────────────────
"%PROJECT_DIR%\.venv\Scripts\pip" install "%PROJECT_DIR%[all]" -q
if %errorlevel% neq 0 (
    echo [ERROR] 依赖安装失败
    pause
    exit /b 1
)
echo         全部依赖安装完成 (核心 + PDF + 开发工具)

:: ── 验证安装 ──────────────────────────────────────
echo.
echo ── 验证安装...
"%PROJECT_DIR%\.venv\Scripts\python" -c "from src.converters import PptxConverter; from src.auditors import StructureAuditor; print('        核心模块导入成功')" 2>nul
if %errorlevel% neq 0 (
    echo [WARN] 模块导入验证失败，请检查安装
)

:: ── 完成 ──────────────────────────────────────────
echo.
echo ============================================
echo   安装完成！
echo.
echo   启动 Web UI:
echo     scripts\run.bat
echo.
echo   CLI 审查:
echo     .venv\Scripts\python src\cli.py 文档.pptx
echo.
echo   启动 LanguageTool (可选):
echo     docker-compose up -d
echo ============================================
echo.

pause
