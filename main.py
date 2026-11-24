# -*- coding: utf-8 -*-
"""
Ponto de Entrada da Aplicacao (main.py)
Suporta execucao em modo normal ou teste, com sobreposicao via CLI:
  - main.exe / py main.py              -> Le opcoes do config.ini
  - main.exe testmode / py main.py testmode -> Forca test_mode=True (1 lote de teste)
  - main.exe testmode 10               -> Forca test_mode=True com 10 registros
  - main.exe normal                    -> Forca test_mode=False (producao completa)
"""

import sys
import os
import configparser

# Garante que o diretorio atual esteja no sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from util.paths import get_base_dir
from controller.sync_controller import SyncController

def main():
    base_dir = get_base_dir()
    config_path = os.path.join(base_dir, 'config.ini')
    
    test_mode = False
    max_records = 50
    db_query_timeout_seconds = 180
    db_fetch_chunk_size = 1000
    last_sync_timestamp = ""
    
    if os.path.exists(config_path):
        try:
            config = configparser.ConfigParser()
            config.read(config_path, encoding='utf-8')
            if 'PROCESSAMENTO' in config:
                p = config['PROCESSAMENTO']
                test_mode = p.getboolean('test_mode', fallback=False)
                max_records = p.getint('max_records', fallback=50)
                db_query_timeout_seconds = p.getint('db_query_timeout_seconds', fallback=180)
                db_fetch_chunk_size = p.getint('db_fetch_chunk_size', fallback=1000)
                last_sync_timestamp = p.get('last_sync_timestamp', fallback='').strip()
        except Exception as e:
            print(f"Aviso ao ler config.ini: {e}")

    # Tratamento de argumentos via linha de comando
    if len(sys.argv) > 1:
        arg1 = sys.argv[1].lower().strip()
        if arg1 in ["check", "--check", "-c", "diagnostico"]:
            print("========================================================")
            print("Executando DIAGNOSTICO de Acesso ao SQL Server e Procedure...")
            print("========================================================")
            from model.source_sqlserver import diagnostico_procedure
            diagnostico_procedure()
            return
        elif arg1 in ["testmode", "test", "--test", "-t"]:
            test_mode = True
            if len(sys.argv) > 2:
                try:
                    val_str = sys.argv[2].replace('-', '')
                    max_records = int(val_str)
                except ValueError:
                    print(f"Aviso: Valor '{sys.argv[2]}' invalido para max_records. Usando {max_records}.")
        elif arg1 in ["normal", "prod", "production", "--normal"]:
            test_mode = False

    if test_mode:
        print(f"Iniciando update_boletos_aws em MODO DE TESTE (1 lote de ate {max_records} registros)...")
    else:
        print(f"Iniciando update_boletos_aws (MODO NORMAL - lotes de {max_records} registros)...")

    controller = SyncController(
        test_mode=test_mode,
        max_records=max_records,
        db_query_timeout_seconds=db_query_timeout_seconds,
        db_fetch_chunk_size=db_fetch_chunk_size,
        last_sync_timestamp=last_sync_timestamp,
        config_path=config_path
    )
    controller.executar_fluxo()

if __name__ == "__main__":
    main()
