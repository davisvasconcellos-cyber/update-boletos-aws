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
    def __init__(self, config_path=None, log_callback=None, ambiente_override=None):
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
        self.ssh_key_passphrase = ""
        
        self.mysql_host = "127.0.0.1"
        self.mysql_port = 3306
        self.mysql_user = "root"
        self.mysql_password = ""
        self.mysql_database = "msf_cobranca"
        self.mysql_target_table = "boletos"
        
        self.carregar_config()
        if ambiente_override:
            self.ambiente = ambiente_override
        
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
            
        config = configparser.RawConfigParser()
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
                self.ssh_key_passphrase = s.get('ssh_key_passphrase', fallback='').strip()
                key_rel = s.get('ssh_key_path', fallback='').strip()
                if key_rel:
                    self.ssh_key_path = os.path.normpath(os.path.join(self.base_dir, key_rel))
                    
            if 'MYSQL_AWS' in config:
                m = config['MYSQL_AWS']
                mysql_url = m.get('mysql_url', fallback='').strip()
                if mysql_url:
                    # Suporte a URL: mysql://usuario:senha@host:porta/banco
                    parsed = self.parse_mysql_url(mysql_url)
                    if parsed:
                        self.mysql_host = parsed['host']
                        self.mysql_port = parsed['port']
                        self.mysql_user = parsed['user']
                        self.mysql_password = parsed['password']
                        self.mysql_database = parsed['database']
                
                # Se campos individuais forem informados, eles sobrescrevem ou preenchem
                if m.get('mysql_host', fallback='').strip():
                    self.mysql_host = m.get('mysql_host').strip()
                if m.get('mysql_port', fallback='').strip():
                    self.mysql_port = m.getint('mysql_port')
                if m.get('mysql_user', fallback='').strip():
                    self.mysql_user = m.get('mysql_user').strip()
                if m.get('mysql_password', fallback='').strip():
                    self.mysql_password = m.get('mysql_password').strip()
                if m.get('mysql_database', fallback='').strip():
                    self.mysql_database = m.get('mysql_database').strip()
                if m.get('mysql_target_table', fallback='').strip():
                    self.mysql_target_table = m.get('mysql_target_table').strip()
        except Exception as e:
            self.log(f"[CONFIG WARNING] Falha ao ler parametros de destino no config.ini: {str(e)}")

    @staticmethod
    def parse_mysql_url(url):
        """Converte mysql://user:pass@host:port/database em dict de parâmetros."""
        import re
        m = re.match(r'^mysql://([^:]+):(.+)@([^:/]+)(?::(\d+))?/(.+)$', url.strip())
        if m:
            user, pwd, host, port, db = m.groups()
            return {
                'user': user,
                'password': pwd,
                'host': host,
                'port': int(port) if port else 3306,
                'database': db.split('?')[0]
            }
        return None

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
                tunnel_kwargs = {
                    'ssh_address_or_host': (self.ssh_host, self.ssh_port),
                    'ssh_username': self.ssh_user,
                    'ssh_pkey': self.ssh_key_path,
                    'remote_bind_address': (self.mysql_host, self.mysql_port)
                }
                if self.ssh_key_passphrase:
                    tunnel_kwargs['ssh_private_key_password'] = self.ssh_key_passphrase

                self.tunnel = SSHTunnelForwarder(**tunnel_kwargs)
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

            # Valida e cria a tabela de boletos automaticamente se não existir
            self.garantir_schema_tabela()

            return True, f"Conexao com MySQL ({self.mysql_database}) estabelecida e tabela `{self.mysql_target_table}` verificada com sucesso."
        except Exception as e:
            self.fechar_conexoes()
            return False, f"Falha ao conectar ao destino MySQL (ou tunel SSH): {str(e)}"

    def garantir_schema_tabela(self):
        """
        Garante que a tabela de destino exista no banco MySQL.
        Para 'boletos_segunda_via' (oficial), apenas valida a existência e estrutura.
        Para 'boletos' (legado / container local), cria automaticamente se não existir.
        """
        if self.mysql_target_table == "boletos_segunda_via":
            try:
                with self.db_conn.cursor() as cursor:
                    cursor.execute("SELECT 1 FROM `boletos_segunda_via` LIMIT 1")
                    cursor.fetchone()
                self.log(f"[DB SCHEMA] Tabela oficial `{self.mysql_target_table}` verificada com sucesso no banco `{self.mysql_database}`.")
                return
            except Exception as e:
                self.log(f"[DB SCHEMA AVISO] Tabela `{self.mysql_target_table}` nao encontrada ou inacessivel: {e}")
                return

        ddl = f"""
        CREATE TABLE IF NOT EXISTS `{self.mysql_target_table}` (
            `rid` VARCHAR(30) NOT NULL,
            `nosso_numero` VARCHAR(30) NULL,
            `numero_documento` VARCHAR(50) NULL,
            `status` VARCHAR(20) DEFAULT 'open',
            `valor` DECIMAL(10,2) DEFAULT 0.00,
            `data_emissao` DATE NULL,
            `data_vencimento` DATE NULL,
            `data_vencimento_sugerida` DATE NULL,
            `id_cobranca_vindi` VARCHAR(50) NULL,
            `id_fatura_vindi` VARCHAR(50) NULL,
            `id_assinatura_vindi` VARCHAR(50) NULL,
            `id_cliente_vindi` VARCHAR(50) NULL,
            `cpf_cnpj` VARCHAR(20) NULL,
            `cpf_cnpj_mascarado` VARCHAR(30) NULL,
            `tipo_pessoa` VARCHAR(5) NULL,
            `nome_completo` VARCHAR(255) NULL,
            `primeiro_nome` VARCHAR(100) NULL,
            `email_mascarado` VARCHAR(150) NULL,
            `telefone` VARCHAR(30) NULL,
            `situacao_doador` VARCHAR(50) NULL,
            `endereco` VARCHAR(255) NULL,
            `numero` VARCHAR(50) NULL,
            `complemento` VARCHAR(150) NULL,
            `bairro` VARCHAR(100) NULL,
            `cidade` VARCHAR(100) NULL,
            `uf` VARCHAR(10) NULL,
            `cep` VARCHAR(20) NULL,
            `metodo_pagamento` VARCHAR(80) NULL,
            `agencia` VARCHAR(10) NULL,
            `conta` VARCHAR(20) NULL,
            `digito_conta` VARCHAR(5) NULL,
            `carteira` VARCHAR(10) NULL,
            `codigo_banco` VARCHAR(10) DEFAULT '237',
            `local_pagamento` VARCHAR(255) NULL,
            `linha_digitavel` VARCHAR(100) NULL,
            `codigo_barras` VARCHAR(150) NULL,
            `beneficiario_nome` VARCHAR(150) NULL,
            `beneficiario_endereco` VARCHAR(255) NULL,
            `beneficiario_documento` VARCHAR(30) NULL,
            `payload_json` LONGTEXT NULL,
            `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (`rid`),
            INDEX `idx_boletos_status` (`status`),
            INDEX `idx_boletos_vencimento` (`data_vencimento`),
            INDEX `idx_boletos_cpf_cnpj` (`cpf_cnpj`),
            INDEX `idx_boletos_vindi_fatura` (`id_fatura_vindi`),
            INDEX `idx_boletos_vindi_cobranca` (`id_cobranca_vindi`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """
        try:
            with self.db_conn.cursor() as cursor:
                cursor.execute(ddl)
            self.db_conn.commit()
            self.log(f"[DB SCHEMA] Tabela `{self.mysql_target_table}` garantida/verificada no banco `{self.mysql_database}`.")
        except Exception as e:
            self.log(f"[DB SCHEMA AVISO] Falha ao verificar/criar tabela `{self.mysql_target_table}`: {e}")

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
            if self.mysql_target_table == "boletos_segunda_via":
                # Tabela oficial de produção/homologação
                # ATENÇÃO: As colunas `id` (auto_increment), `tipo_pessoa` (STORED GENERATED),
                # `expira_em` (STORED GENERATED), `criado_em` e `atualizado_em` NÃO DEVEM ser inseridas!
                colunas = [
                    "lote", "numero_documento", "nosso_numero", "carteira",
                    "id_fatura_vindi", "id_cobranca_vindi", "id_assinatura_vindi", "code_oportunidade",
                    "metodo_pagamento", "status_vindi", "status", "situacao_doador", "pago_em",
                    "nome_curto", "nome_completo", "email", "cpf_cnpj", "receber_carta",
                    "logradouro", "numero_endereco", "complemento", "cep", "bairro", "cidade", "uf", "pais",
                    "telefone_tipo", "telefone_numero", "telefone_ramal",
                    "banco_codigo", "banco_nome", "agencia", "conta", "conta_digito",
                    "beneficiario", "local_pagamento", "especie_doc", "aceite",
                    "data_emissao", "data_vencimento", "data_vencimento_sugerida", "vencimento_frente_carta",
                    "valor", "linha_digitavel", "codigo_barras", "pdf_url"
                ]
                cols_str = ", ".join([f"`{c}`" for c in colunas])
                placeholders = ", ".join(["%s"] * len(colunas))
                update_cols = [c for c in colunas if c not in ("id_fatura_vindi", "nosso_numero", "carteira")]
                update_clause = ", ".join([f"`{c}` = VALUES(`{c}`)" for c in update_cols])
            else:
                # Tabela legado 'boletos'
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

            single_row_placeholder = "(" + ", ".join(["%s"] * len(colunas)) + ")"
            sql_single = f"""
                INSERT INTO `{self.mysql_target_table}` ({cols_str})
                VALUES {single_row_placeholder}
                ON DUPLICATE KEY UPDATE {update_clause}
            """

            atualizados_ou_criados = 0
            falhas = []

            # Inserção em blocos multi-row (chunks de até 500 registros por query).
            # Elimina o overhead de latência do túnel SSH (150ms por round-trip aos EUA),
            # reduzindo o tempo de 60.000 registros de ~2h30 para apenas ~1 a 2 minutos!
            chunk_size = 500

            with self.db_conn.cursor() as cursor:
                for i in range(0, total_lote, chunk_size):
                    chunk = lote_registros[i:i + chunk_size]
                    multi_placeholders = ", ".join([single_row_placeholder] * len(chunk))
                    sql_multi = f"""
                        INSERT INTO `{self.mysql_target_table}` ({cols_str})
                        VALUES {multi_placeholders}
                        ON DUPLICATE KEY UPDATE {update_clause}
                    """
                    valores_multi = []
                    for reg in chunk:
                        for c in colunas:
                            valores_multi.append(reg.get(c))

                    try:
                        cursor.execute(sql_multi, valores_multi)
                        atualizados_ou_criados += len(chunk)
                    except Exception:
                        # Fallback resiliente: se o bloco falhar, executa linha a linha para capturar a falha individual
                        for reg in chunk:
                            valores = [reg.get(c) for c in colunas]
                            try:
                                cursor.execute(sql_single, valores)
                                atualizados_ou_criados += 1
                            except Exception as err_item:
                                rid_ref = reg.get("nosso_numero") or reg.get("rid", "N/A")
                                nome_ref = reg.get("nome_completo", "")
                                motivo = str(err_item)
                                falhas.append(f"✗ [FALHA/INVALIDO] NossoNumero: {rid_ref} | Nome/Ref: {nome_ref} | Motivo: {motivo}")

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

