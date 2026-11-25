# update_boletos_aws — Sincronização de Boletos (SQL Server ➔ AWS MySQL via SSH)

Aplicação modular de alta performance para extração, transformação e sincronização de dados de cobrança por **Boletos Bancários** do **SQL Server local** para um banco de dados **MySQL hospedado na AWS**, utilizando **Túnel SSH autenticado por certificado (`.pem`)** e **Modo Mockup** para validação operacional de dados.

Desenvolvida pela equipe de tecnologia de **Médicos Sem Fronteiras (MSF)**, seguindo a arquitetura operacional consolidada do `update_occ_contacts`.

---

## 1. Visão Geral e Modelo de Negócio

Esta aplicação automatiza a disponibilização dos dados de faturas de boletos para a página e API de segunda via e renegociação de doações de MSF.

- **Origem dos Dados:** Stored Procedure `CarregaFaturasBoletoWS` no SQL Server (banco de dados `VINDI` no host `192.168.1.20`).
- **Camada de Transformação:** Regras de negócio e sanitização de dados baseadas no modelo **FingerPrint (CNAB)** e na especificação de 32 campos da Vindi/Bradesco.
- **Destino dos Dados:** Banco MySQL na AWS (tabela `boletos`), acessado de forma segura através de um túnel SSH com autenticação por chave privada (`.pem` / `id_ed25519`).
- **Padrão de Resiliência:** 
  - **Modo Mockup (`ambiente = mockup`)**: permite rodar a extração real no SQL Server, aplicar todas as regras de derivação, gerar CSVs de auditoria e relatórios visuais no Dashboard sem depender da liberação prévia de portas de rede na AWS.
  - **Backup Físico em CSV (`gerar_csv_backup = true`)**: exporta automaticamente uma cópia física em `backups_csv/` de todos os registros enriquecidos enviados em cada execução.
  - **Corte Incremental (`last_sync_timestamp`)**: garante idempotência e rastreabilidade entre as execuções diárias.

---

## 2. Estrutura de Diretórios

```text
update_boletos_aws/
├── controller/
│   └── sync_controller.py          # Orquestrador: testa conexões, executa SP, fatia lotes, atualiza config e gera dashboard
├── model/
│   ├── source_sqlserver.py         # Conexão SQL Server (pyodbc), chamada da SP CarregaFaturasBoletoWS e fetch paginado
│   ├── formatter.py                # Regras de transformação e derivação (DERIVAR) dos 32 campos do FingerPrint
│   └── target_aws_mysql.py         # Cliente AWS MySQL: Túnel SSH (.pem) via sshtunnel/pymysql + Modo Mockup
├── util/
│   └── paths.py                    # Resolução do diretório raiz para script .py e executável PyInstaller (.exe)
├── log_dashboard/
│   ├── dashboard_generator.py      # Gerador do relatório visual HTML (Bootstrap 5, Accordion, abas de falhas e log bruto)
│   └── dashboard.html              # Painel interativo gerado automaticamente ao final de cada execução
├── logs/                           # Arquivos de log por execução: exec_YYYY-MM-DD_HH-MM-SS.log
├── config.ini                      # Configuração centralizada (banco, datas, SSH, MySQL AWS, timeouts)
├── main.py                         # Ponto de entrada com argumentos CLI (testmode / normal)
├── rodar_update.bat                # Atalho para execução em produção / normal
├── rodar_teste.bat                 # Atalho para execução em modo de teste (1 lote limitado)
├── Compilador.bat                  # Script para compilar em main.exe com backup automático
├── .gitignore                      # Proteção de credenciais, certificados *.pem, executáveis e logs
└── README.md                       # Documentação técnica completa
```

---

## 3. Origem dos Dados — Stored Procedure `CarregaFaturasBoletoWS` (Base `VINDI`)

A extração é realizada chamando a Stored Procedure do SQL Server:
```sql
USE VINDI;
EXEC CarregaFaturasBoletoWS 'YYYY-MM-DD', 'YYYY-MM-DD';
```

A procedure retorna **15 colunas oficiais**:

