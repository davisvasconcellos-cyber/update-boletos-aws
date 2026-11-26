@echo off
cd /d "%~dp0"
echo ========================================================
echo Abrindo Tunel SSH para o MySQL AWS (msf_cobranca)...
echo Bastion: 34.204.24.206:22 -> RDS: 10.1.10.101:3306
echo ========================================================
echo.
echo O tunel ficara disponivel em: 127.0.0.1:3307
echo Voce pode conectar seu DBeaver / Workbench / Plugin em:
echo   Host: 127.0.0.1
echo   Porta: 3307
echo   Usuario: davis.vasconcellos
echo   Banco: msf_cobranca
echo.
echo Mantenha esta janela aberta enquanto estiver usando o banco!
echo (Para encerrar, feche esta janela ou aperte Ctrl+C)
echo ========================================================
echo.

ssh -N -L 3307:10.1.10.101:3306 davis.vasconcellos@34.204.24.206 -i ssh\id_ed25519
