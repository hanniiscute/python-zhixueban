@echo off
chcp 65001 >nul
title 个性化学习智能体 - 环境安装（只需运行一次）
cd /d "%~dp0"

echo.
echo   ==========================================
echo      个性化学习智能体系统 - 环境安装
echo      拿到包后先运行本脚本，只需运行一次
echo   ==========================================
echo.

REM ---------- 1. 检测 Python ----------
set "PY_CMD=python"
where python >nul 2>&1
if not errorlevel 1 goto HAS_PY
where py >nul 2>&1
if errorlevel 1 goto NO_PY
set "PY_CMD=py -3"
:HAS_PY
echo   [1/5] 检测到 Python，正在创建虚拟环境...
if exist "backend\.venv\Scripts\python.exe" (
    echo         虚拟环境已存在，跳过。
    goto PIP
)
%PY_CMD% -m venv backend\.venv
if errorlevel 1 (
    echo   [错误] 创建虚拟环境失败，请截图发到群里。
    pause
    exit /b 1
)
goto PIP

:NO_PY
echo   [错误] 没找到 Python，请先安装 Python 3.11 及以上版本：
echo          https://www.python.org/downloads/
echo          安装时务必勾选 "Add Python to PATH"
echo          装好后重新双击本脚本。
pause
exit /b 1

:PIP
REM ---------- 2. 后端依赖 ----------
echo   [2/5] 正在安装后端依赖（约 3-8 分钟，取决于网速）...
"%~dp0backend\.venv\Scripts\python.exe" -m pip install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo   [错误] 后端依赖安装失败，请检查网络后重新运行本脚本。
    pause
    exit /b 1
)

REM ---------- 3. 前端依赖 ----------
echo   [3/5] 正在安装前端依赖（可能需要几分钟）...
where npm >nul 2>&1
if not errorlevel 1 (
    pushd frontend
    call npm install
    popd
    goto ENVFILE
)
if exist "%ProgramFiles%\nodejs\npm.cmd" (
    pushd frontend
    call "%ProgramFiles%\nodejs\npm.cmd" install
    popd
    goto ENVFILE
)
echo   [错误] 没找到 npm，请先安装 Node.js 18 及以上版本：
echo          https://nodejs.org
echo          装好后重新双击本脚本（已装好的部分会自动跳过）。
pause
exit /b 1

:ENVFILE
REM ---------- 4. 生成配置 ----------
echo   [4/5] 正在生成配置文件 backend\.env ...
if exist "backend\.env" (
    echo         已存在，保留现有配置不动。
) else (
    copy backend\.env.clean backend\.env >nul
    echo         已生成，还差最后一步填密钥（见下方说明）。
)

REM ---------- 5. 完成 ----------
echo   [5/5] 环境安装完成！
echo.
echo   ==========================================
echo      还差最后一步（只做一次）：
echo.
echo      用记事本打开 backend\.env ，填这四行：
echo        SPARK_APP_ID=你的讯飞 AppID
echo        SPARK_API_KEY=你的讯飞 API Key
echo        SPARK_API_SECRET=你的讯飞 API Secret
echo        MYSQL_PASSWORD=你本机 MySQL 的 root 密码
echo.
echo      讯飞密钥免费申请： https://console.xfyun.cn
echo      （创建应用后，领一个模型的免费试用包）
echo.
echo      填完后双击「启动项目.bat」就能用了！
echo   ==========================================
echo.
pause