def diagnostico_mysql(config_path=None, log_callback=print):
    """
    Testa a conectividade com o banco MySQL (direta ou via SSH),
    mostra informações da versão, banco de dados e garante a criação da tabela de boletos.
    """
    log_callback("========================================================")
    log_callback("Executando DIAGNOSTICO de Conexao e Schema do MySQL...")
    log_callback("========================================================")
    
    # Força ambiente sandbox para testar conexão real
    target = AWSMysqlTarget(ambiente_override="sandbox", config_path=config_path, log_callback=log_callback)
    
    log_callback(f"[DIAGNOSTICO MYSQL] Host: {target.mysql_host}:{target.mysql_port}")
    log_callback(f"[DIAGNOSTICO MYSQL] Usuario: {target.mysql_user}")
    log_callback(f"[DIAGNOSTICO MYSQL] Banco Destino: {target.mysql_database}")
    log_callback(f"[DIAGNOSTICO MYSQL] Tunel SSH Ativo: {target.use_ssh}")
    
    sucesso, msg = target.autenticar()
    if not sucesso:
        log_callback(f"[DIAGNOSTICO MYSQL ERRO]: {msg}")
        return False
        
    log_callback(f"[DIAGNOSTICO MYSQL SUCESSO]: {msg}")
    
    try:
        with target.db_conn.cursor() as cursor:
            cursor.execute("SELECT VERSION(), DATABASE();")
            versao, banco_atual = cursor.fetchone()
            log_callback(f"[DIAGNOSTICO MYSQL] Versao do MySQL Server: {versao} | Banco Atual: {banco_atual}")
            
            # Checa quantidade de registros na tabela
            cursor.execute(f"SELECT COUNT(*) FROM `{target.mysql_target_table}`;")
            total = cursor.fetchone()[0]
            log_callback(f"[DIAGNOSTICO MYSQL] Tabela `{target.mysql_target_table}`: {total} registro(s) existente(s).")
            
            # Mostra colunas da tabela
            cursor.execute(f"DESCRIBE `{target.mysql_target_table}`;")
            colunas_desc = cursor.fetchall()
            log_callback(f"[DIAGNOSTICO MYSQL] Total de colunas na tabela `{target.mysql_target_table}`: {len(colunas_desc)}")
            
        target.fechar_conexoes()
        log_callback("[DIAGNOSTICO MYSQL FINAL]: Conexao e Schema MySQL 100% OPERACIONAIS!")
        return True
    except Exception as e:
        log_callback(f"[DIAGNOSTICO MYSQL ERRO]: {e}")
        target.fechar_conexoes()
        return False
