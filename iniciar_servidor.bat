@echo off
title Sony Price Tracker - Servidor Local
echo =======================================================
echo    Iniciando servidor de Sony Store Bolivia Tracker
echo =======================================================
echo.
cd /d "%~dp0"
echo Abriendo navegador en http://localhost:8080/ ...
start http://localhost:8080/
echo.
echo Servidor en ejecucion. Para detenerlo, cierra esta ventana.
echo.
python server.py
pause
