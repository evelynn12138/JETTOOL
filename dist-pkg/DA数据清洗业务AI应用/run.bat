@echo off
chcp 65001 >nul
title DA数据清洗业务AI应用

echo ============================================
echo   DA数据清洗业务AI应用
echo ============================================
echo.

:: 检查 Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [✓] Python:
python --version

:: 检查依赖
echo.
echo [检查] 检查依赖...
pip show flask >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [安装] 安装依赖...
    pip install -r requirements.txt
    if %ERRORLEVEL% neq 0 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
)
echo [✓] 依赖就绪

:: 启动
echo.
echo [启动] 正在启动服务...
echo.
start "" http://127.0.0.1:5003
python run.py

pause
