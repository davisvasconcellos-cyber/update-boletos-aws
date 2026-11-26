# -*- coding: utf-8 -*-
"""
Módulo de Formatação e Transformação de Campos (model/formatter.py)
Aplica todas as regras especificadas em 'boleto-32-campos-planilha-vindi-v2.pdf'
e no blueprint arquitetural, convertendo o registro bruto vindo do SQL Server (SP CarregaFaturasBoletoWS)
no formato exigido pelo contrato da página e pela tabela MySQL na AWS.
"""

import re
import datetime
import json

def extrair_digitos(valor):
    """Remove qualquer caractere não numérico."""
    if valor is None:
        return ""
    return re.sub(r'\D', '', str(valor).strip())

def extrair_nosso_numero_11_digitos(nosso_numero_raw):
    """
    Regra DERIVAR:
    Nosso Número vem como '09/00001385544' ou '09/00001385544-X' ou '00001385544'.
    Deve extrair exatamente os 11 dígitos do nosso número (sem a carteira 09 e sem DV).
    """
    if not nosso_numero_raw:
        return ""
    
    val_str = str(nosso_numero_raw).strip()
    
    # Se contém barra (ex: '09/00001385544' ou '09/00001385544-8')
    if '/' in val_str:
        partes = val_str.split('/', 1)
        depois_barra = partes[1].split('-')[0].strip()
        digitos = re.sub(r'\D', '', depois_barra)
        if len(digitos) >= 11:
            return digitos[:11]
        return digitos.zfill(11)
        
    # Se contém traço (ex: '00001385544-8')
    if '-' in val_str:
        antes_traco = val_str.split('-')[0].strip()
        digitos = re.sub(r'\D', '', antes_traco)
        if len(digitos) >= 11:
            return digitos[-11:]
        return digitos.zfill(11)
        
    digitos = re.sub(r'\D', '', val_str)
    # Se tiver 13 dígitos e começar com 09 (carteira embutida)
    if len(digitos) == 13 and digitos.startswith('09'):
        return digitos[2:]
    elif len(digitos) > 11:
        return digitos[-11:]
    elif digitos:
        return digitos.zfill(11)
        
    return ""

def extrair_nosso_numero_de_linha_digitavel(linha_digitavel):
    """
    Regra DERIVAR:
    Em boletos Bradesco (Banco 237):
    Linha digitável (47 dígitos com DVs):
      Campo 1: 2379A.AAACC d1
      Campo 2: C NNNN.NNNNN d2  (posições 11-20: 1 dígito carteira + 9 primeiros dígitos do Nosso Número)
      Campo 3: NN CCC.CCCC0 d3  (posições 21-23: 2 últimos dígitos do Nosso Número)
    Exemplo real do DBA:
      '23793.17601 90000.138785 05074.295600 5 166100000...'
      Campo 2: '90000.138785' -> parte útil = '000013878' (9 dígitos)
      Campo 3: '05074.295600' -> parte útil = '05' (2 dígitos)
      Resultado: '000013878' + '05' = '00001387805' (11 dígitos)
    """
    if not linha_digitavel:
        return ""
    limpo = re.sub(r'[\.\s]', '', str(linha_digitavel).strip())
    if len(limpo) >= 32:
        # Posições 11 a 20 (9 dígitos do nosso número)
        p1 = limpo[11:20]
        # Posições 21 a 23 (2 dígitos finais do nosso número)
        p2 = limpo[21:23]
        nosso_num = p1 + p2
        if len(nosso_num) == 11 and nosso_num.isdigit():
            return nosso_num
    return ""

