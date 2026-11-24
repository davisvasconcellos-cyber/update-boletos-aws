@echo off
cd /d "%~dp0"

:: Localiza o executavel do Python
set PYTHON_CMD=python
if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Python\bin\python.exe"
)

echo =========================================
echo Instalando dependencias necessarias...
echo =========================================
"%PYTHON_CMD%" -m pip install pyinstaller pyodbc pymysql sshtunnel paramiko cryptography

echo.
echo =========================================
echo Compilando a aplicacao para .exe...
echo =========================================
"%PYTHON_CMD%" -m PyInstaller --clean --onefile --name main main.py

echo.
echo =========================================
echo Gerando backup do main.exe anterior (se existir)...
echo =========================================
set CURR_DATE=%date:~-4%%date:~3,2%%date:~0,2%
set CURR_TIME=%time:~0,2%%time:~3,2%
set CURR_TIME=%CURR_TIME: =0%
set TIMESTAMP=%CURR_DATE%_%CURR_TIME%

if exist main.exe (
    echo Renomeando main.exe existente para main_%TIMESTAMP%.exe ...
    ren main.exe main_%TIMESTAMP%.exe
)

echo.
echo Copiando o novo main.exe da pasta dist para a raiz...
copy /y dist\main.exe .

echo.
echo =========================================
echo Compilacao e Backup finalizados com sucesso!
echo - Novo executavel: main.exe
echo - Executaveis em dist\ foram mantidos.
echo =========================================
pause
