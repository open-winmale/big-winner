@echo off
rem big-winner 日常启动（Windows）：双击运行，门户 http://127.0.0.1:8787
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PY="

py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)"') do set "PY=%%I"
if defined PY goto :found

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)"') do set "PY=%%I"
if defined PY goto :found

python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 for /f "delims=" %%I in ('python3 -c "import sys; print(sys.executable)"') do set "PY=%%I"
if defined PY goto :found

echo [run] 未检测到 Python 3.10+。请先双击 setup.bat 完成安装。
pause
exit /b 1

:found
"%PY%" run.py %*
echo.
echo [run] 服务已退出。
pause