def linha_digitavel_para_codigo_barras_44(linha_digitavel):
    """
    Converte a linha digitável (47 dígitos) no código de barras oficial FEBRABAN (44 dígitos).
    Regra FEBRABAN:
      Linha: 
        c1 = posições 0..9 (9 úteis + DV pos 9)
        c2 = posições 10..20 (10 úteis + DV pos 20)
        c3 = posições 21..31 (10 úteis + DV pos 31)
        c4 = posição 32 (DV geral)
        c5 = posições 33..47 (14 dígitos: fator + valor)
      Código de barras (44 posições):
        banco_moeda (4) + DV geral (1) + fator_valor (14) + campo_livre (25)
    """
    if not linha_digitavel:
        return ""
    digitos = re.sub(r'\D', '', str(linha_digitavel).strip())
    if len(digitos) != 47:
        return ""
    
    c1 = digitos[0:9]    # 9 dígitos (sem o DV pos 9)
    c2 = digitos[10:20]  # 10 dígitos (sem o DV pos 20)
    c3 = digitos[21:31]  # 10 dígitos (sem o DV pos 31)
    c4 = digitos[32:33]  # 1 dígito (DV geral)
    c5 = digitos[33:47]  # 14 dígitos (fator + valor)
    
    banco_moeda = c1[0:4]
    campo_livre_1 = c1[4:9]
    campo_livre_2 = c2
    campo_livre_3 = c3
    
    return banco_moeda + c4 + c5 + campo_livre_1 + campo_livre_2 + campo_livre_3

def extrair_telefone_estruturado(val):
    """
    Extrai número do telefone e tipo ('mobile' ou 'landline').
    Suporta formato JSON retornado por VINDI:
    '[{"id":...,"phone_type":"mobile","number":"5521981285458","extension":null}]'
    ou string simples.
    """
    if not val:
        return "", "mobile", ""
    s = str(val).strip()
    if s.startswith('[') or s.startswith('{'):
        try:
            data = json.loads(s)
            if isinstance(data, list) and len(data) > 0:
                item = data[0]
                num = extrair_digitos(item.get('number', ''))
                tipo = item.get('phone_type', 'mobile')
                ext = str(item.get('extension') or '')
                return num, ('landline' if tipo == 'landline' else 'mobile'), ext
            elif isinstance(data, dict):
                num = extrair_digitos(data.get('number', ''))
                tipo = data.get('phone_type', 'mobile')
                ext = str(data.get('extension') or '')
                return num, ('landline' if tipo == 'landline' else 'mobile'), ext
        except Exception:
            pass
            
    m = re.search(r'"number"\s*:\s*"(\d+)"', s)
    if m:
        t_m = re.search(r'"phone_type"\s*:\s*"(\w+)"', s)
        tipo = t_m.group(1) if t_m else 'mobile'
        return m.group(1), ('landline' if tipo == 'landline' else 'mobile'), ""
        
    num = extrair_digitos(s)
    return num, 'mobile', ""

def formatar_cep_com_traco(cep_raw):
    """Garante formato 00000-000 (9 caracteres) exigido pela tabela."""
    digitos = extrair_digitos(cep_raw)
    if not digitos:
        return "00000-000"
    digitos = digitos.zfill(8)[-8:]
    return f"{digitos[:5]}-{digitos[5:]}"

def normalizar_status(status_raw):
    """
    Regra DERIVAR:
    pending ➔ open
    paid ➔ paid
    canceled / cancelled ➔ settled
    rejected ➔ rejected
    """
    if not status_raw:
        return "open"
    s = str(status_raw).strip().lower()
    if s in ["pending", "open", "aberto", "em aberto"]:
        return "open"
    elif s in ["paid", "pago", "liquidado"]:
        return "paid"
    elif s in ["canceled", "cancelled", "settled", "baixado", "cancelado"]:
        return "settled"
    elif s in ["rejected", "recusado"]:
        return "rejected"
    return "open"

def extrair_charge_id(url_ou_id):
    """
    Regra DERIVAR:
    Extrai o ID numérico da cobrança da URL do PDF da Vindi:
    'https://app.vindi.com.br/customer/charges/563983311?b=...' ➔ '563983311'
    Ou se já for id numérico puro, retorna ele.
    """
    if not url_ou_id:
        return ""
    val_str = str(url_ou_id).strip()
    match = re.search(r'/charges/(\d+)', val_str)
    if match:
        return match.group(1)
    # Se for apenas dígitos
    digitos = re.sub(r'\D', '', val_str)
    if digitos:
        return digitos
    return ""

