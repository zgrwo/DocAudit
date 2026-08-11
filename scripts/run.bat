@echo off
chcp 936 > nul

setlocal enabledelayedexpansion

title DocAudit — 本地离线文档审查系统

:: ============================================================
::  DocAudit 一键启动脚本 (Windows)
::  双击即可: 自动检测 → 安装 → 打开浏览器 → 审查文档
:: ============================================================

set "PROJECT_DIR=%~dp0.."
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "PYTHON="

echo.
echo   +==============================================+
echo   ^|     DocAudit — 本地离线文档审查系统         ^|
echo   ^|     一键启动脚本 v1.0                        ^|
echo   +==============================================+
echo.

:: ── 1. 查找 Python 3.10+ (三级降级策略) ──
echo   [1] 检测 Python 环境...

:: ── 策略 1: py launcher (Windows Python Launcher, 覆盖面最广) ──
:: py.exe 随官方 Python 安装器写入 C:\Windows\py.exe ，
:: 可发现本机所有已安装的 Python 版本（含未加入 PATH 的）。
py --version >nul 2>&1
if !errorlevel!==0 (
    for /f "tokens=2" %%v in ('py --version 2^>^&1') do set "PYVER=%%v"
    for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
        set /a _MJ=%%a 2>nul
        set /a _MN=%%b 2>nul
        if !_MJ! gtr 3 set "PYTHON=py" & goto :python_found
        if !_MJ! equ 3 if !_MN! geq 10 set "PYTHON=py" & goto :python_found
    )
    :: py 启动器可用但默认版本 < 3.10，尝试指定更高版本
    for %%v in (3.13 3.12 3.11 3.10) do (
        py -%%v --version >nul 2>&1
        if !errorlevel!==0 (
            for /f "tokens=2" %%x in ('py -%%v --version 2^>^&1') do set "PYVER=%%x"
            set "PYTHON=py -%%v"
            goto :python_found
        )
    )
)

:: ── 策略 2: where 命令 (PATH 中的 python / python3) ──
for %%p in (python3 python) do (
    where.exe %%p >nul 2>nul
    if !errorlevel!==0 (
        for /f "tokens=2" %%v in ('%%p --version 2^>^&1') do (
            for /f "tokens=1,2 delims=." %%a in ("%%v") do (
                set /a _MJ=%%a 2>nul
                set /a _MN=%%b 2>nul
                if !_MJ! gtr 3 set "PYTHON=%%p" & set "PYVER=%%v" & goto :python_found
                if !_MJ! equ 3 if !_MN! geq 10 set "PYTHON=%%p" & set "PYVER=%%v" & goto :python_found
            )
        )
    )
)

:: ── 策略 3: 扫描常见安装路径 (未加入 PATH 的用户/系统安装) ──
for %%d in (
    "%LOCALAPPDATA%\Programs\Python\Python313"
    "%LOCALAPPDATA%\Programs\Python\Python312"
    "%LOCALAPPDATA%\Programs\Python\Python311"
    "%LOCALAPPDATA%\Programs\Python\Python310"
    "%ProgramFiles%\Python313"
    "%ProgramFiles%\Python312"
    "%ProgramFiles%\Python311"
    "%ProgramFiles%\Python310"
) do (
    if exist "%%~d\python.exe" (
        for /f "tokens=2" %%v in ('"%%~d\python.exe" --version 2^>^&1') do (
            for /f "tokens=1,2 delims=." %%a in ("%%v") do (
                set /a _MJ=%%a 2>nul
                set /a _MN=%%b 2>nul
                if !_MJ! gtr 3 set "PYTHON=%%~d\python.exe" & set "PYVER=%%v" & goto :python_found
                if !_MJ! equ 3 if !_MN! geq 10 set "PYTHON=%%~d\python.exe" & set "PYVER=%%v" & goto :python_found
            )
        )
    )
)

:python_found
if "%PYTHON%"=="" (
    echo   [X] 未找到 Python 3.10+
    echo.
    echo      请从 https://www.python.org/downloads/ 下载安装 Python 3.10+
    echo      安装时请勾选 "Add Python to PATH" 选项
    echo.
    echo      如已安装但未被检测到, 请将 Python 加入系统 PATH 后重试
    pause
    exit /b 1
)
echo   [OK] 找到 Python %PYVER%  (%PYTHON%)

:: ── 2. 准备虚拟环境 ──
echo   [2] 准备虚拟环境...

set "NEED_INSTALL=0"
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo        首次运行，正在创建虚拟环境...
    %PYTHON% -m venv "%VENV_DIR%" --clear
    if errorlevel 1 (
        echo   [X] 虚拟环境创建失败，请检查磁盘空间和权限
        pause
        exit /b 1
    )
    echo   [OK] 虚拟环境创建成功
    set "NEED_INSTALL=1"
) else (
    echo   [OK] 虚拟环境已就绪
)

set "RUN_PYTHON=%VENV_DIR%\Scripts\python"

:: ── 3. 安装依赖 ──
echo   [3] 检查依赖...

:: 通过能否导入 streamlit 来判断依赖是否已安装
set "DEPS_OK=0"
"%RUN_PYTHON%" -c "import streamlit" >nul 2>&1
if !errorlevel!==0 (set "DEPS_OK=1")

if "%DEPS_OK%"=="0" (
    echo        正在安装 DocAudit 及全部依赖 约需 1-3 分钟...
    "%RUN_PYTHON%" -m pip install --upgrade pip -q
    "%RUN_PYTHON%" -m pip install "%PROJECT_DIR%[all]" -q
    if errorlevel 1 (
        echo   [X] 依赖安装失败，请检查网络连接后重试
        pause
        exit /b 1
    )
    echo   [OK] 依赖安装完成
) else (
    echo   [OK] 依赖已安装
)

:: ── 启动 Web UI ──
echo.
echo   [启动] 启动 Web 界面...

echo.
echo   +==============================================+
echo   ^|  浏览器将自动打开 http://127.0.0.1:8501      ^|
echo   ^|  上传文档 → 点击审查 → 查看结果              ^|
echo   ^|  按 Ctrl+C 或关闭此窗口停止服务               ^|
echo   +==============================================+
echo.

:: 启动 Streamlit 应用
"%RUN_PYTHON%" -m streamlit run "%PROJECT_DIR%\app.py"

echo.
echo   DocAudit 已停止。
pause
