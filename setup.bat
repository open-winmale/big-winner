@echo off
rem big-winner 安装引导（Windows）：确保 Python 3.10+ 后进入安装向导。
rem 双击运行即可；命令口径见 AGENTS.md。
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PY="

rem ---- 依次探测 py -3 / python / python3，且版本必须 >= 3.10 ----
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)"') do set "PY=%%I"
if defined PY goto :found

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)"') do set "PY=%%I"
if defined PY goto :found

python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 for /f "delims=" %%I in ('python3 -c "import sys; print(sys.executable)"') do set "PY=%%I"
if defined PY goto :found

echo [setup] 未检测到 Python 3.10+，尝试用 winget 自动安装...
where winget >nul 2>&1
if errorlevel 1 goto :manual
winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
if errorlevel 1 goto :manual

rem ---- 刚装完的 Python 不在当前窗口 PATH 里，探测固定安装路径 ----
for %%V in (314 313 312 311 310) do (
    if not defined PY if exist "%LocalAppData%\Programs\Python\Python%%V%\python.exe" set "PY=%LocalAppData%\Programs\Python\Python%%V%\python.exe"
)
for %%V in (314 313 312 311 310) do (
    if not defined PY if exist "C:\Program Files\Python%%V%\python.exe" set "PY=C:\Program Files\Python%%V%\python.exe"
)
if defined PY goto :found
echo [setup] Python 已安装，但当前窗口还没识别到它。
echo         请关闭本窗口，重新双击 setup.bat 即可继续。
pause
exit /b 1

:manual
echo [setup] 无法自动安装 Python，请手动安装（三步）：
echo   1. 按任意键打开 python.org 下载页，下载并运行安装包
echo   2. 安装第一屏务必勾选 “Add python.exe to PATH”
echo   3. 装完后关闭本窗口，重新双击 setup.bat
pause >nul
start https://www.python.org/downloads/
exit /b 1

:found
echo [setup] 使用 Python：%PY%
"%PY%" setup_wizard.py %*
echo.
echo [setup] 向导已退出。
pause
