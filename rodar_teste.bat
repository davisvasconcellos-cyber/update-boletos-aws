@echo off
echo ========================================================
echo Iniciando Sincronizacao de Boletos (MODO DE TESTE)
echo Apenas 1 lote (ate 50 registros) sera processado.
echo Data e Hora: %date% %time%
echo ========================================================

cd /d "%~dp0"

if exist main.exe (
    main.exe testmode
) else (
    py -3 main.py testmode || python main.py testmode
)

echo.
echo ========================================================
echo Execucao de TESTE Finalizada!
echo O Dashboard interativo foi atualizado em:
echo log_dashboard\dashboard.html
echo ========================================================
pause
