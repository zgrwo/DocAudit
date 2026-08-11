@echo off
chcp 936 > nul
:: ============================================================
:: DocAudit 离线安装脚本（Windows）
:: 用法:
::   联网下载:  setup_offline.bat download [core|pdf|full]
::   离线安装:  setup_offline.bat install   [core|pdf|full]
:: ============================================================
setlocal enabledelayedexpansion
set "PACKAGES_DIR=%~dp0packages"
set "PROJECT_DIR=%~dp0..\"

:: 默认 profile = core
set "PROFILE=%~2"
if "%PROFILE%"=="" set "PROFILE=core"

:: 解析 profile → pip extras 参数
set "EXTRAS="
if /I "%PROFILE%"=="core" set "EXTRAS="
if /I "%PROFILE%"=="pdf"  set "EXTRAS=[pdf]"
if /I "%PROFILE%"=="full" set "EXTRAS=[all]"

if /I "%~1"=="download" (
    if not exist "%PACKAGES_DIR%" mkdir "%PACKAGES_DIR%"

    echo [DocAudit] 下载依赖 profile=%PROFILE% 到 packages/ ...
    echo.
    pip download "%PROJECT_DIR%%EXTRAS%" -d "%PACKAGES_DIR%"

    if errorlevel 1 (
        echo [错误] 下载失败，请检查网络连接
        exit /b 1
    )

    echo.
    echo ========================================
    echo  下载完成！packages/ 文件列表:
    echo ========================================
    dir /b "%PACKAGES_DIR%\*.whl" 2>nul
    dir /b "%PACKAGES_DIR%\*.tar.gz" 2>nul
    echo.
    echo 请将 packages/ 文件夹复制到离线机器的项目根目录,
    echo 然后在离线机器上运行: setup_offline.bat install %PROFILE%
    goto :eof
)

if /I "%~1"=="install" (
    if not exist "%PACKAGES_DIR%" (
        echo [错误] packages/ 文件夹不存在，请先在有网机器上运行:
        echo        setup_offline.bat download %PROFILE%
        exit /b 1
    )

    if not exist ".venv" (
        echo [0/2] 创建虚拟环境...
        python -m venv .venv
        if errorlevel 1 (
            echo [错误] 创建虚拟环境失败
            exit /b 1
        )
    ) else (
        echo [0/2] 虚拟环境已存在
    )

    echo [1/2] 从本地 packages/ 安装依赖 profile=%PROFILE%...
    .venv\Scripts\pip install --upgrade pip -q
    .venv\Scripts\pip install --no-index --find-links="%PACKAGES_DIR%" "%PROJECT_DIR%%EXTRAS%"

    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查 packages/ 中的文件是否完整
        exit /b 1
    )

    echo [2/2] 验证安装...
    .venv\Scripts\python -c "import streamlit; from src.converters import PptxConverter; from src.auditors import StructureAuditor; print('        核心模块导入成功')"
    if errorlevel 1 (
        echo [警告] 模块导入验证失败
    )

    echo.
    echo ========================================
    echo  离线安装完成！
    echo ========================================
    echo  启动 Web UI:
    echo    .venv\Scripts\streamlit run app.py
    echo.
    echo  CLI 审查:
    echo    .venv\Scripts\python src\cli.py 文档.pptx
    echo ========================================
    goto :eof
)

:: 默认：显示帮助
echo DocAudit 离线安装脚本
echo ========================================
echo 用法:
echo   setup_offline.bat download [profile]  - 下载依赖到 packages/
echo   setup_offline.bat install  [profile]  - 从本地 packages/ 安装
echo.
echo profile 选项:
echo   core  (默认) - PPTX/DOCX/MD 审查
echo   pdf           - core + PDF 支持
echo   full          - core + PDF + 开发工具
echo ========================================
echo.
echo 典型流程:
echo   联网机器: setup_offline.bat download core
echo   拷到离线: 复制整个项目文件夹（含 packages/）
echo   离线机器: setup_offline.bat install core
endlocal
