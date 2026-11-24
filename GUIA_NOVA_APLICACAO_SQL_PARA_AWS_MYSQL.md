# Especificação e Blueprint Arquitetural — Nova Aplicação de Sincronização (SQL Server ➔ AWS MySQL via SSH)

> **INSTRUÇÃO PARA O AGENTE DE IA NA NOVA JANELA / PASTA:**
> Este documento descreve em detalhes a arquitetura, o modelo de negócio, os padrões de código, o formato de logs, o `config.ini` e o Dashboard HTML da aplicação de referência (`update_occ_contacts`), para que você **recrie a mesma estrutura e padrão operacional** nesta nova aplicação.
>
> **O que esta nova aplicação deve fazer:**
> 1. Conectar ao **SQL Server local** via `pyodbc` (mesmo padrão da aplicação atual).
> 2. Ler registros de uma **tabela de origem** (que o usuário informará) em blocos (`fetchmany`), aplicando filtro incremental por data/hora (`last_sync_timestamp`) quando configurado.
> 3. Aplicar uma **camada de formatação/transformação de campos** (conforme documento/regras que o usuário fornecerá) antes do envio.
> 4. Enviar os dados em lotes (`max_records`) para um banco **MySQL hospedado na AWS** utilizando **autenticação/túnel SSH por certificado (`.pem`)**.
> 5. **IMPORTANTE — Fase Inicial (Modo Mockup):** Como o acesso ao banco MySQL remoto na AWS ainda não está liberado neste momento inicial, a aplicação **deve implementar um Modo Mockup (`mock_mode = true` no `config.ini`)** na camada de destino, além de já deixar a estrutura de conexão SSH + MySQL pronta. No modo Mockup, o sistema deve conectar de verdade no SQL Server, ler a tabela real, formatar os registros, simular o envio dos lotes ao MySQL registrando nos logs o payload/colunas formatadas e gerar o `dashboard.html` completo.

---

## 1. Estrutura de Diretórios Obrigatória

A nova aplicação deve seguir exatamente esta organização modular:

```text
nova_aplicacao_sync/
├── controller/
│   └── sync_controller.py          # Orquestrador: testa conexões, lê origem, formata, envia lotes, atualiza config.ini e gera dashboard
├── model/
│   ├── source_sqlserver.py         # Conexão SQL Server (pyodbc), teste rápido (SELECT TOP 1) e leitura paginada (fetchmany)
│   ├── formatter.py                # Regras de formatação, limpeza e mapeamento das colunas antes do upload
│   └── target_aws_mysql.py         # Cliente MySQL na AWS com túnel SSH por certificado (.pem) + Modo Mockup integrado
├── util/
│   └── paths.py                    # Resolução de diretório raiz compatível com script .py e executável PyInstaller (.exe)
├── log_dashboard/
│   ├── dashboard_generator.py      # Gerador do relatório visual HTML (Bootstrap 5 + Accordion + Abas de Falhas e Log Bruto)
│   └── dashboard.html              # Relatório interativo gerado automaticamente ao final de cada execução
├── logs/                           # Logs detalhados por execução: exec_YYYY-MM-DD_HH-MM-SS.log
├── config.ini                      # Configuração centralizada (SQL Server, AWS MySQL, SSH, Processamento, Mockup e Logs)
├── main.py                         # Ponto de entrada (entry point) com suporte a argumentos CLI (testmode / normal)
├── Compilador.bat                  # Script para compilar em main.exe (--onefile) via PyInstaller com backup automático
├── rodar_update.bat                # Atalho para execução em modo normal/produção
├── rodar_teste.bat                 # Atalho para execução em modo de teste (1 único lote limitado)
├── .gitignore                      # Ignora build/, dist/, *.exe, *.spec, __pycache__/, logs/, log_dashboard/dashboard.html
└── README.md                       # Documentação completa da nova aplicação
```

---

## 2. Modelo do Arquivo `config.ini`

O arquivo `config.ini` fica na raiz do projeto (ao lado de `main.py` e `main.exe`) e deve seguir este formato:

