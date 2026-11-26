# -*- coding: utf-8 -*-
"""
Gerador de Dashboard HTML Interativo (log_dashboard/dashboard_generator.py)
Analisa todos os arquivos de logs de execuções gerados em logs/*.log
e constrói um painel responsivo em Bootstrap 5 com métricas de lotes,
painel Accordion, abas de auditoria de falhas e log bruto.
"""

import os
import glob
import datetime
import re
from util.paths import get_base_dir

class DashboardGenerator:
    def __init__(self):
        self.base_dir = get_base_dir()
        self.logs_dir = os.path.join(self.base_dir, 'logs')
        self.dashboard_path = os.path.join(self.base_dir, 'log_dashboard', 'dashboard.html')
        
    def generate(self):
        """Lê os logs e gera o Dashboard HTML interativo."""
        os.makedirs(os.path.dirname(self.dashboard_path), exist_ok=True)
        
        log_files = glob.glob(os.path.join(self.logs_dir, '*.log'))
        log_files.sort(reverse=True)  # Mais recentes primeiro
        
        cards_html = ""
        
        for idx, log_file in enumerate(log_files):
            filename = os.path.basename(log_file)
            date_str = filename.replace('exec_', '').replace('.log', '')
            
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                content = "".join(lines)
                
                # Métricas agregadas
                total_processados = 0
                total_atualizados = 0
                total_criados = 0
                total_falhas = 0
                
                is_test_mode = "MODO DE TESTE" in content
                is_mockup = "MOCKUP" in content
                
                # Regex para extrair métricas de resumo dos lotes
                resumo_matches = re.findall(
                    r'Total=(\d+)\s*\|\s*(?:Atualizados|Sucesso)=(\d+)\s*\|\s*(?:Criados=(\d+)\s*\|)?\s*Falhas=(\d+)',
                    content
                )
                for match in resumo_matches:
                    tot, upd, cre, fail = match
                    total_processados += int(tot)
                    total_atualizados += int(upd)
                    total_criados += int(cre) if cre else 0
                    total_falhas += int(fail)
                
                # Extrai lista de falhas individuais ou inconsistências
                falhas_list = []
                for line in lines:
                    line_clean = line.strip()
                    if "✗ [FALHA/INVALIDO]" in line_clean or "ERRO CRITICO" in line_clean:
                        falhas_list.append(line_clean)

                # Extração do tempo total da operação (duração)
                duracao_str = "0s"
                m_dur = re.search(r'Duracao Total:\s*([^\)]+)\)', content)
                if m_dur:
                    duracao_str = m_dur.group(1).strip()
                else:
                    primeiro_ts = None
                    ultimo_ts = None
                    for line in lines:
                        m_ts = re.match(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]', line)
                        if m_ts:
                            try:
                                ts = datetime.datetime.strptime(m_ts.group(1), '%Y-%m-%d %H:%M:%S')
                                if primeiro_ts is None:
                                    primeiro_ts = ts
                                ultimo_ts = ts
                            except Exception:
                                pass
                    if primeiro_ts and ultimo_ts and ultimo_ts >= primeiro_ts:
                        diff_sec = int((ultimo_ts - primeiro_ts).total_seconds())
                        m, s = divmod(diff_sec, 60)
                        h, m = divmod(m, 60)
                        if h > 0:
                            duracao_str = f"{h}h {m}m {s}s"
                        elif m > 0:
                            duracao_str = f"{m}m {s}s"
                        else:
                            duracao_str = f"{s}s"
                        
                # Adiciona falhas de validação se houver
                qtd_falhas_exibidas = len(falhas_list) + total_falhas
                status_general = "FALHA / ATENÇÃO" if (qtd_falhas_exibidas > 0 or "ERRO CRITICO" in content) else "SUCESSO"
                badge_class = "badge-success" if status_general == "SUCESSO" else "badge-warning" if qtd_falhas_exibidas > 0 else "badge-danger"
                
                badges_header = []
                if is_test_mode:
                    badges_header.append('<span class="badge bg-info text-dark me-1">TESTE</span>')
                if is_mockup:
                    badges_header.append('<span class="badge bg-warning text-dark me-1">MOCKUP</span>')
                badges_str = "".join(badges_header)
                
                # Renderiza itens da aba de falhas
                falhas_items_html = ""
                if falhas_list:
                    for f_item in falhas_list:
                        item_formatado = f_item
                        if "[FALHA/INVALIDO]" in item_formatado:
                            item_formatado = item_formatado.replace("[FALHA/INVALIDO]", '<span class="text-danger fw-bold">[FALHA/INVALIDO]</span>')
                            item_formatado = re.sub(r'ID(?:/NossoNumero)?:\s*([^\s|]+)', r'ID: <span class="text-danger fw-bold">\1</span>', item_formatado)
                            item_formatado = re.sub(r'Motivo:\s*(.+)$', r'Motivo: <span class="text-danger">\1</span>', item_formatado)
                        elif "ERRO CRITICO" in item_formatado:
                            item_formatado = f'<span class="text-danger fw-bold">{item_formatado}</span>'

                        falhas_items_html += f'<li class="list-group-item bg-white text-dark border-0 border-bottom border-danger-subtle py-2 px-3"><i class="fas fa-exclamation-triangle text-danger me-2"></i>{item_formatado}</li>'
                else:
                    falhas_items_html = '<li class="list-group-item bg-white text-success border-0 border-bottom border-success-subtle py-2 px-3"><i class="fas fa-check-circle text-success me-2"></i>Nenhuma falha individual registrada neste processamento.</li>'

                cards_html += f"""
                <div class="accordion-item mb-3 shadow-sm border-0 rounded">
                    <h2 class="accordion-header" id="heading_{idx}">
                        <button class="accordion-button collapsed py-3" type="button" data-bs-toggle="collapse" data-bs-target="#collapse_{idx}" aria-expanded="false" aria-controls="collapse_{idx}">
                            <div class="d-flex justify-content-between align-items-center w-100 me-3">
                                <div>
                                    <strong style="font-size: 1.05rem;"><i class="far fa-clock me-2"></i>{date_str}</strong>
                                    {badges_str}
                                </div>
                                <div>
                                    <span class="badge bg-dark text-white me-2"><i class="fas fa-stopwatch me-1"></i>{duracao_str}</span>
                                    <span class="badge bg-secondary me-2">Lidos: {total_processados}</span>
                                    <span class="badge bg-success me-2">Ok: {total_atualizados + total_criados}</span>
                                    <span class="badge bg-danger me-2">Falhas: {total_falhas + len(falhas_list)}</span>
                                    <span class="badge {badge_class}">{status_general}</span>
                                </div>
                            </div>
                        </button>
                    </h2>
                    <div id="collapse_{idx}" class="accordion-collapse collapse" aria-labelledby="heading_{idx}">
                        <div class="accordion-body bg-white rounded-bottom">
                            
                            <!-- Métricas Cards -->
                            <div class="row text-center mb-4 g-2">
                                <div class="col-md-2">
                                    <div class="p-3 bg-light rounded border h-100">
                                        <div class="text-muted small">Total Lidos</div>
                                        <div class="fs-4 fw-bold text-dark">{total_processados}</div>
                                    </div>
                                </div>
                                <div class="col-md-3">
                                    <div class="p-3 bg-light rounded border border-success h-100">
                                        <div class="text-muted small">Atualizados / Inseridos</div>
                                        <div class="fs-4 fw-bold text-success">{total_atualizados + total_criados}</div>
                                    </div>
                                </div>
                                <div class="col-md-2">
                                    <div class="p-3 bg-light rounded border border-danger h-100">
                                        <div class="text-muted small">Falhas</div>
                                        <div class="fs-4 fw-bold text-danger">{total_falhas + len(falhas_list)}</div>
                                    </div>
                                </div>
                                <div class="col-md-2">
                                    <div class="p-3 bg-light rounded border border-info h-100">
                                        <div class="text-muted small">Tempo Total</div>
                                        <div class="fs-4 fw-bold text-primary"><i class="fas fa-stopwatch me-1"></i>{duracao_str}</div>
                                    </div>
                                </div>
                                <div class="col-md-3">
                                    <div class="p-3 bg-light rounded border h-100">
                                        <div class="text-muted small">Modo de Operação</div>
                                        <div class="fs-6 fw-bold text-secondary mt-1">{"Teste Limitado" if is_test_mode else "Completa"} ({"Mockup" if is_mockup else "AWS MySQL"})</div>
                                    </div>
                                </div>
                            </div>

                            <!-- Tabs de Detalhamento -->
                            <ul class="nav nav-tabs" id="tab_{idx}" role="tablist">
                                <li class="nav-item" role="presentation">
                                    <button class="nav-link active text-danger fw-bold" id="falhas-tab_{idx}" data-bs-toggle="tab" data-bs-target="#falhas_{idx}" type="button" role="tab">
                                        <i class="fas fa-bug me-1"></i> Lista de Falhas ({len(falhas_list)})
                                    </button>
                                </li>
                                <li class="nav-item" role="presentation">
                                    <button class="nav-link text-dark" id="log-tab_{idx}" data-bs-toggle="tab" data-bs-target="#log_{idx}" type="button" role="tab">
                                        <i class="fas fa-terminal me-1"></i> Log Bruto de Execução
                                    </button>
                                </li>
                            </ul>
                            
                            <div class="tab-content p-3 border border-top-0 rounded-bottom bg-light" id="tabContent_{idx}">
                                <div class="tab-pane fade show active" id="falhas_{idx}" role="tabpanel">
                                    <h6 class="text-muted mb-3">Registros que apresentaram inconsistência ou falha de inserção:</h6>
                                    <ul class="list-group max-height-list">
                                        {falhas_items_html}
                                    </ul>
                                </div>
                                <div class="tab-pane fade" id="log_{idx}" role="tabpanel">
                                    <pre class="bg-dark text-light p-3 rounded font-monospace" style="max-height: 400px; overflow-y: auto; font-size: 12px;">{content}</pre>
                                </div>
                            </div>

                        </div>
                    </div>
                </div>
                """
            except Exception:
                pass
                
        html_template = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard Sincronização Boletos AWS - MSF</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body {{ background-color: #f0f2f5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        .header-box {{ background: linear-gradient(135deg, #0d3b66 0%, #001e3d 100%); color: white; padding: 25px 20px; border-radius: 12px; margin-bottom: 25px; box-shadow: 0 4px 12px rgba(0,0,0,0.12); }}
        .badge-success {{ background-color: #198754; }}
        .badge-warning {{ background-color: #ffc107; color: #000; }}
        .badge-danger {{ background-color: #dc3545; }}
        .accordion-button:not(.collapsed) {{ background-color: #e7f1ff; color: #0c63e4; }}
        .max-height-list {{ max-height: 380px; overflow-y: auto; font-size: 11.5px; font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; }}
    </style>
</head>
<body>
    <div class="container py-4">
        <div class="header-box d-flex justify-content-between align-items-center">
            <div>
                <h2 class="fw-bold m-0"><i class="fas fa-file-invoice-dollar me-2"></i> Sincronização de Boletos (SQL Server ➔ AWS MySQL)</h2>
                <p class="m-0 text-white-50 mt-1">Painel operacional, histórico de execuções e relatório de inconsistências</p>
            </div>
            <div class="text-end">
                <span class="badge bg-light text-dark p-2"><i class="far fa-calendar-alt me-1"></i> Atualizado em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</span>
            </div>
        </div>

        <div class="accordion" id="accordionLogs">
            {cards_html if cards_html else '<div class="alert alert-secondary text-center">Nenhum histórico de execução encontrado em logs/.</div>'}
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""

        with open(self.dashboard_path, 'w', encoding='utf-8') as f:
            f.write(html_template)
            
        return self.dashboard_path
