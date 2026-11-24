# -*- coding: utf-8 -*-
import pyodbc

conn_str = 'DRIVER={SQL Server};SERVER=192.168.1.20;DATABASE=VINDI;UID=PROGSPY1;PWD=QAZWSX12!'
print('Tentando conectar ao SQL Server 192.168.1.20 na base VINDI...')

try:
    conn = pyodbc.connect(conn_str, timeout=8)
    cursor = conn.cursor()
    print('Conexao estabelecida com sucesso!')
    
    # 1. Verifica se a procedure existe
    sql_check = "SELECT ROUTINE_SCHEMA, ROUTINE_NAME, CREATED, LAST_ALTERED FROM INFORMATION_SCHEMA.ROUTINES WHERE ROUTINE_NAME = 'CarregaFaturasBoletoWS'"
    cursor.execute(sql_check)
    row = cursor.fetchone()
    if row:
        print(f'Procedure encontrada no banco VINDI: Schema={row[0]} | Nome={row[1]} | Alterada em={row[3]}')
    else:
        print('Aviso: Routine nao encontrada via INFORMATION_SCHEMA. Testando execucao direta...')
        
    # 2. Executa a procedure
    print("Executando: EXEC CarregaFaturasBoletoWS '2026-12-01', '2027-01-01' ...")
    cursor.execute("EXEC CarregaFaturasBoletoWS '2026-12-01', '2027-01-01'")
    
    if cursor.description:
        colunas = [col[0] for col in cursor.description]
        print(f'\nTotal de colunas retornadas: {len(colunas)}')
        print('Colunas:', colunas)
        
        primeira_linha = cursor.fetchone()
        if primeira_linha:
            print('\nPrimeira linha retornada da base real:')
            for col, val in zip(colunas, primeira_linha):
                print(f'  {col}: {val}')
        else:
            print('Nenhum registro retornado para este periodo.')
    else:
        print('Nenhum cursor.description retornado.')
        
    cursor.close()
    conn.close()
    print('\n[SUCESSO] Procedure CarregaFaturasBoletoWS testada com sucesso na base VINDI!')
except Exception as e:
    print('\n[FALHA NO TESTE]:', e)