| # | Coluna Retornada pelo SQL Server | Tipo / Exemplo | Mapeamento no Destino (`model/formatter.py`) |
| :-: | :--- | :--- | :--- |
| **1** | `IdFatura` | `555262732` | `id_fatura_vindi` / `vindi.billId` / `Gateway_Opportunity_ID` |
| **2** | `IdCharge` | `563925391` | `id_cobranca_vindi` / `vindi.chargeId` (ID para Pix / Cartão) |
| **3** | `name` | `Ana Luiza Romitelli` | `donor.fullName` e `donor.firstName` ("Ana") |
| **4** | `last_transaction.gateway_response_fields.barcode` | `<NWnnwnNnWw...>` | `codigo_barras` / `boleto.barcode` |
| **5** | `last_transaction.gateway_response_fields.typeable_barcode` | `23793.17601 90000.133117 33074.295602 1 16320000004100` | `linha_digitavel` / `boleto.digitableLine` e derivação do **Nosso Número** (`rid`) |
| **6** | `CustomerId` | `30733143` | `id_cliente_vindi` / `vindi.customerId` |
| **7** | `due_at` | `2026-11-16 23:59:59` | `data_vencimento` / `boleto.dueDate` (formato `AAAA-MM-DD`) |
| **8** | `amount` | `41.0` | `valor` / `boleto.amount` (float decimal) |
| **9** | `last_transaction.amount` | `41.0` | Conferência de valor da transação |
| **10** | `CreatedDate` | `2026-10-15 10:12:42` | `data_emissao` / `boleto.issueDate` (formato `AAAA-MM-DD`) |
| **11** | `Gateway_Opportunity_ID` | `555262732` | `gateway_opportunity_id` (vínculo de oportunidade) |
| **12** | `Id` | `006U500000gB9XdIAK` | `salesforce_id` (ID da Oportunidade no Salesforce) |
| **13** | `MetodoPagamento__c` | `Boleto` | `plan.paymentMethod` (`online_bank_slip_bradesco_recorrente`) |
| **14** | `Gateway_ID__c` | `Vindi` | `gateway` |
| **15** | `status` | `pending` | `status` (mapeado para `open` na interface do doador) |

### 3.1. Derivação Matemática do Nosso Número (`rid` - 11 dígitos)
Quando o nosso número não vem em coluna separada, o `formatter.py` o extrai diretamente da Linha Digitável do Bradesco (237):
- **Estrutura da Linha Digitável Bradesco:**
  `2379A.AAAAX 9NNNN.NNNNNY NNCCC.CCCCZ K FFFF0000000000`
- **Regra de extração:**
  1. Campo 2 (`90000.133117`): posições úteis 5 a 13 fornecem os **9 primeiros dígitos** (`000013311`).
  2. Campo 3 (`33074.295602`): as primeiras 2 posições fornecem os **2 dígitos finais** (`14` ou `33`).
  3. Resultado: **11 dígitos perfeitos** (exemplo: `00001331114`), exatamente o `rid` registrado no Bradesco e no arquivo CNAB.

---

## 4. Mapeamento Completo das Colunas — FingerPrint (CNAB) ➔ AWS MySQL

A tabela abaixo documenta a correspondência exata entre o modelo de dados extraído no arquivo **FingerPrint (CNAB de Boletos Bradesco)** e a estrutura normalizada gravada no MySQL e no payload da API:

