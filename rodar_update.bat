@echo off
echo ========================================================
echo Iniciando Sincronizacao de Boletos (SQL Server -^> AWS MySQL)
echo Data e Hora: %date% %time%
echo ========================================================

cd /d "%~dp0"

if exist main.exe (
    main.exe
) else (
    py -3 main.py || python main.py
)

echo.
echo ========================================================
echo Execucao Finalizada!
echo O Dashboard interativo foi atualizado em:
echo log_dashboard\dashboard.html
echo ========================================================
pause
