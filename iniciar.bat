@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app.py
) else (
    py -3 app.py
)
if errorlevel 1 (
    echo.
    echo No se pudo iniciar. Consulta la instalacion en README.md.
    pause
)
