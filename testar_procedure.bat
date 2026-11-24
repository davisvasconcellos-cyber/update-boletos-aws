@echo off
cd /d "%~dp0"
echo ========================================================
echo Testando acesso direto a Stored Procedure na base VINDI...
echo ========================================================

if exist main.exe (
    main.exe check
) else (
    set PYTHON_CMD=python
    if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
        set "PYTHON_CMD=%LOCALAPPDATA%\Python\bin\python.exe"
    )
    "%PYTHON_CMD%" main.py check || python main.py check || py main.py check
)

echo.
pause
