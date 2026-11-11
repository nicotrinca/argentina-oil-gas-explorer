@echo off
REM Levanta un servidor local y abre el visor. Hace falta servidor: abriendo
REM index.html con doble clic el navegador bloquea las capas y los graficos.
cd /d "%~dp0"
start "" cmd /c "timeout /t 2 >nul & start http://localhost:8765/"
echo Visor en http://localhost:8765  (cerra esta ventana para apagarlo)
python -m http.server 8765
