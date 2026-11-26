# -*- coding: utf-8 -*-
"""
Módulo de Conexão com o SQL Server (model/source_sqlserver.py)
Executa a Stored Procedure 'CarregaFaturasBoletoWS' com controle de timeout,
leitura paginada via cursor.fetchmany e acionamento da camada de formatação.
"""

import sys
import os
import configparser
import datetime
import pyodbc

from util.paths import get_base_dir
from model.formatter import formatar_registro

def get_db_config():
    """Lê as configurações de banco do config.ini."""
    base_dir = get_base_dir()
    config_path = os.path.join(base_dir, 'config.ini')
    config = configparser.RawConfigParser()
    
    cfg = {
        "servidor_ip": "192.168.1.20",
        "database": "SALESFORCE",
        "procedure_name": "CarregaFaturasBoletoWS",
        "connect_timeout_seconds": 10,
        "data_inicio": "",
        "data_fim": ""
    }
    
    if os.path.exists(config_path):
        try:
            config.read(config_path, encoding='utf-8')
            if 'banco' in config:
                b = config['banco']
                cfg["servidor_ip"] = b.get('servidor_ip', fallback=cfg["servidor_ip"]).strip()
                cfg["database"] = b.get('database', fallback=cfg["database"]).strip()
                cfg["procedure_name"] = b.get('procedure_name', fallback=cfg["procedure_name"]).strip()
                cfg["connect_timeout_seconds"] = b.getint('connect_timeout_seconds', fallback=cfg["connect_timeout_seconds"])
            if 'FILTRO' in config:
                f = config['FILTRO']
                cfg["data_inicio"] = f.get('data_inicio', fallback='').strip()
                cfg["data_fim"] = f.get('data_fim', fallback='').strip()
        except Exception:
            pass
            
    return cfg

def get_conexao(connect_timeout_seconds=None):
    """Cria conexão pyodbc com o SQL Server."""
    cfg = get_db_config()
    timeout = int(connect_timeout_seconds) if connect_timeout_seconds else cfg["connect_timeout_seconds"]
    servidor = cfg["servidor_ip"]
    database = cfg["database"]
    
    string_conexao = f'DRIVER={{SQL Server}};SERVER={servidor};DATABASE={database};UID=PROGSPY1;PWD=QAZWSX12!'
    try:
        conn = pyodbc.connect(string_conexao, timeout=timeout)
        return conn
    except Exception as e:
        raise Exception(f"Falha ao conectar via pyodbc ao SQL Server ({servidor}/{database}): {str(e)}")

def testar_conexao_db():
    """
    Teste rápido de conectividade com o SQL Server antes de rodar a extração principal.
    Verifica se o servidor responde e se a procedure existe no banco de dados configurado.
    """
    cfg = get_db_config()
    servidor = cfg["servidor_ip"]
    database = cfg["database"]
    proc_name = cfg["procedure_name"]
    try:
        conn = get_conexao(connect_timeout_seconds=10)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        
        # Checa se a procedure existe no banco configurado
        sql_check = f"SELECT ROUTINE_SCHEMA, ROUTINE_NAME FROM INFORMATION_SCHEMA.ROUTINES WHERE ROUTINE_NAME = '{proc_name}'"
        cursor.execute(sql_check)
        row = cursor.fetchone()
        if not row:
            cursor.execute(f"SELECT name FROM sys.procedures WHERE name = '{proc_name}'")
            row = cursor.fetchone()
            
        cursor.close()
        conn.close()
        
        if row:
            return True, f"Conexao com o SQL Server ({servidor}) OK e procedure '{proc_name}' confirmada no banco '{database}'."
        else:
            return False, f"Conexao com o SQL Server ({servidor}) OK, mas a procedure '{proc_name}' NAO foi encontrada no banco '{database}'. Verifique se o nome do banco no config.ini esta correto (esperado: VINDI)."
    except Exception as e:
        return False, f"Falha no teste de conexao com o SQL Server ({servidor}): {str(e)}"