```ini
[banco]
# IP do servidor SQL Server de origem
servidor_ip = 192.168.1.20
database = SALESFORCE
tabela_origem = NOME_DA_TABELA_A_DEFINIR
coluna_data_corte = UpdateDateList

[AMBIENTE]
# Valores aceitos: mockup, sandbox, prod
# Enquanto o acesso ao MySQL AWS nao estiver disponivel, manter como mockup
ambiente = mockup

[SSH]
# Configuracoes do tunel SSH por certificado para chegar ao MySQL na AWS
use_ssh_tunnel = true
ssh_host = ec2-xx-xx-xx-xx.compute-1.amazonaws.com
ssh_port = 22
ssh_user = ec2-user
ssh_key_path = certs/chave_aws.pem

[MYSQL_AWS]
# Configuracoes do banco MySQL remoto (quando via SSH tunnel, o host remoto visto pelo bastion ou RDS endpoint)
mysql_host = meu-banco.xxxxxx.us-east-1.rds.amazonaws.com
mysql_port = 3306
mysql_user = usuario_sync
mysql_password = 
mysql_database = nome_base_aws
mysql_target_table = tabela_destino_mysql

[PROCESSAMENTO]
test_mode = false
max_records = 50
db_query_timeout_seconds = 180
db_fetch_chunk_size = 1000
last_sync_timestamp = 

[LOG]
diretorio = logs/
dashboard_html = log_dashboard/dashboard.html
```

---

## 3. Especificação Técnica de Cada Componente

### 3.1. Resolução de Diretório Base (`util/paths.py`)

Garante que a aplicação encontre o `config.ini`, a pasta `logs/`, os certificados SSH e o `log_dashboard/dashboard.html` tanto rodando via `py main.py` quanto compilada em `.exe` via PyInstaller:

```python
import sys
import os

def get_base_dir():
    """
    Retorna o diretorio raiz da aplicacao.
    Funciona tanto rodando via script .py quanto compilado via .exe pelo PyInstaller.
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```

---

### 3.2. Ponto de Entrada e Argumentos de Linha de Comando (`main.py`)

O `main.py` lê o `config.ini` e permite sobrescrever o modo de execução via terminal:
- `main.exe` ou `py main.py`: executa conforme o `config.ini`.
- `main.exe testmode` ou `py main.py testmode`: força `test_mode = True` (busca com `TOP (max_records)`, processa apenas **1 único lote** e **não atualiza** o `last_sync_timestamp` no `config.ini`).
- `main.exe testmode 10`: força `test_mode = True` com `max_records = 10`.
- `main.exe normal`: força `test_mode = False` (modo produção completo).

---

### 3.3. Camada de Origem SQL Server (`model/source_sqlserver.py`)

1. **String de Conexão ODBC**:
   ```python
   string_conexao = f'DRIVER={{SQL Server}};SERVER={servidor};DATABASE={database};UID=PROGSPY1;PWD=QAZWSX12!'
   conn = pyodbc.connect(string_conexao, timeout=int(connect_timeout_seconds))
   ```
2. **Teste Rápido de Conectividade (`testar_conexao_db()`)**:
   - Antes de rodar a query principal, executa `SELECT TOP 1 * FROM <tabela_origem> (NOLOCK)` com timeout curto (10s) para validar acesso de rede e permissão na tabela.
3. **Filtro Incremental (`data_corte` / `last_sync_timestamp`)**:
   - Se `last_sync_timestamp` estiver preenchido no `config.ini`:
     - Filtra `<coluna_data_corte> >= '<last_sync_timestamp>'`
     - Loga: `[DB QUERY] Aplicando data de corte (<coluna_data_corte>): <valor>`
   - Se `last_sync_timestamp` estiver em branco (ou se a tabela não usar filtro de data inicial, conforme instrução do usuário):
     - Usa o padrão do dia corrente (`>= CONVERT(date, GETDATE())`) ou a regra definida para a tabela.
4. **Modo de Teste (`limite`)**:
   - Quando `test_mode = True`, aplica `SELECT TOP ({int(limite)}) ...` na query SQL para resposta imediata.
5. **Leitura Paginada do Cursor (`fetchmany`)**:
   - Configura `cursor.timeout = max(1, int(query_timeout_seconds))`.
   - Lê em blocos de `db_fetch_chunk_size` (ex.: 1000 registros por vez) via `cursor.fetchmany(chunk_size)`, emitindo log de progresso:
     `[DB PROGRESSO] Registros lidos ate o momento: {total_lidos}`.
6. **Acionamento da Camada de Formatação (`model/formatter.py`)**:
   - Converte cada linha lida do banco através de `formatar_registro(linha_raw)` e emite log a cada bloco:
     `[DB FORMATACAO] Registros formatados: {i}/{total_resultados}`.

---

### 3.4. Camada de Formatação de Campos (`model/formatter.py`)

