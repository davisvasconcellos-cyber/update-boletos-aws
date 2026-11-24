# -*- coding: utf-8 -*-
"""
Controlador Orquestrador da Sincronização (controller/sync_controller.py)
Gerencia o fluxo completo:
  1. Testa conexão com SQL Server
  2. Executa a procedure CarregaFaturasBoletoWS e formata os dados
  3. Prepara a conexão com o destino (AWS MySQL via SSH ou Mockup)
  4. Fatia os registros em lotes (max_records) e dispara o envio
  5. Atualiza o last_sync_timestamp no config.ini (se modo normal e sem erro crítico)
  6. Gera o dashboard HTML interativo em log_dashboard/dashboard.html
"""

import os
import datetime
import configparser

from util.paths import get_base_dir
from model.source_sqlserver import testar_conexao_db, buscar_e_formatar_boletos
from model.target_aws_mysql import AWSMysqlTarget
from log_dashboard.dashboard_generator import DashboardGenerator

class SyncController:
    def __init__(self, test_mode=False, max_records=50, db_query_timeout_seconds=180, db_fetch_chunk_size=1000, last_sync_timestamp="", config_path=None):
        self.test_mode = test_mode
        self.max_records = max_records
        self.db_query_timeout_seconds = db_query_timeout_seconds
        self.db_fetch_chunk_size = db_fetch_chunk_size
        self.last_sync_timestamp = last_sync_timestamp
        
        self.base_dir = get_base_dir()
        self.config_path = config_path or os.path.join(self.base_dir, 'config.ini')
        
        # Cria diretório de logs
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        os.makedirs(self.logs_dir, exist_ok=True)
        
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        self.log_file = os.path.join(self.logs_dir, f'exec_{timestamp}.log')
        
        # Inicializa o cliente de destino
        self.target = AWSMysqlTarget(config_path=self.config_path, log_callback=self.log)

    def log(self, message):
        """Imprime no console em tempo real (flush=True) e grava no arquivo de log."""
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"[{timestamp}] {message}"
        print(log_line, flush=True)
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_line + '\n')
        except Exception:
            pass

    def atualizar_config_last_sync(self, inicio_execucao):
        """Salva a data de início da execução como nova data de corte no config.ini."""
        if not self.config_path or not os.path.exists(self.config_path):
            self.log("[CONFIG WARNING] Caminho do config.ini nao encontrado para atualizar last_sync_timestamp.")
            return

        try:
            config = configparser.ConfigParser()
            config.read(self.config_path, encoding='utf-8')
            if 'PROCESSAMENTO' not in config:
                config['PROCESSAMENTO'] = {}
            config['PROCESSAMENTO']['last_sync_timestamp'] = inicio_execucao
            with open(self.config_path, 'w', encoding='utf-8') as f:
                config.write(f)
            self.log(f"[CONFIG SUCCESS] last_sync_timestamp atualizado no config.ini para: {inicio_execucao}")
        except Exception as e:
            self.log(f"[CONFIG ERROR] Falha ao atualizar last_sync_timestamp no config.ini: {str(e)}")

    def executar_fluxo(self):
        """Executa a rotina completa de sincronização."""
        modo_str = f" (MODO DE TESTE - 1 LOTE DE ATE {self.max_records})" if self.test_mode else f" (MODO NORMAL - LOTES DE ATE {self.max_records})"
        self.log(f"=== INICIO DA SINCRONIZACAO DE BOLETOS AWS{modo_str} ===")
        self.log(f"[AMBIENTE DESTINO]: {self.target.ambiente.upper()} (Tabela: {self.target.mysql_target_table})")

        try:
            inicio_execucao = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # 1. Teste de conectividade com o banco de dados SQL Server
            self.log("Testando conectividade com o SQL Server...")
            conn_ok, conn_msg = testar_conexao_db()
            self.log(f"[DB CONEXAO STATUS]: {conn_msg}")
            
            if not conn_ok:
                self.log("Processo interrompido por falha na conexao inicial com o SQL Server.")
                return

            # 2. Busca e formatação dos boletos via Stored Procedure
            self.log("Executando Stored Procedure e formatando boletos...")
            limite_busca = self.max_records if self.test_mode else None
            
            sp_ok, sp_msg, registros, falhas_validacao = buscar_e_formatar_boletos(
                limite=limite_busca,
                data_corte=self.last_sync_timestamp,
                query_timeout_seconds=self.db_query_timeout_seconds,
                fetch_chunk_size=self.db_fetch_chunk_size,
                log_callback=self.log
            )
            self.log(f"[DB RESULTADO STATUS]: {sp_msg}")

            if not sp_ok:
                self.log("Processo interrompido por falha na execucao da procedure no SQL Server.")
                return

            if not registros:
                self.log("Nenhum boleto retornado para processar.")
                if not self.test_mode:
                    self.atualizar_config_last_sync(inicio_execucao)
                return

            total_boletos = len(registros)
            self.log(f"Boletos selecionados e formatados com sucesso: {total_boletos} registro(s).")

            # 3. Autenticação e preparação do destino
            self.log("Autenticando e preparando conexao de destino...")
            dest_ok, dest_msg = self.target.autenticar()
            self.log(f"[DESTINO STATUS]: {dest_msg}")

            if not dest_ok:
                self.log("Processo interrompido por falha na conexao de destino.")
                return

            # 4. Divisão em lotes e envio
            if self.test_mode:
                registros = registros[:self.max_records]
                tamanho_lote = len(registros)
                self.log(f"[MODO TESTE ATIVADO] Enviando 1 unico lote de teste contendo {tamanho_lote} registro(s).")
            else:
                tamanho_lote = self.max_records

            total_a_enviar = len(registros)
            lotes = [registros[i:i + tamanho_lote] for i in range(0, total_a_enviar, tamanho_lote)]
            self.log(f"Total de registros a enviar: {total_a_enviar} em {len(lotes)} lote(s) (tamanho max lote: {tamanho_lote}).")

            sucesso_geral = True
            for index, lote in enumerate(lotes, 1):
                self.log(f"--- Enviando lote {index}/{len(lotes)} ({len(lote)} registros) ---")
                lote_ok, lote_resumo = self.target.enviar_lote(lote)
                self.log(f"[LOTE {index} RESUMO]: \n{lote_resumo}")
                if not lote_ok:
                    sucesso_geral = False

            # 5. Atualização de corte incremental
            if sucesso_geral and not self.test_mode:
                self.atualizar_config_last_sync(inicio_execucao)
            elif self.test_mode:
                self.log("[MODO TESTE] last_sync_timestamp nao foi atualizado no config.ini (execucao de teste).")
            else:
                self.log("[CONFIG WARNING] last_sync_timestamp nao foi atualizado devido a erro critico em um ou mais lotes.")

        except KeyboardInterrupt:
            self.log("Execucao interrompida manualmente pelo usuario (Ctrl+C).")
        except Exception as e:
            self.log(f"ERRO CRITICO durante a execucao: {str(e)}")
        finally:
            self.target.fechar_conexoes()
            self.log("=== FIM DA EXECUCAO ===")
            
            # 6. Geração do Dashboard HTML
            try:
                self.log("Gerando Dashboard HTML incremental...")
                gen = DashboardGenerator()
                dash_path = gen.generate()
                self.log(f"Dashboard gerado com sucesso em: {dash_path}")
            except Exception as e:
                self.log(f"Falha ao gerar o dashboard HTML: {str(e)}")
