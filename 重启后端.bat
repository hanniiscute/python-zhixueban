@echo off
chcp 65001 >nul
title 后端服务-请勿关闭
cd /d "%~dp0backend"

echo.
echo   ==========================================
echo      后端服务（端口 8000）
echo   ==========================================
echo.
echo   [1/2] 清理占用 8000 端口的残留进程...
REM findstr 的 /C: 让带空格的串成为"单个"正则；不加 /C: 空格会拆成
REM 多个 pattern 变成"或"关系，把所有 LISTENING 行都匹配上、误杀无关进程
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
    echo         结束旧进程 PID %%p
    taskkill /PID %%p /F >nul 2>&1
)
timeout /t 2 >nul

echo   [2/2] 启动后端...
echo.
echo   这个窗口就是后端服务，请勿关闭 —— 关掉它网站就打不开了。
echo   改了 .env 或后端代码后：关掉本窗口，再双击一次本脚本即可生效。
echo.
".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
echo.
echo   [后端已退出] 如果这不是你主动关的，把上面红色报错截图发我。
pause