| # | Coluna no FingerPrint (CNAB) | Campo Destino / Contrato da Página | Situação | Regra de Transformação / Derivação Aplicada (`model/formatter.py`) |
| :-: | :--- | :--- | :-: | :--- |
| **1** | `Nosso Número` | `rid` / `nosso_numero` / `boleto.ourNumber` | **DERIVAR** | Extrai os **11 dígitos** do nosso número (ex.: `09/00001385544-8` ➔ `00001385544`), removendo a carteira `09/` e qualquer dígito verificador. É a chave primária da URL (`?rid=`). |
| **2** | `Status` | `status` | **DERIVAR** | Converte os status operacionais: `pending` ➔ `open` (boleto em aberto na tela); `paid` ➔ `paid`; `canceled` / `settled` ➔ `settled`. |
| **3** | `PDF de cobrança` | `id_cobranca_vindi` / `vindi.chargeId` | **DERIVAR** | Extrai via expressão regular o ID numérico da cobrança da URL Vindi (`https://app.vindi.com.br/customer/charges/563983311?b=...` ➔ `563983311`). Obrigatório para reemissão via Pix ou Cartão. |
| **4** | `ID de Fatura Vindi` | `id_fatura_vindi` / `vindi.billId` | **OK** | Identificador único da fatura na Vindi. Utilizado para consultas de contexto e webhooks. |
| **5** | `Id de Assinatura` | `id_assinatura_vindi` / `vindi.subscriptionId` | **OK** | Identificador da assinatura associada ao doador na Vindi. |
| **6** | *(Obtido via fatura/SP)* | `id_cliente_vindi` / `vindi.customerId` | **OPCIONAL** | ID do cliente na Vindi para cadastro de cartão de crédito sem requisição intermediária. |
| **7** | `Primeiro e último nome` | `donor.firstName` | **DERIVAR** | Extrai a **primeira palavra** do nome (ex.: `Karla Prata` ➔ `Karla`) para a saudação personalizada na interface. |
| **8** | `Nome Completo` | `nome_completo` / `donor.fullName` | **OK** | Nome completo do pagador para emissão de recibo, ficha de compensação e titular padrão. |
| **9** | `CPF/CNPJ` | `cpf_cnpj` / `donor.document` | **DERIVAR** | Remove pontuações e caracteres não numéricos, mantendo apenas dígitos (`53897145553`). |
| **10** | *(Derivado do CPF/CNPJ)* | `cpf_cnpj_mascarado` / `donor.maskedDocument` | **DERIVAR** | Aplica máscara de proteção LGPD: `320.***.***-04` para CPF (11 dígitos) ou `12.***.***/0001-34` para CNPJ (14 dígitos). |
| **11** | *(Derivado do CPF/CNPJ)* | `tipo_pessoa` / `donor.personType` | **DERIVAR** | Identifica se o doador é `PF` (11 dígitos) ou `PJ` (14 dígitos). Determina a disponibilidade do Pix Automático. |
| **12** | `E-mail` | `email_mascarado` / `donor.maskedEmail` | **DERIVAR** | Mascara o e-mail preservando os 2 primeiros caracteres e o domínio (ex.: `katla.prata2525@gmail.com` ➔ `ka***@gmail.com`). |
| **13** | `Endereço` | `endereco` / `donor.address.street` | **OK** | Logradouro do doador. |
| **14** | `Número` | `numero` / `donor.address.number` | **OK** | Número do imóvel. |
| **15** | `Complemento` | `complemento` / `donor.address.complement` | **OK** | Complemento do endereço (ex.: `BL.7 AP 92`). |
| **16** | `Bairro` | `bairro` / `donor.address.district` | **OK** | Bairro do endereço. |
| **17** | `CEP` | `cep` / `donor.address.postalCode` | **OK** | Código de Endereçamento Postal. |
| **18** | `Cidade` / `Estado` | `cidade` / `uf` | **DERIVAR** | Normaliza e separa caso venham juntos em formato `Cidade, UF` ou `Cidade/UF`. |
| **19** | `País` | `donor.address.country` | **OK** | Fixo `BR`. |
| **20** | `Número Telefone` | `telefone` / `donor.phone` | **OK** | Telefone de contato do doador. |
| **21** | `Situação` | `situacao_doador` / `donor.situation` | **OK** | Indicador de adimplência cadastral (`Adimplente` / `Inadimplente`). |
| **22** | `Método de Pagamento` | `metodo_pagamento` / `plan.paymentMethod` | **OK** | Método cadastrado (ex.: `online_bank_slip_bradesco_recorrente`). |
| **23** | `Agência/Conta de Cobrança` | `agencia`, `conta`, `digito_conta` | **DERIVAR** | Decompõe `3176/0742956-8` em: **Agência** (`3176` - 4 dígitos), **Conta** (`0742956` - 7 dígitos) e **Dígito** (`8`). |
| **24** | `Carteira` | `carteira` / `boleto.wallet` | **OK** | Código da carteira de cobrança do Bradesco (ex.: `09`). |
| **25** | `Nº do documento` | `numero_documento` / `boleto.documentNumber` | **OK** | Número de controle do documento no banco. |
| **26** | `Valor` | `valor` / `boleto.amount` | **DERIVAR** | Converte valores monetários com múltiplos separadores (ex.: `R$ 35,00` ou `R$ 20,000,00`) para float decimal (`35.00` ou `20000.00`). |
| **27** | `Data de Emissão` | `data_emissao` / `boleto.issueDate` | **DERIVAR** | Converte de `DD/MM/AAAA` para o formato padrão ISO `AAAA-MM-DD`. |
| **28** | `Data de Vencimento` | `data_vencimento` / `boleto.dueDate` | **DERIVAR** | Converte de `DD/MM/AAAA` para o formato padrão ISO `AAAA-MM-DD`. |
| **29** | `Vencimento frente carta` | `data_vencimento_sugerida` | **OPCIONAL** | Data sugerida para vencimento da segunda via (ou `null`). |
| **30** | `Beneficiário` | `beneficiario_nome`, `endereco`, `documento` | **DERIVAR** | Decompõe o texto consolidado em: **Nome** (`Médicos Sem Fronteiras`), **Endereço** (`Av. República do Chile, 230...`) e **CNPJ** (`00.988.096/0001-48`). |
| **31** | `Linha digitável` | `linha_digitavel` / `boleto.digitableLine` | **OK** | Linha digitável de 47 dígitos do boleto para auditoria e conferência. |
| **32** | `Cód. de Barras` | `codigo_barras` / `boleto.barcode` | **OK** | Representação do código de barras bancário. |
| **33** | `Banco` | `codigo_banco` / `boleto.bankCode` | **OK** | Código de compensação bancária (Fixo `237` - Bradesco). |
| **34** | `Local de Pagamento` | `local_pagamento` / `boleto.paymentPlace` | **OK** | Texto padrão: `EM QUALQUER BANCO OU CORRESPONDENTE NÃO BANCÁRIO.` |