def diagnostico_procedure(log_callback=print):
    """
    Executa um diagnóstico detalhado do SQL Server e da Stored Procedure.
    Mostra informações de schema, colunas retornadas e amostra de registro.
    """
    cfg = get_db_config()
    servidor = cfg["servidor_ip"]
    database = cfg["database"]
    proc_name = cfg["procedure_name"]
    d_inicio, d_fim = resolver_datas_filtro(cfg["data_inicio"], cfg["data_fim"])
    
    log_callback(f"[DIAGNOSTICO] Servidor: {servidor} | Banco: {database} | Procedure: {proc_name}")
    log_callback(f"[DIAGNOSTICO] Periodo de teste: '{d_inicio}' ate '{d_fim}'")
    
    try:
        conn = get_conexao(connect_timeout_seconds=10)
        cursor = conn.cursor()
        log_callback(f"[DIAGNOSTICO] Conexao com SQL Server ({servidor}) no banco '{database}' realizada com sucesso!")
        
        # 1. Checa no INFORMATION_SCHEMA
        sql_check = f"SELECT ROUTINE_SCHEMA, ROUTINE_NAME, CREATED, LAST_ALTERED FROM INFORMATION_SCHEMA.ROUTINES WHERE ROUTINE_NAME = '{proc_name}'"
        cursor.execute(sql_check)
        row = cursor.fetchone()
        if row:
            log_callback(f"[DIAGNOSTICO] SP encontrada: Schema={row[0]} | Nome={row[1]} | Ultima alteracao={row[3]}")
        else:
            cursor.execute(f"SELECT name FROM sys.procedures WHERE name = '{proc_name}'")
            row2 = cursor.fetchone()
            if row2:
                log_callback(f"[DIAGNOSTICO] SP encontrada via sys.procedures: {row2[0]}")
            else:
                log_callback(f"[DIAGNOSTICO ALERTA] Procedure '{proc_name}' nao encontrada no banco '{database}'.")
        
        # 2. Executa a procedure
        log_callback(f"[DIAGNOSTICO] Executando: EXEC {proc_name} '{d_inicio}', '{d_fim}' ...")
        cursor.execute(f"EXEC {proc_name} '{d_inicio}', '{d_fim}'")
        
        if cursor.description:
            colunas = [col[0] for col in cursor.description]
            log_callback(f"[DIAGNOSTICO] Total de colunas retornadas: {len(colunas)}")
            log_callback(f"[DIAGNOSTICO] Nomes das colunas: {', '.join(colunas)}")
            
            primeira_linha = cursor.fetchone()
            if primeira_linha:
                log_callback(f"[DIAGNOSTICO] Registro de exemplo recuperado com sucesso!")
                for col, val in zip(colunas, primeira_linha):
                    log_callback(f"   * {col}: {val}")
            else:
                log_callback(f"[DIAGNOSTICO] A procedure executou perfeitamente, mas nao ha faturas no periodo '{d_inicio}' ate '{d_fim}'.")
        else:
            log_callback(f"[DIAGNOSTICO] Procedure executada sem conjunto de resultados retornado.")
            
        cursor.close()
        conn.close()
        log_callback("[DIAGNOSTICO FINAL]: Teste concluido com 100% de SUCESSO!")
        return True
    except Exception as e:
        log_callback(f"[DIAGNOSTICO ERRO]: {e}")
        return False

def resolver_datas_filtro(cfg_data_inicio, cfg_data_fim, last_sync_timestamp=None):
    """
    Define as datas de início e fim para passar à procedure CarregaFaturasBoletoWS.
    Se não informadas no config.ini:
      - data_inicio: primeiro dia do mês corrente (ou derivado de last_sync_timestamp se houver)
      - data_fim: primeiro dia do mês subsequente ao próximo (ex.: cobrindo 60 dias)
    """
    hoje = datetime.date.today()
    
    if cfg_data_inicio:
        d_inicio = cfg_data_inicio
    else:
        # Primeiro dia do mês corrente
        d_inicio = hoje.replace(day=1).strftime('%Y-%m-%d')
        
    if cfg_data_fim:
        d_fim = cfg_data_fim
    else:
        # 60 dias à frente (cobrindo faturas a vencer)
        d_fim = (hoje + datetime.timedelta(days=60)).strftime('%Y-%m-%d')
        
    return d_inicio, d_fim