def mascarar_documento(doc_limpo):
    """
    Regra DERIVAR:
    CPF (11 dígitos): 320.***.***-04
    CNPJ (14 dígitos): 12.***.***/0001-34
    """
    if not doc_limpo:
        return ""
    if len(doc_limpo) == 11:
        return f"{doc_limpo[:3]}.***.***-{doc_limpo[-2:]}"
    elif len(doc_limpo) == 14:
        return f"{doc_limpo[:2]}.***.***/{doc_limpo[8:12]}-{doc_limpo[-2:]}"
    return doc_limpo

def mascarar_email(email_raw):
    """
    Regra DERIVAR:
    be***@example.com (primeiras 2 letras + ***@ + domínio)
    """
    if not email_raw:
        return ""
    e = str(email_raw).strip()
    if '@' not in e:
        return ""
    partes = e.split('@', 1)
    usuario = partes[0]
    dominio = partes[1]
    if len(usuario) <= 2:
        user_mascarado = usuario + "***"
    else:
        user_mascarado = usuario[:2] + "***"
    return f"{user_mascarado}@{dominio}"

def parse_valor_monetario(valor_raw):
    """
    Regra DERIVAR:
    Valor R$ 35,00 ➔ 35.00
    Cuidado com R$ 20,000,00 ou 20.000,00 (a última vírgula/ponto é a decimal).
    """
    if valor_raw is None:
        return 0.0
    if isinstance(valor_raw, (int, float)):
        return round(float(valor_raw), 2)
        
    s = str(valor_raw).replace('R$', '').replace('r$', '').strip()
    if not s:
        return 0.0
        
    # Se contiver tanto ponto quanto vírgula
    if '.' in s and ',' in s:
        last_dot = s.rfind('.')
        last_comma = s.rfind(',')
        if last_comma > last_dot:
            # Ponto é milhar, vírgula é decimal (ex: 20.000,00 ou 20,000,00)
            s_clean = s.replace('.', '').replace(',', '.')
        else:
            # Vírgula é milhar, ponto é decimal
            s_clean = s.replace(',', '')
    elif ',' in s:
        # Se contiver apenas vírgula
        partes = s.split(',')
        if len(partes) == 2:
            s_clean = partes[0].replace('.', '') + '.' + partes[1]
        else:
            # Múltiplas vírgulas: última é decimal (ex: 20,000,00)
            dec = partes[-1]
            inteiro = "".join(partes[:-1])
            s_clean = f"{inteiro}.{dec}"
    else:
        s_clean = s
        
    try:
        return round(float(s_clean), 2)
    except (ValueError, TypeError):
        return 0.0

def parse_data_iso(data_raw):
    """
    Regra DERIVAR:
    Converte datetime, date ou string 'dd/mm/aaaa' para 'aaaa-mm-dd'.
    """
    if not data_raw:
        return None
    if isinstance(data_raw, (datetime.datetime, datetime.date)):
        return data_raw.strftime('%Y-%m-%d')
    s = str(data_raw).strip()
    if not s:
        return None
        
    # Formato AAAA-MM-DD
    if re.match(r'^\d{4}-\d{2}-\d{2}', s):
        return s[:10]
        
    # Formato DD/MM/AAAA
    match_br = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})', s)
    if match_br:
        dia, mes, ano = match_br.groups()
        return f"{ano}-{mes.zfill(2)}-{dia.zfill(2)}"
        
    return s[:10]

