@echo off
chcp 65001 >nul
title 个性化学习智能体 - 一键启动
cd /d "%~dp0"

echo.
echo   ==========================================
echo      个性化学习智能体系统 - 启动中
echo   ==========================================
echo.

REM ---------- 1. 检查 Python 虚拟环境 ----------
if not exist "backend\.venv\Scripts\python.exe" (
    echo   [错误] 没找到 backend\.venv\Scripts\python.exe
    echo          Python 环境缺失，项目需要重建。
    echo.
    pause
    exit /b 1
)

REM ---------- 2. 检查前端依赖 ----------
if not exist "frontend\node_modules\vite\bin\vite.js" (
    echo   [提示] 前端依赖还没装，请先双击「环境安装.bat」
    echo          （只需运行一次，装完再回来双击本脚本）
    echo.
    pause
    exit /b 1
)

REM ---------- 3. 探测 node.exe（不写死路径，避免目录被清理后失效） ----------
set "NODE_EXE="
if exist "%ProgramFiles%\nodejs\node.exe" set "NODE_EXE=%ProgramFiles%\nodejs\node.exe"
if not defined NODE_EXE if exist "%ProgramFiles(x86)%\nodejs\node.exe" set "NODE_EXE=%ProgramFiles(x86)%\nodejs\node.exe"
if not defined NODE_EXE if exist "%LOCALAPPDATA%\Programs\nodejs\node.exe" set "NODE_EXE=%LOCALAPPDATA%\Programs\nodejs\node.exe"
if not defined NODE_EXE (
    for /f "delims=" %%i in ('where node 2^>nul') do if not defined NODE_EXE set "NODE_EXE=%%i"
)
if not defined NODE_EXE (
    echo   [错误] 没找到 node.exe，请先安装 Node.js
    echo          官网： https://nodejs.org
    echo.
    pause
    exit /b 1
)
echo   使用 Node: %NODE_EXE%

REM ---------- 4. 启动后端 ----------
REM 注意：不带 --reload。reload 模式是"主进程+worker"两个进程，
REM 关窗口/杀主进程时 worker 会变成孤儿继续占着 8000 端口。
REM 后端配置（.env）改动需要重启才会生效：关掉后端窗口重新运行本脚本即可。
echo.
echo   [1/3] 正在启动后端服务（端口 8000）...
start "后端服务-请勿关闭" /d "%~dp0backend" "%~dp0backend\.venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000

REM ---------- 5. 启动前端 ----------
echo   [2/3] 正在启动前端界面（端口 5173）...
start "前端服务-请勿关闭" /d "%~dp0frontend" "%NODE_EXE%" "%~dp0frontend\node_modules\vite\bin\vite.js" --host localhost --port 5173

REM ---------- 6. 等待就绪 ----------
echo   [3/3] 等待服务就绪（后端首次启动约需 20-40 秒）...
echo.
set /a WAITED=0
:WAIT
if %WAITED% GEQ 120 goto OPEN
timeout /t 3 >nul
set /a WAITED+=3
echo      已等待 %WAITED% 秒...
powershell -NoProfile -Command "try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',8000); $c.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 goto WAIT
REM 前端用 HTTP 探测：vite dev 只监听 IPv6(::1)，TcpClient 走 IPv4 会假阴性，
REM 导致这里一直轮询到 120 秒超时才开始打开浏览器。
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://localhost:5173/' -UseBasicParsing -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 goto WAIT

:OPEN
echo.
echo   ==========================================
echo      启动完成！正在打开浏览器...
echo.
echo      网站地址：  http://localhost:5173
echo      接口文档：  http://127.0.0.1:8000/docs
echo.
echo      那两个黑色命令行窗口就是服务，请勿关闭，
echo      关掉它们网站就打不开了。
echo   ==========================================
echo.
start "" http://localhost:5173

echo   本窗口可以关闭。要停止服务，运行「停止项目.bat」
echo.
pause
