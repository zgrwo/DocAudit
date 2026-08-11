@echo off
chcp 65001 > nul
py -3 "%~dp0run.py" %*
if errorlevel 9009 goto :try_python
exit /b %errorlevel%
:try_python
python "%~dp0run.py" %*
if errorlevel 9009 goto :no_python
exit /b %errorlevel%
:no_python
echo.
echo [X] Python 3.10+ not found.
echo     Install it from https://www.python.org/downloads/
echo     and check "Add Python to PATH" during install.
pause
exit /b 1