def separar_agencia_conta(agencia_conta_raw):
    """
    Regra DERIVAR:
    Agência/Conta de Cobrança 3176/0742956-8 ➔
    agência: 3176 (4 posições)
    conta: 0742956 (7 posições)
    dígito: 8
    """
    agencia = ""
    conta = ""
    digito = ""
    
    if not agencia_conta_raw:
        return "3176", "0742956", "8"
        
    s = str(agencia_conta_raw).strip()
    # Padrão: AGENCIA / CONTA - DIGITO
    # Ex: 3176/0742956-8 ou 3176 / 0742956-8
    match = re.search(r'(\d+)\s*/\s*(\d+)(?:-(\w+))?', s)
    if match:
        agencia = match.group(1).zfill(4)[-4:]
        conta = match.group(2).zfill(7)[-7:]
        digito = match.group(3) if match.group(3) else ""
    else:
        digitos = re.sub(r'\D', '', s)
        if len(digitos) >= 12:
            agencia = digitos[:4]
            conta = digitos[4:11]
            digito = digitos[11:12]
        elif len(digitos) >= 11:
            agencia = digitos[:4]
            conta = digitos[4:11]
            digito = ""
            
    return agencia, conta, digito

def separar_beneficiario(beneficiario_raw):
    """
    Regra DERIVAR:
    Beneficiário vem como texto único:
    'Médicos Sem Fronteiras, Av. República do Chile, 230, sala 2801, 20031-170. CNPJ 00.988.096/0001-48'
    Separa em nome, endereço e CNPJ.
    """
    default_name = "Médicos Sem Fronteiras"
    default_address = "Av. República do Chile, 230, sala 2801, 20031-170"
    default_doc = "00.988.096/0001-48"
    
    if not beneficiario_raw:
        return default_name, default_address, default_doc
        
    s = str(beneficiario_raw).strip()
    
    # Extrai CNPJ
    cnpj_match = re.search(r'CNPJ\s*([\d\.\/\-]+)', s, re.IGNORECASE)
    cnpj = cnpj_match.group(1).strip() if cnpj_match else default_doc
    
    # Remove CNPJ da string para separar nome e endereço
    s_sem_cnpj = re.sub(r'[\.,\-]?\s*CNPJ\s*[\d\.\/\-]+', '', s, flags=re.IGNORECASE).strip()
    
    # Se contém vírgula, primeira parte é o nome e o resto é o endereço
    if ',' in s_sem_cnpj:
        partes = s_sem_cnpj.split(',', 1)
        nome = partes[0].strip()
        endereco = partes[1].strip()
    else:
        nome = s_sem_cnpj
        endereco = default_address
        
    if not nome:
        nome = default_name
    if not endereco:
        endereco = default_address
        
    return nome, endereco, cnpj

