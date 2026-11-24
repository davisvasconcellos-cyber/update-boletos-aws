# -*- coding: utf-8 -*-
"""
Módulo de Destino AWS MySQL com Túnel SSH e Modo Mockup (model/target_aws_mysql.py)
Suporta:
  - Modo Mockup (ambiente = mockup): simula o envio e imprime amostras de payload para validação.
  - Modo Real (ambiente = sandbox / prod): abre túnel SSH por certificado (.pem) com sshtunnel
    e executa upsert em lote com pymysql.
"""

import os
import json
import configparser
from util.paths import get_base_dir

class AWSMysqlTarget:
    def __init__(self, config_path=None, log_callback=None):
        self.log_callback = log_callback
        self.base_dir = get_base_dir()
        self.config_path = config_path or os.path.join(self.base_dir, 'config.ini')
        
        # Defaults
        self.ambiente = "mockup"
        self.use_ssh = True
        self.ssh_host = ""
        self.ssh_port = 22
        self.ssh_user = "ec2-user"
        self.ssh_key_path = ""
        
        self.mysql_host = "127.0.0.1"
        self.mysql_port = 3306
        self.mysql_user = "root"
        self.mysql_password = ""
        self.mysql_database = "msf_cobranca"
        self.mysql_target_table = "boletos"
        
        self.carregar_config()
        
        # Objetos de conexão em modo real
        self.tunnel = None
        self.db_conn = None
        self.primeiro_lote_enviado = False

    def log(self, msg):
        if self.log_callback:
            self.log_callback(msg)
        else:
            print(msg)

    def carregar_config(self):
        if not os.path.exists(self.config_path):
            return
            
        config = configparser.ConfigParser()
        try:
            config.read(self.config_path, encoding='utf-8')
            if 'AMBIENTE' in config:
                self.ambiente = config['AMBIENTE'].get('ambiente', fallback='mockup').strip().lower()
                
            if 'SSH' in config:
                s = config['SSH']
                self.use_ssh = s.getboolean('use_ssh_tunnel', fallback=True)
                self.ssh_host = s.get('ssh_host', fallback='').strip()
                self.ssh_port = s.getint('ssh_port', fallback=22)
                self.ssh_user = s.get('ssh_user', fallback='ec2-user').strip()
                key_rel = s.get('ssh_key_path', fallback='').strip()
                if key_rel:
                    self.ssh_key_path = os.path.normpath(os.path.join(self.base_dir, key_rel))
                    
            if 'MYSQL_AWS' in config:
                m = config['MYSQL_AWS']
                self.mysql_host = m.get('mysql_host', fallback='').strip()
                self.mysql_port = m.getint('mysql_port', fallback=3306)
                self.mysql_user = m.get('mysql_user', fallback='').strip()
                self.mysql_password = m.get('mysql_password', fallback='').strip()
                self.mysql_database = m.get('mysql_database', fallback='msf_cobranca').strip()
                self.mysql_target_table = m.get('mysql_target_table', fallback='boletos').strip()
        except Exception as e:
            self.log(f"[CONFIG WARNING] Falha ao ler parametros de destino no config.ini: {str(e)}")

    def is_mockup(self):
        return self.ambiente == "mockup"

    def autenticar(self):
        """Valida a conectividade ou inicializa o túnel SSH e banco MySQL."""
        if self.is_mockup():
            msg = f"Modo MOCKUP ativo (ambiente={self.ambiente}) -> Simulando tunel SSH e banco MySQL AWS ({self.mysql_target_table})"
            return True, msg

        # Modo Real: Conexão SSH + MySQL
        try:
            import pymysql
            from sshtunnel import SSHTunnelForwarder
            
            if self.use_ssh:
                if not os.path.exists(self.ssh_key_path):
                    return False, f"Arquivo de chave SSH (.pem) nao encontrado em: {self.ssh_key_path}"

                self.log(f"[SSH INFO] Iniciando tunel SSH para {self.ssh_host}:{self.ssh_port} via chave {os.path.basename(self.ssh_key_path)}...")
                self.tunnel = SSHTunnelForwarder(
                    (self.ssh_host, self.ssh_port),
                    ssh_username=self.ssh_user,
                    ssh_pkey=self.ssh_key_path,
                    remote_bind_address=(self.mysql_host, self.mysql_port)
                )
                self.tunnel.start()
                local_port = self.tunnel.local_bind_port
                self.log(f"[SSH SUCCESS] Tunel SSH ativo! Porta local mapeada: {local_port}")
                
                # Conecta ao MySQL através da porta mapeada do túnel
                self.db_conn = pymysql.connect(
                    host='127.0.0.1',
                    port=local_port,
                    user=self.mysql_user,
                    password=self.mysql_password,
                    database=self.mysql_database,
                    charset='utf8mb4',
                    connect_timeout=15,
                    autocommit=False
                )
            else:
                self.log(f"[MYSQL DIRECT] Conectando direto ao MySQL em {self.mysql_host}:{self.mysql_port}...")
                self.db_conn = pymysql.connect(
                    host=self.mysql_host,
                    port=self.mysql_port,
                    user=self.mysql_user,
                    password=self.mysql_password,
                    database=self.mysql_database,
                    charset='utf8mb4',
                    connect_timeout=15,
                    autocommit=False
                )

            with self.db_conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()

            return True, f"Conexao com MySQL AWS ({self.mysql_database}) estabelecida com sucesso."
        except Exception as e:
            self.fechar_conexoes()
            return False, f"Falha ao conectar ao destino AWS MySQL via SSH: {str(e)}"

    def enviar_lote(self, lote_registros):
        """
        Envia um lote de registros formatados para o destino.
        Retorna: (lote_processado_ok: bool, mensagem_resumo: str)
        """
        if not lote_registros:
            return True, "Lote vazio. Nenhum registro para enviar."

        total_lote = len(lote_registros)

        # ---------------- MODO MOCKUP ----------------
        if self.is_mockup():
            # No primeiro lote, imprime amostra formatada em JSON no log para conferência
            if not self.primeiro_lote_enviado:
                self.primeiro_lote_enviado = True
                amostra = lote_registros[:min(2, len(lote_registros))]
                self.log("\n================ [MOCKUP PAYLOAD SAMPLE] ================")
                for idx, reg in enumerate(amostra, 1):
                    # Mostra o JSON do contrato
                    payload_dict = json.loads(reg.get("payload_json", "{}"))
                    self.log(f"--- Amostra {idx} (rid: {reg.get('rid')}) ---")
                    self.log(json.dumps(payload_dict, indent=2, ensure_ascii=False))
                self.log("=========================================================\n")

            resumo = (
                f"RESUMO DESTINO (MOCKUP AWS MYSQL): STATUS 200 | Total={total_lote} | "
                f"Atualizados={total_lote} | Criados=0 | Falhas=0\n\n"
                f"DETALHES DE FALHAS (0):\n"
                f"Nenhuma falha individual registrada."
            )
            return True, resumo

        # ---------------- MODO REAL (AWS MYSQL) ----------------
        try:
            colunas = [
                "rid", "nosso_numero", "numero_documento", "status", "valor",
                "data_emissao", "data_vencimento", "data_vencimento_sugerida",
                "id_cobranca_vindi", "id_fatura_vindi", "id_assinatura_vindi", "id_cliente_vindi",
                "cpf_cnpj", "cpf_cnpj_mascarado", "tipo_pessoa", "nome_completo", "primeiro_nome",
                "email_mascarado", "telefone", "situacao_doador", "endereco", "numero", "complemento", "bairro", "cidade", "uf", "cep",
                "metodo_pagamento", "agencia", "conta", "digito_conta", "carteira", "codigo_banco",
                "local_pagamento", "linha_digitavel", "codigo_barras", "beneficiario_nome", "beneficiario_endereco", "beneficiario_documento",
                "payload_json"
            ]

            cols_str = ", ".join([f"`{c}`" for c in colunas])
            placeholders = ", ".join(["%s"] * len(colunas))
            update_clause = ", ".join([f"`{c}` = VALUES(`{c}`)" for c in colunas if c != "rid"])

            sql_upsert = f"""
                INSERT INTO `{self.mysql_target_table}` ({cols_str})
                VALUES ({placeholders})
                ON DUPLICATE KEY UPDATE {update_clause}
            """

            atualizados_ou_criados = 0
            falhas = []

            with self.db_conn.cursor() as cursor:
                for reg in lote_registros:
                    valores = [reg.get(c) for c in colunas]
                    try:
                        cursor.execute(sql_upsert, valores)
                        atualizados_ou_criados += 1
                    except Exception as err_item:
                        rid_ref = reg.get("rid", "N/A")
                        nome_ref = reg.get("nome_completo", "")
                        motivo = str(err_item)
                        falhas.append(f"✗ [FALHA/INVALIDO] ID: {rid_ref} | Nome/Ref: {nome_ref} | Motivo: {motivo}")

                self.db_conn.commit()

            total_falhas = len(falhas)
            detalhes_falhas_str = "\n".join(falhas) if falhas else "Nenhuma falha individual registrada."

            resumo = (
                f"RESUMO DESTINO (AWS MYSQL): STATUS 200 | Total={total_lote} | "
                f"Atualizados={atualizados_ou_criados} | Criados=0 | Falhas={total_falhas}\n\n"
                f"DETALHES DE FALHAS ({total_falhas}):\n"
                f"{detalhes_falhas_str}"
            )
            return True, resumo

        except Exception as e:
            if self.db_conn:
                try:
                    self.db_conn.rollback()
                except Exception:
                    pass
            return False, f"ERRO CRITICO no envio do lote ao MySQL AWS: {str(e)}"

    def fechar_conexoes(self):
        """Encerra com segurança a conexão MySQL e o túnel SSH."""
        if self.db_conn:
            try:
                self.db_conn.close()
            except Exception:
                pass
            self.db_conn = None

        if self.tunnel:
            try:
                self.tunnel.stop()
            except Exception:
                pass
            self.tunnel = None