Deve ser criada como um módulo isolado e limpo (`formatar_registro(row_dict)` -> `(is_valido, motivo_erro, registro_formatado)`):
- Recebe o dicionário bruto vindo do SQL Server (`row_dict`).
- Aplica todas as regras de formatação de strings, datas, números, CPF/CNPJ, booleanos, tratamento de `NULL` e mapeamento de nomes de colunas conforme o documento de especificação de campos que o usuário fornecerá.
- Caso um registro possua dado obrigatório inválido que impeça a formatação, pode retornar `(False, "Motivo da invalidacao", registro_parcial)` para já ser contabilizado e exibido na lista de falhas do Dashboard.

---

### 3.5. Camada de Destino: AWS MySQL com SSH por Certificado + Modo Mockup (`model/target_aws_mysql.py`)

Esta classe (`AWSMysqlTarget`) deve suportar **dois modos de operação** controlados pela chave `ambiente` (ou `mock_mode`) no `config.ini`:

#### A) Modo Mockup (`ambiente = mockup`) — **ATIVO INICIALMENTE**
- Não exige conexão de rede com a AWS nem pacotes externos de SSH ativos para rodar os testes locais de leitura e formatação.
- `autenticar()` / `testar_conexao_destino()`:
  - Retorna `True, "Modo MOCKUP ativo -> Simulando tunel SSH e banco MySQL AWS"`.
- `enviar_lote(lote_registros)`:
  - Valida a estrutura dos registros formatados do lote.
  - No primeiro lote (ou em modo de teste), imprime no log uma amostra de 1 a 3 registros formatados em JSON (`[MOCKUP PAYLOAD SAMPLE]`) para que o usuário possa auditar visualmente no log e no Dashboard se a formatação dos campos ficou perfeita!
  - Simula a contabilização e retorna exatamente o padrão de texto esperado pelo gerador de Dashboard:
    ```text
    RESUMO DESTINO (MOCKUP AWS MYSQL): STATUS 200 | Total=49 | Atualizados=49 | Criados=0 | Falhas=0

    DETALHES DE FALHAS (0):
    Nenhuma falha individual registrada.
    ```

#### B) Modo Real AWS MySQL via SSH Certificate (`ambiente = sandbox` ou `ambiente = prod`)
- Utiliza `sshtunnel.SSHTunnelForwarder` (ou `paramiko`) + `pymysql`:
  - Abre túnel SSH usando `ssh_host`, `ssh_port`, `ssh_user` e o arquivo de certificado `ssh_key_path` (`mypkey` / `.pem`), fazendo bind para `(mysql_host, mysql_port)`.
  - Conecta ao MySQL local na porta `server.local_bind_port` via `pymysql.connect(...)`.
  - Executa `INSERT INTO <mysql_target_table> (...) VALUES (...) ON DUPLICATE KEY UPDATE ...` em lotes transacionais.
  - Caso algum registro falhe individualmente, captura o erro no formato padrão:
    `✗ [FALHA/INVALIDO] ID: <id> | Nome/Ref: <ref> | Motivo: <erro>`
  - Mantém o contrato de retorno `(lote_processado_ok, mensagem_resumo)` onde `lote_processado_ok = True` sempre que o lote foi processado (mesmo com rejeições individuais de dados), retornando `False` apenas em falha crítica de conexão SSH/MySQL.

---

### 3.6. Orquestrador e Regra de Atualização do `last_sync_timestamp` (`controller/sync_controller.py`)

O fluxo em `executar_fluxo()` deve seguir exatamente estas etapas:

1. **Captura do início da execução**:
   ```python
   inicio_execucao = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
   ```
2. **Teste de conexão com o SQL Server (`testar_conexao_db()`)**:
   - Se falhar, loga o erro e interrompe sem alterar o `last_sync_timestamp`.
3. **Busca e formatação dos registros (`buscar_registros()`)**:
   - Se `test_mode = True`, passa `limite=self.max_records`.
   - Se não houver registros novos (`len(registros) == 0`) e `not self.test_mode`, atualiza o `last_sync_timestamp` no `config.ini` para `inicio_execucao`.
4. **Preparação / Conexão ao Destino (Mockup ou AWS MySQL via SSH)**:
   - Valida a disponibilidade do destino.
5. **Fatiamento e Envio em Lotes**:
   - Em `test_mode = True`, garante o envio de apenas **1 único lote** de até `max_records`.
   - Em `test_mode = False`, divide todos os registros em lotes de tamanho `max_records`:
     ```python
     lotes = [registros[i:i + tamanho_lote] for i in range(0, total_registros, tamanho_lote)]
     ```
   - Para cada lote, loga:
     `--- Enviando lote {index}/{len(lotes)} ({len(lote)} registros) ---`