def formatar_registro(row_dict):
    """
    Converte um registro bruto (dict) retornado pelo SQL Server no modelo formatado.
    Retorna: (is_valido: bool, motivo_erro: str, registro_formatado: dict)
    """
    if not row_dict or not isinstance(row_dict, dict):
        return False, "Registro vazio ou formato invalido", {}

    # Busca valores por possíveis nomes de colunas retornadas pela SP/tabela
    def get_val(*chaves, default=""):
        for k in chaves:
            if k in row_dict and row_dict[k] is not None:
                val = str(row_dict[k]).strip()
                if val:
                    return val
            # Tenta case-insensitive
            for rk in row_dict:
                if rk.lower() == k.lower() and row_dict[rk] is not None:
                    val = str(row_dict[rk]).strip()
                    if val:
                        return val
        return default

    # Campos da resposta da SP/gateway
    linha_digitavel = get_val("last_transaction.gateway_response_fields.typeable_barcode", "Linha digitável", "Linha digitavel", "linha_digitavel", "digitableLine")
    codigo_barras = get_val("last_transaction.gateway_response_fields.barcode", "Cód. de Barras", "Cod. de Barras", "codigo_barras", "barcode")
    situacao_doador = get_val("Situação", "Situacao", "situacao_doador")

    # 1. Chave de Consulta (rid / nosso_numero)
    linha_limpa_47 = extrair_digitos(linha_digitavel)
    if len(linha_limpa_47) == 47:
        codigo_barras_44 = linha_digitavel_para_codigo_barras_44(linha_limpa_47)
    else:
        codigo_barras_44 = extrair_digitos(codigo_barras)

    nosso_numero_raw = get_val("Nosso Número", "NossoNumero", "ourNumber", "nosso_numero")
    rid = extrair_nosso_numero_11_digitos(nosso_numero_raw)
    
    if not rid and linha_digitavel:
        # Se não veio a coluna Nosso Número explícita, deriva diretamente da linha digitável Bradesco
        rid = extrair_nosso_numero_de_linha_digitavel(linha_digitavel)

    if not rid:
        # Fallback para número do documento
        num_doc_fallback = extrair_digitos(get_val("Nº do documento", "NumeroDocumento", "documentNumber", "document_number"))
        if len(num_doc_fallback) >= 11:
            rid = num_doc_fallback[-11:]
        elif num_doc_fallback:
            rid = num_doc_fallback.zfill(11)
            
    if not rid or len(rid) != 11:
        return False, f"Nosso Numero invalido ou ausente para identificar o boleto: '{nosso_numero_raw}' (rid: '{rid}')", {}

    # Validação do código de barras e linha digitável
    if len(linha_limpa_47) != 47:
        return False, f"Linha digitavel deve ter 47 digitos numericos: '{linha_digitavel}'", {}
    if len(codigo_barras_44) != 44:
        return False, f"Codigo de barras deve ter 44 digitos numericos: '{codigo_barras_44}'", {}

    # 2. Situação / Status
    status_raw = get_val("Status", "status", "situacao", default="pending")
    status = normalizar_status(status_raw)

    # 3. Identificadores Vindi / Salesforce
    url_pdf = get_val("PDF de cobrança", "PDF de cobranca", "url_pdf", "pdf_url")
    charge_id = get_val("IdCharge", "id_charge", "vindi_charge_id", "chargeId", "id_cobranca")
    if not charge_id and url_pdf:
        charge_id = extrair_charge_id(url_pdf)

    bill_id = get_val("IdFatura", "id_fatura", "ID de Fatura Vindi", "ID Fatura Vindi", "billId")
    if not bill_id:
        return False, "ID de Fatura Vindi (bill_id) ausente", {}

    subscription_id = get_val("Id de Assinatura", "subscriptionId", "id_assinatura_vindi", "id_assinatura")
    customer_id = get_val("CustomerId", "customer_id", "Id do Cliente Vindi", "customerId")
    code_oportunidade = get_val("Id", "Gateway_Opportunity_ID", "code_oportunidade", "opportunity_id")

    if not url_pdf and charge_id:
        url_pdf = f"https://app.vindi.com.br/customer/charges/{charge_id}"

    # 4. Dados do Doador
    nome_completo = get_val("name", "Nome Completo", "Nome", "fullName", "donor_name")
    if not nome_completo:
        nome_completo = "Doador MSF"

    # Nome curto (primeiro e último nome)
    partes_nome = nome_completo.split()
    if len(partes_nome) >= 2:
        nome_curto = f"{partes_nome[0]} {partes_nome[-1]}"[:60]
    else:
        nome_curto = nome_completo[:60]

    first_name = partes_nome[0] if partes_nome else "Doador"

    doc_raw = get_val("CPF/CNPJ", "CPF", "CNPJ", "document", "msf_document_number", "registry_code")
    doc_limpo = extrair_digitos(doc_raw)
    if len(doc_limpo) not in (11, 14):
        return False, f"CPF/CNPJ invalido ({len(doc_limpo)} digitos): '{doc_raw}'", {}

    masked_doc = mascarar_documento(doc_limpo)
    person_type = "PJ" if len(doc_limpo) == 14 else "PF"

    email_raw = get_val("Email", "E-mail", "email")
    masked_email = mascarar_email(email_raw)

    tel_raw = get_val("Telefone", "Número Telefone", "Numero Telefone", "telefone", "phone", "phones")
    tel_num, tel_tipo, tel_ramal = extrair_telefone_estruturado(tel_raw)
    telefone = tel_num

    endereco_rua = get_val("Endereço", "Endereco", "street", "address1", "address.street", default="Nao informado")[:80]
    endereco_num = get_val("Número", "Numero", "number", "address.number", default="S/N")[:10]
    endereco_comp = get_val("Complemento", "complement", "address.additional_details", default="")[:40]
    endereco_bairro = get_val("Bairro", "district", "address.neighborhood", default="Centro")[:60]
    endereco_cep_raw = get_val("CEP", "postalCode", "address.zipcode", default="00000000")
    endereco_cep = formatar_cep_com_traco(endereco_cep_raw)
    endereco_cidade = get_val("Cidade", "city", "address.city", default="Rio de Janeiro")[:60]
    endereco_estado = get_val("Estado", "state", "UF", "address.state", default="RJ")[:2].upper()

    # Se a cidade vier combinada (ex: 'Rio de Janeiro, RJ' ou 'Rio de Janeiro/RJ')
    if (not endereco_estado or len(endereco_estado) != 2) and (',' in endereco_cidade or '/' in endereco_cidade):
        sep = ',' if ',' in endereco_cidade else '/'
        c_partes = endereco_cidade.split(sep, 1)
        endereco_cidade = c_partes[0].strip()[:60]
        endereco_estado = c_partes[1].strip()[:2].upper()

    if not endereco_estado:
        endereco_estado = "RJ"

    # 5. Valores e Datas
    valor_raw = get_val("amount", "Valor", "last_transaction.amount", "valor_boleto")
    valor_float = parse_valor_monetario(valor_raw)
    if valor_float <= 0:
        return False, f"Valor invalido para boleto: {valor_float}", {}

    due_date = parse_data_iso(get_val("due_at", "Data de Vencimento", "DataVencimento", "dueDate"))
    if not due_date:
        return False, "Data de vencimento ausente", {}

    issue_date = parse_data_iso(get_val("CreatedDate", "Data de Emissão", "DataEmissao", "issueDate"))
    if not issue_date:
        issue_date = datetime.date.today().strftime('%Y-%m-%d')

    # Garantir regra ck_vencimento (data_vencimento >= data_emissao)
    if issue_date > due_date:
        issue_date = due_date

    suggested_due_date = parse_data_iso(get_val("Vencimento sugerido", "data_vencimento_sugerida", "suggestedDueDate"))
    if suggested_due_date:
        if suggested_due_date < issue_date or suggested_due_date > due_date:
            suggested_due_date = due_date

    # 6. Parâmetros Bancários
    payment_method = get_val("Método de Pagamento", "MetodoPagamento", "paymentMethod", default="online_bank_slip_bradesco_recorrente")[:50]
    agencia_conta_raw = get_val("Agência/Conta de Cobrança", "AgenciaConta", "agencia_conta")
    agencia, conta, digito_conta = separar_agencia_conta(agencia_conta_raw)

    carteira = get_val("Carteira", "wallet", default="09").zfill(2)[:2]
    doc_number = get_val("Nº do documento", "NumeroDocumento", "documentNumber", "document_number")
    if not doc_number:
        doc_number = str(int(rid)) if rid.isdigit() else rid
    doc_number = str(doc_number)[:20]

    beneficiario_raw = get_val("Beneficiário", "Beneficiario", "beneficiary")
    ben_name, ben_address, ben_doc = separar_beneficiario(beneficiario_raw)
    ben_full_text = f"{ben_name}, {ben_address}. CNPJ {ben_doc}"[:150]

    local_pagamento = get_val("Local de Pagamento", "LocalPagamento", "paymentPlace", default="EM QUALQUER BANCO OU CORRESPONDENTE NÃO BANCÁRIO.")[:120]
    codigo_banco = "237"
    banco_nome = "Bradesco"

    # Lote padrão
    lote = get_val("lote", default=f"SP_CarregaFaturasBoletoWS_{datetime.date.today().strftime('%Y%m%d')}")[:80]

    # Monta a estrutura JSON conforme contrato da página (especificado no PDF)
    payload_json = {
        "status": status,
        "donor": {
            "firstName": first_name,
            "fullName": nome_completo,
            "document": doc_limpo,
            "maskedDocument": masked_doc,
            "maskedEmail": masked_email,
            "personType": person_type,
            "phone": telefone,
            "situation": situacao_doador,
            "address": {
                "street": endereco_rua,
                "number": endereco_num,
                "complement": endereco_comp,
                "district": endereco_bairro,
                "city": endereco_cidade,
                "state": endereco_estado,
                "postalCode": endereco_cep
            }
        },
        "plan": {
            "paymentMethod": payment_method,
            "amount": valor_float
        },
        "vindi": {
            "chargeId": charge_id,
            "billId": bill_id,
            "subscriptionId": subscription_id,
            "customerId": customer_id
        },
        "boleto": {
            "bankCode": codigo_banco,
            "agency": agencia,
            "account": conta,
            "accountDigit": digito_conta,
            "wallet": carteira,
            "ourNumber": rid,
            "documentNumber": doc_number,
            "amount": valor_float,
            "issueDate": issue_date,
            "dueDate": due_date,
            "suggestedDueDate": suggested_due_date,
            "paymentPlace": local_pagamento,
            "digitableLine": linha_digitavel,
            "barcode": codigo_barras,
            "beneficiary": {
                "name": ben_name,
                "address": ben_address,
                "document": ben_doc
            }
        }
    }

    # Registro final (compatível com a tabela oficial 'boletos_segunda_via' e tabela genérica 'boletos')
    id_fat_int = int(bill_id) if str(bill_id).isdigit() else None
    id_cob_int = int(charge_id) if str(charge_id).isdigit() else None
    id_ass_int = int(subscription_id) if str(subscription_id).isdigit() else None

    registro_formatado = {
        # Campos oficiais da tabela boletos_segunda_via
        "lote": lote,
        "numero_documento": doc_number,
        "nosso_numero": rid,
        "carteira": carteira,
        "id_fatura_vindi": id_fat_int,
        "id_cobranca_vindi": id_cob_int,
        "id_assinatura_vindi": id_ass_int,
        "code_oportunidade": code_oportunidade or None,
        "metodo_pagamento": payment_method,
        "status_vindi": status_raw,
        "status": status,
        "situacao_doador": situacao_doador if situacao_doador in ('Adimplente', 'Inadimplente') else None,
        "pago_em": None,
        "nome_curto": nome_curto,
        "nome_completo": nome_completo,
        "email": email_raw or None,
        "cpf_cnpj": doc_limpo,
        "receber_carta": get_val("Receber Carta", "receber_carta", default=None),
        "logradouro": endereco_rua,
        "numero_endereco": endereco_num,
        "complemento": endereco_comp or None,
        "cep": endereco_cep,
        "bairro": endereco_bairro,
        "cidade": endereco_cidade,
        "uf": endereco_estado,
        "pais": "BR",
        "telefone_tipo": tel_tipo,
        "telefone_numero": tel_num or None,
        "telefone_ramal": tel_ramal or None,
        "banco_codigo": codigo_banco,
        "banco_nome": banco_nome,
        "agencia": agencia,
        "conta": conta,
        "conta_digito": digito_conta,
        "beneficiario": ben_full_text,
        "local_pagamento": local_pagamento,
        "especie_doc": "Outros",
        "aceite": "N",
        "data_emissao": issue_date,
        "data_vencimento": due_date,
        "data_vencimento_sugerida": suggested_due_date,
        "vencimento_frente_carta": get_val("vencimento_frente_carta", default=None),
        "valor": valor_float,
        "linha_digitavel": linha_limpa_47,
        "codigo_barras": codigo_barras_44,
        "pdf_url": url_pdf or None,

        # Campos adicionais / compatibilidade com schema legado 'boletos'
        "rid": rid,
        "id_cliente_vindi": customer_id,
        "cpf_cnpj_mascarado": masked_doc,
        "tipo_pessoa": person_type,
        "primeiro_nome": first_name,
        "email_mascarado": masked_email,
        "telefone": tel_num,
        "endereco": endereco_rua,
        "numero": endereco_num,
        "digito_conta": digito_conta,
        "beneficiario_nome": ben_name,
        "beneficiario_endereco": ben_address,
        "beneficiario_documento": ben_doc,
        "payload_json": json.dumps(payload_json, ensure_ascii=False)
    }

    return True, "", registro_formatado
