@echo off
chcp 65001 >nul
title DA数据清洗工具 - Windows 打包工具
echo ============================================
echo    DA数据清洗业务AI应用 - Windows 打包
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

:: 检查 pip
where pip >nul 2>&1
if %ERRORLEVEL% neq 0 (
    python -m ensurepip >nul 2>&1
)
echo [✓] pip 就绪

:: 安装依赖
echo.
echo [正在安装依赖...]
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [警告] 部分依赖安装可能有问题，尝试继续...
)

:: 检查 PyInstaller
pip show pyinstaller >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [安装] PyInstaller...
    pip install pyinstaller
)

:: 清理旧构建
echo.
echo [清理] 旧构建文件...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del /f /q DA数据清洗工具.spec 2>nul

:: 构建
echo.
echo [构建] 正在打包，请耐心等待...
pyinstaller ^
    --name "DA数据清洗工具" ^
    --windowed ^
    --add-data "modules;modules" ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-data "config.py;." ^
    --hidden-import flask_session ^
    --hidden-import duckdb ^
    --hidden-import numpy ^
    --hidden-import pandas ^
    --hidden-import cryptography ^
    --collect-all cryptography ^
    run.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [错误] 打包失败！请检查上面的错误信息
    pause
    exit /b 1
)

:: 清理构建中间产物
rmdir /s /q build 2>nul
del /f /q DA数据清洗工具.spec 2>nul

echo.
echo ============================================
echo    [✓] 打包完成！
echo ============================================
echo.
echo 生成的程序在 dist\DA数据清洗工具\ 目录下
echo 运行: dist\DA数据清洗工具\DA数据清洗工具.exe
echo.
pause