---

## 5. Exemplo de Payload JSON Formatado pela Aplicação

O campo `payload_json` gerado para cada registro segue rigorosamente o contrato esperado pela API e pela aplicação web de pagamentos:

```json
{
  "status": "open",
  "donor": {
    "firstName": "Karla",
    "fullName": "KARLA CRISTINA PRATA",
    "document": "53897145553",
    "maskedDocument": "538.***.***-53",
    "maskedEmail": "ka***@gmail.com",
    "personType": "PF",
    "phone": "5516997297100",
    "situation": "Adimplente",
    "address": {
      "street": "RUA DO RETIRO",
      "number": "2172",
      "complement": "BL.7 AP 92",
      "district": "VILA DAS HORTÊNCIAS",
      "city": "JUNDIAÍ",
      "state": "SP",
      "postalCode": "13209-355"
    }
  },
  "plan": {
    "paymentMethod": "online_bank_slip_bradesco_recorrente",
    "amount": 35.0
  },
  "vindi": {
    "chargeId": "563983311",
    "billId": "555320870",
    "subscriptionId": "78286809",
    "customerId": ""
  },
  "boleto": {
    "bankCode": "237",
    "agency": "3176",
    "account": "0742956",
    "accountDigit": "8",
    "wallet": "09",
    "ourNumber": "00001385544",
    "documentNumber": "1385544",
    "amount": 35.0,
    "issueDate": "2026-10-15",
    "dueDate": "2026-11-16",
    "suggestedDueDate": null,
    "paymentPlace": "EM QUALQUER BANCO OU CORRESPONDENTE NÃO BANCÁRIO.",
    "digitableLine": "23793.17601 90000.138553 44074.295609 3 16320000003500",
    "barcode": "<NWnnwnNnWwWwnnNNWwnnnwNNwnnWWnnnWWnNNwwnwnWNnNNwwnwnnNWnwWNnnwNWnnnWWnNnwwNWwnNnWnWnnnnWnWnnwWNnNwnWNwNwnnwWNn>",
    "beneficiary": {
      "name": "Médicos Sem Fronteiras",
      "address": "Av. República do Chile, 230, sala 2801, 20031-170",
      "document": "00.988.096/0001-48"
    }
  }
}
```

---

## 6. Arquivo de Configuração (`config.ini`)

