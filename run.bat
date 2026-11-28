@echo off
title SonyBoliviaDB - Monitor de Precios y Stock
cd /d "%~dp0"
echo ========================================================
echo   Iniciando SonyBoliviaDB - Monitor de Precios y Banners
echo ========================================================
echo.
python server.py
pause
