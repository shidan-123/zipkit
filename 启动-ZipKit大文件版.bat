@echo off
chcp 65001 >nul
title ZipKit 大文件版
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -m zipkit gui
    goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python -m zipkit gui
    goto :end
)

echo.
echo  没有找到 Python。
echo.
echo  请先安装：https://www.python.org/downloads/
echo  安装时务必勾选 "Add Python to PATH"
echo.
pause

:end
