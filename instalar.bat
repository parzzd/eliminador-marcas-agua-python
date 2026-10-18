@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
echo.
echo Instalacion terminada. Abre iniciar.bat para ejecutar LimpiaColor.
pause
exit /b 0
:error
echo.
echo No se pudo completar. Instala Python 3.10 o superior desde python.org.
pause
exit /b 1