O arquivo [config.ini](file:///c:/Users/davis.vasconcellos/OneDrive%20-%20MSF/Documentos/MSF/PHYTON/update_boletos_aws/config.ini) centraliza todos os parâmetros da rotina:

```ini
[banco]
# IP ou hostname do servidor SQL Server de origem
servidor_ip = 192.168.1.20
database = VINDI
procedure_name = CarregaFaturasBoletoWS
connect_timeout_seconds = 10

[FILTRO]
# Parâmetros de data para a Stored Procedure 'CarregaFaturasBoletoWS'
# Deixe em branco para cálculo automático (mês corrente até faturas futuras)
data_inicio = 
data_fim = 

[AMBIENTE]
# Opções: mockup, sandbox, prod
# Mantenha como 'mockup' para testes locais seguros
ambiente = mockup

[SSH]
# Configurações do túnel SSH para conexão ao MySQL na AWS
use_ssh_tunnel = true
ssh_host = ec2-xx-xx-xx-xx.compute-1.amazonaws.com
ssh_port = 22
ssh_user = ec2-user
ssh_key_path = ssh/id_ed25519
ssh_key_passphrase = 

[MYSQL_AWS]
# Banco de dados MySQL destino na AWS
mysql_host = meu-banco.xxxxxx.us-east-1.rds.amazonaws.com
mysql_port = 3306
mysql_user = usuario_sync
mysql_password = 
mysql_database = msf_cobranca
mysql_target_table = boletos

[PROCESSAMENTO]
test_mode = false
max_records = 50
db_query_timeout_seconds = 180
db_fetch_chunk_size = 1000
last_sync_timestamp = 
# Gera backup físico em CSV dos dados formatados enviados nesta execução
gerar_csv_backup = true
diretorio_csv_backup = backups_csv/

[LOG]
diretorio = logs/
dashboard_html = log_dashboard/dashboard.html
```

---

## 7. Como Executar

### 7.1. Execução via Scripts Batch (.bat)
- **Diagnóstico da Stored Procedure:** execute [testar_procedure.bat](file:///c:/Users/davis.vasconcellos/OneDrive%20-%20MSF/Documentos/MSF/PHYTON/update_boletos_aws/testar_procedure.bat) para validar a conexão e checar se a procedure existe na base `VINDI`.
- **Modo Teste (1 Lote Limitado):** execute [rodar_teste.bat](file:///c:/Users/davis.vasconcellos/OneDrive%20-%20MSF/Documentos/MSF/PHYTON/update_boletos_aws/rodar_teste.bat).
- **Modo Normal (Produção):** execute [rodar_update.bat](file:///c:/Users/davis.vasconcellos/OneDrive%20-%20MSF/Documentos/MSF/PHYTON/update_boletos_aws/rodar_update.bat).

### 7.2. Execução via Linha de Comando (CLI)
```bash
# Diagnóstico completo de acesso e verificação de schema da procedure
main.exe check
python main.py check

# Executa em modo normal (lendo config.ini)
main.exe
python main.py

# Força modo de teste (processa apenas 1 lote de até 50 registros, sem avançar corte)
main.exe testmode
python main.py testmode

# Força modo de teste com limite customizado (ex.: 10 registros)
main.exe testmode 10
python main.py testmode 10

# Força modo normal
main.exe normal
python main.py normal
```

---

## 8. Como Compilar para Executável (.exe)

O script [Compilador.bat](file:///c:/Users/davis.vasconcellos/OneDrive%20-%20MSF/Documentos/MSF/PHYTON/update_boletos_aws/Compilador.bat) automatiza todo o processo de build:
1. Instala as dependências necessárias (`pyinstaller`, `pyodbc`, `pymysql`, `sshtunnel`, `paramiko`, `cryptography`);
2. Cria backup automático do executável anterior (`main_YYYYMMDD_HHMM.exe`);
3. Compila a aplicação em um único arquivo binário independente (`main.exe`) na raiz do projeto.

---

## 9. Backup Físico em CSV (`backups_csv/`)

A aplicação conta com um recurso nativo de contingência contábil e auditoria:
- Toda execução com a flag `gerar_csv_backup = true` no `config.ini` grava um arquivo CSV contendo todos os registros formatados com as colunas finais preparadas para a AWS.
- Nome do arquivo gerado: `backups_csv/boletos_upload_YYYY-MM-DD_HH-MM-SS.csv`.
- Permite importar manualmente ou auditar valores, vencimentos, códigos de barras e CPFs a qualquer momento diretamente no Microsoft Excel.

---

## 10. Dashboard HTML Interativo

Ao término de cada execução (mesmo em caso de falhas ou cancelamento), a aplicação gera ou atualiza o painel visual em:
`log_dashboard/dashboard.html`

O dashboard fornece:
- **Cards de Métricas:** Total de registros lidos, registros inseridos/atualizados com sucesso e inconsistências.
- **Accordion Histórico:** Lista cronológica de todas as execuções registradas em `logs/`.
- **Aba "Lista de Falhas":** Destaque seletivo de registros que apresentaram inconsistência cadastral para ação rápida.
- **Aba "Log Bruto de Execução":** Terminal completo da execução com saída detalhada das amostras JSON.

---

## 11. Guia de Resolução de Problemas (Troubleshooting)

| Sintoma / Erro | Causa Provável | Solução |
| :--- | :--- | :--- |
| `Could not find stored procedure 'CarregaFaturasBoletoWS'. (2812)` | O parâmetro `database` no `config.ini` está apontando para outro banco (ex.: `SALESFORCE`). | Altere `database = VINDI` no `config.ini`. A procedure reside oficialmente no banco `VINDI`. |
| `SQL Server inexistente ou acesso negado. (17)` | A máquina que está executando não tem rota de rede interna para `192.168.1.20`. | Execute a aplicação a partir de um servidor da rede interna (ex.: `D:\Programas\update_boletos_aws`) ou conecte a VPN de MSF. |
| `Authentication failed` no túnel SSH | A chave privada `id_ed25519` possui senha configurada. | Preencha o parâmetro `ssh_key_passphrase` na seção `[SSH]` do `config.ini`. |
| `Diretório temporário não encontrado no .exe` | Executável PyInstaller rodando sem resolver diretório base relativo. | A aplicação utiliza o helper `util.paths.get_base_dir()` que detecta se está rodando via script ou frozen `.exe`. |