def buscar_e_formatar_boletos(limite=None, data_corte=None, query_timeout_seconds=180, fetch_chunk_size=1000, log_callback=None):
    """
    Executa a stored procedure 'CarregaFaturasBoletoWS' com as datas parametrizadas.
    Lê os resultados em blocos via fetchmany, formata através de model/formatter.py
    e retorna: (sucesso: bool, mensagem: str, registros_formatados: list, falhas_validacao: list)
    """
    cfg = get_db_config()
    proc_name = cfg["procedure_name"]
    d_inicio, d_fim = resolver_datas_filtro(cfg["data_inicio"], cfg["data_fim"], data_corte)
    
    if log_callback:
        log_callback(f"[DB QUERY] Executando procedure: EXEC {proc_name} '{d_inicio}', '{d_fim}'")
        if data_corte:
            log_callback(f"[DB QUERY] Data de corte informada (last_sync_timestamp): {data_corte}")

    resultados_raw = []
    
    try:
        conn = get_conexao(connect_timeout_seconds=15)
        cursor = conn.cursor()
        try:
            cursor.timeout = max(1, int(query_timeout_seconds))
        except Exception:
            if log_callback:
                log_callback("[DB INFO] pyodbc sem suporte a cursor.timeout; continuando sem timeout de cursor.")

        # Executa a stored procedure com os parâmetros de data
        sql_exec = f"EXEC {proc_name} ?, ?"
        cursor.execute(sql_exec, (d_inicio, d_fim))
        
        if log_callback:
            log_callback("[DB INFO] Procedure executada no SQL Server. Iniciando leitura dos registros em blocos...")

        # Obtém o nome das colunas retornadas pela procedure
        if not cursor.description:
            cursor.close()
            conn.close()
            return True, "Procedure executada com sucesso, mas nenhum conjunto de dados foi retornado.", [], []
            
        colunas = [col[0] for col in cursor.description]
        total_lidos = 0
        chunk_size = max(1, int(fetch_chunk_size))
        proximo_log = chunk_size

        while True:
            # Em modo de teste com limite definido, não lê mais do que o limite necessário
            if limite and total_lidos >= limite:
                break
                
            qtd_a_ler = chunk_size
            if limite and (total_lidos + qtd_a_ler) > limite:
                qtd_a_ler = limite - total_lidos

            rows = cursor.fetchmany(qtd_a_ler)
            if not rows:
                break

            for r in rows:
                resultados_raw.append(dict(zip(colunas, r)))

            total_lidos += len(rows)
            if log_callback and total_lidos >= proximo_log:
                log_callback(f"[DB PROGRESSO] Registros lidos do SQL Server: {total_lidos}")
                proximo_log += chunk_size

        cursor.close()
        conn.close()
    except Exception as e:
        return False, f"Falha na conexao ou execucao da procedure via ODBC: {str(e)}", [], []

    if not resultados_raw:
        return True, "Conexao OK, procedure executada, mas nenhuma fatura retornada para o periodo.", [], []

    # Camada de Formatação e Validação
    total_registros = len(resultados_raw)
    if log_callback:
        log_callback(f"[DB INFO] Iniciando formatacao e derivacao de {total_registros} registro(s)...")

    registros_formatados = []
    falhas_validacao = []

    for i, row in enumerate(resultados_raw, 1):
        is_ok, motivo_erro, reg_formatado = formatar_registro(row)
        if is_ok:
            registros_formatados.append(reg_formatado)
        else:
            id_ref = row.get("Nosso Número") or row.get("Nº do documento") or f"Linha_{i}"
            falhas_validacao.append({
                "id": str(id_ref),
                "motivo": motivo_erro,
                "registro_raw": row
            })
            if log_callback:
                log_callback(f"✗ [FALHA/INVALIDO] ID/NossoNumero: {id_ref} | Motivo: {motivo_erro}")

        if log_callback and (i % max(1, int(fetch_chunk_size)) == 0 or i == total_registros):
            log_callback(f"[DB FORMATACAO] Registros formatados: {i}/{total_registros}")

    msg_sucesso = f"Leitura concluida: {len(registros_formatados)} validos, {len(falhas_validacao)} inconsistencias."
    return True, msg_sucesso, registros_formatados, falhas_validacao
