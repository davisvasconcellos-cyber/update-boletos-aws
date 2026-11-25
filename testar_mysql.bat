@echo off
cd /d "%~dp0"
echo ========================================================
echo Testando acesso direto ao MySQL e Schema da Tabela boletos
echo ========================================================

if exist main.exe (
    main.exe check-mysql
) else (
    set PYTHON_CMD=python
    if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
        set "PYTHON_CMD=%LOCALAPPDATA%\Python\bin\python.exe"
    )
    "%PYTHON_CMD%" main.py check-mysql || python main.py check-mysql || py main.py check-mysql
)

echo.
pause