6. **Regra de Atualização do `last_sync_timestamp` no `config.ini`**:
   - **Avança o `last_sync_timestamp`** para `inicio_execucao` sempre que `not self.test_mode` e os lotes tiverem sido processados (mesmo que algum registro individual tenha apresentado erro de validação de dados, pois o erro individual já fica registrado no log e no Dashboard).
   - **NÃO avança o `last_sync_timestamp`** quando `self.test_mode == True` ou quando ocorrer **erro crítico de infraestrutura** (queda de conexão SSH/MySQL/SQL Server que impeça o processamento de um lote).

---

### 3.7. Logs e Dashboard HTML Interativo (`log_dashboard/dashboard_generator.py`)

- **Arquivos de log**: gravados em `logs/exec_YYYY-MM-DD_HH-M-SS.log` com `print(log_line, flush=True)` simultâneo no console.
- **Dashboard HTML (`log_dashboard/dashboard.html`)**:
  - Ao final de toda execução (dentro de um bloco `try/finally` ou após o fluxo principal), `DashboardGenerator().generate()` lê todos os arquivos `logs/*.log` (do mais recente para o mais antigo).
  - Extrai via regex as métricas de cada lote:
    ```python
    resumo_matches = re.findall(r'Total=(\d+)\s*\|\s*(?:Atualizados|Sucesso)=(\d+)\s*\|\s*(?:Criados=(\d+)\s*\|)?\s*Falhas=(\d+)', content)
    ```
  - Extrai todas as linhas contendo `✗ [FALHA/INVALIDO]` para exibir na aba **Lista de Falhas**.
  - Gera um painel Bootstrap 5 com cards de resumo (`Total Processados`, `Atualizados / Criados`, `Falhas`, `Tipo de Carga: Teste Limitado / Completa Diária / Mockup`), Accordion por execução e duas abas por execução:
    1. **Lista de Falhas**: registros com inconsistência destacados em vermelho.
    2. **Log Bruto de Execução**: terminal completo (incluindo a amostra de dados formatados no modo Mockup).

---

### 3.8. Scripts Batch de Operação e Compilação

Criar na raiz do novo projeto:
1. **`rodar_update.bat`**: executa `main.exe` (ou `py main.py` caso `main.exe` ainda não tenha sido compilado) em modo normal e informa o caminho de `log_dashboard\dashboard.html`.
2. **`rodar_teste.bat`**: executa `main.exe testmode` (ou `py main.py testmode`) para rodar apenas 1 lote de teste.
3. **`Compilador.bat`**:
   - Instala dependências (`pyinstaller`, `pyodbc`, `pymysql`, `sshtunnel`, `paramiko`).
   - Compila com `py -m PyInstaller --onefile main.py`.
   - Renomeia o `main.exe` anterior para `main_YYYYMMDD_HHMM.exe` (backup) e copia `dist\main.exe` para a raiz.

---

## 4. Roteiro Passo a Passo para o Agente na Nova Janela

Ao ler este documento na nova pasta do projeto, siga esta ordem:

1. **Verifique com o usuário as informações da tabela de origem e formatação**:
   - Qual o nome da tabela (ou view/query) no SQL Server que será lida?
   - Qual o banco (`DATABASE`) e IP do SQL Server (ex.: `192.168.1.20` / `SALESFORCE`)?
   - Existe uma coluna de data/hora para corte incremental (`last_sync_timestamp`) nessa tabela? Qual o nome dela?
   - Solicite ou leia o documento de mapeamento/formatação dos campos que o usuário informou que vai passar.
2. **Crie toda a estrutura de pastas e arquivos** seguindo o padrão acima, começando com `ambiente = mockup` no `config.ini`.
3. **Implemente a conexão real com o SQL Server** (`model/source_sqlserver.py`) e a **camada de formatação** (`model/formatter.py`) de acordo com o documento de campos do usuário.
4. **Implemente o destino (`model/target_aws_mysql.py`)** já com:
   - O **Modo Mockup** totalmente funcional (exibindo amostra dos registros formatados no log para validação imediata).
   - O esqueleto completo da conexão **SSH com Certificado (`.pem`) + MySQL AWS** pronto para ser ativado assim que o usuário receber os dados de acesso da AWS.
5. **Teste a leitura e formatação em Modo de Teste (`testmode`)**, gere o `log_dashboard/dashboard.html` e valide os campos formatados junto ao usuário.
