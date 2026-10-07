"""
Validador de invariantes do extrato BTG (payload v3 de app/tools/btg_xlsx_parser.py).

Por que existe: o parser confere o que leu contra o Sumário (checagem), mas quem decidia
gravar ignorava o resultado, e várias invariantes internas do extrato (Σ linhas = Total do
bloco, Σ mercados = Total do Sumário, encadeamento entre meses...) nunca eram conferidas.
Este módulo roda TODAS elas sobre o payload pronto e devolve um veredito por gravidade —
divergência de centavos é do próprio BTG e não pode travar o dono; acima de R$ 1,00 é
dinheiro sumindo e trava.

Contrato congelado (outros pontos do app programam contra ele):

  validar_extrato(payload) -> dict          puro, sem banco; payload v1/v2 → checks
                                            'nao_avaliavel' (veredito ok + nota)
  validar_encadeamento(session, payload)    V7 — precisa do banco; severidade máx. aviso
  anexar_validacao(extrato, session=None)   ExtratoParsed.to_dict() + payload["validacao"]
                                            (com V7 quando houver session)

Saída: {"versao_validador": 1, "veredito": "ok"|"aviso"|"erro",
        "checks": [{"id", "rotulo", "severidade": "ok"|"aviso"|"erro"|"nao_avaliavel",
                    "esperado", "obtido", "diferenca", "detalhe"}],
        "erros": [str], "avisos": [str], "tolerancias": {"ok": 0.05, "erro": 1.00}}

Convenções:
  - `esperado` é o número que o PRÓPRIO extrato declara (Sumário, linha de total);
    `obtido` é o que o parser leu/somou; diferenca = obtido - esperado.
  - '-' no extrato virou None no parser; em total e mercado, None vale 0,00. Mercado
    presente no Sumário com '-' no período atual = classe zerada (não é falta de
    cobertura).
  - Checks estruturais (V8, colisão sem-vencimento, quantidade 0 não-derivável em classe
    com cotação) não têm régua: são erro direto.
  - `detalhe` nunca carrega saldo absoluto — só diferenças, contagens, datas e nomes —
    para a saída do smoke local poder ser colada sem expor a carteira. Os saldos ficam
    em esperado/obtido e nas mensagens de `erros`/`avisos` (que vão só para a tela).
  - `validacao` entra no payload como irmã de `checagem`, nunca dentro dela: o preview
    filtra `checagem` por lista e vazaria chaves novas para o modelo.

Quem chama: os call sites de API/gravação (fora deste módulo). parse_btg_xlsx NÃO chama
anexar_validacao — seria import circular.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional

from .btg_xlsx_parser import ExtratoParsed, _norm, _norm_mercado, _num, _slug

VERSAO_VALIDADOR = 1
TOLERANCIA_OK = 0.05      # até aqui é arredondamento do próprio BTG: ok
TOLERANCIA_ERRO = 1.00    # até aqui aviso; acima, erro (bloqueia a gravação)

# Classes de posição que cada mercado do Sumário exige (V8). 'Valores em Trânsito' fica
# de fora de propósito: trânsito não é posição (o próprio parser o exclui do checksum).
_COBERTURA: dict[str, Optional[set]] = {
    "renda variavel": {"ACAO", "ETF", "FII", "BDR"},
    "renda fixa": {"TESOURO", "RF"},
    "conta corrente": {"CAIXA"},
    "fundos de investimento": {"FUNDO"},
    "criptoativos": {"CRIPTO"},
    "valores em transito": None,          # ignorado
}

# Classes em que quantidade 0 com valor em carteira é erro estrutural: a cotação ao vivo
# multiplicaria 0 e o papel "sumiria" do dashboard.
_CLASSES_COM_COTACAO = {"ACAO", "ETF", "FII", "BDR", "CRIPTO"}

# Checks publicados mesmo quando não dá para avaliar (payload v1/v2): a UI mostra a
# lista estável com 'nao_avaliavel' em vez de fingir que está tudo certo.
_CHECKS_BASE: tuple[tuple[str, str], ...] = (
    ("V1_SUMARIO_BRUTO_FIM", "Sumário: Σ mercados = Total (bruto, fim)"),
    ("V1_SUMARIO_LIQ_FIM", "Sumário: Σ mercados = Total (líquido, fim)"),
    ("V1_SUMARIO_BRUTO_INI", "Sumário: Σ mercados = Total (bruto, início)"),
    ("V1_SUMARIO_LIQ_INI", "Sumário: Σ mercados = Total (líquido, início)"),
    ("V2_RV_TOTAL", "Renda Variável: Σ totais dos blocos + aluguel = Sumário"),
    ("V3_RF_TOTAL_BRUTO", "Renda Fixa: Σ totais das seções = Sumário (bruto)"),
    ("V3_RF_TOTAL_LIQ", "Renda Fixa: Σ totais das seções = Sumário (líquido)"),
    ("V4_CC_RAZAO", "Conta corrente: saldo inicial + Σ lançamentos = saldo final"),
    ("V4_CC_CREDITOS", "Conta corrente: Σ créditos = Total de Créditos"),
    ("V4_CC_DEBITOS", "Conta corrente: Σ débitos = Total de Débitos"),
    ("V4_CC_VS_CAIXA", "Conta corrente: saldo final = posição CAIXA"),
    ("V4_CC_VS_SUMARIO_ANTERIOR", "Conta corrente: Saldo Anterior = Sumário anterior"),
    ("V5_TRANSITO_TOTAL", "Valores em trânsito: Σ linhas = Total da aba"),
    ("V5_TRANSITO_SUMARIO", "Valores em trânsito: Total da aba = Sumário"),
    ("V6_FUNDOS", "Fundos: Total da aba = Sumário"),
    ("V6_CRIPTO", "CriptoAtivos: Total da aba = Sumário"),
    ("V8_COBERTURA", "Cobertura: todo mercado do Sumário tem posições da classe"),
    ("V9_DATAS", "Datas: Capa, Sumário e posição CAIXA apontam o mesmo fim"),
    ("V10_QTDE_PRECO", "Posições: quantidade × preço ≈ saldo"),
)


# ---------------------------------------------------------------------------
# Régua e montagem
# ---------------------------------------------------------------------------

def _r2(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(float(v), 2)


def _severidade(dif: Optional[float]) -> str:
    if dif is None:
        return "nao_avaliavel"
    d = abs(round(dif, 2))
    if d <= TOLERANCIA_OK:
        return "ok"
    if d <= TOLERANCIA_ERRO:
        return "aviso"
    return "erro"


def _check(
    cid: str,
    rotulo: str,
    esperado: Optional[float],
    obtido: Optional[float],
    detalhe: str = "",
    severidade: Optional[str] = None,
    diferenca: Optional[float] = None,
) -> dict:
    """`diferenca` explícita é para os checks que REUSAM uma diferença já computada."""
    if diferenca is None and esperado is not None and obtido is not None:
        diferenca = round(obtido - esperado, 2)
    return {
        "id": cid,
        "rotulo": rotulo,
        "severidade": severidade or _severidade(diferenca),
        "esperado": _r2(esperado),
        "obtido": _r2(obtido),
        "diferenca": _r2(diferenca),
        "detalhe": detalhe,
    }


def _na(cid: str, rotulo: str, detalhe: str) -> dict:
    return _check(cid, rotulo, None, None, detalhe=detalhe, severidade="nao_avaliavel")


def _mensagem(c: dict) -> str:
    base = f"{c['id']} — {c['rotulo']}"
    if c["esperado"] is not None and c["obtido"] is not None:
        base += (
            f": esperado R$ {c['esperado']:,.2f}, obtido R$ {c['obtido']:,.2f}"
            f" (diferença R$ {c['diferenca']:,.2f})"
        )
    if c["detalhe"]:
        base += f" [{c['detalhe']}]"
    return base


def _montar_resultado(checks: list[dict]) -> dict:
    veredito = "ok"
    erros: list[str] = []
    avisos: list[str] = []
    for c in checks:
        if c["severidade"] == "erro":
            erros.append(_mensagem(c))
            veredito = "erro"
        elif c["severidade"] == "aviso":
            avisos.append(_mensagem(c))
            if veredito != "erro":
                veredito = "aviso"
    return {
        "versao_validador": VERSAO_VALIDADOR,
        "veredito": veredito,
        "checks": checks,
        "erros": erros,
        "avisos": avisos,
        "tolerancias": {"ok": TOLERANCIA_OK, "erro": TOLERANCIA_ERRO},
    }


# ---------------------------------------------------------------------------
# Acesso ao payload (sempre defensivo: o payload vem do banco, de qualquer época)
# ---------------------------------------------------------------------------

def _sumario_bloco(payload: dict, periodo: str) -> dict:
    return (payload.get("sumario") or {}).get(periodo) or {}


def _mercado(payload: dict, nome: str, periodo: str = "atual") -> tuple[bool, dict]:
    """(mercado presente no Sumário?, {bruto, liquido}). Casa ignorando o '*' decorativo."""
    for rotulo, valores in (_sumario_bloco(payload, periodo).get("mercados") or {}).items():
        if _norm_mercado(rotulo) == _norm_mercado(nome):
            return True, valores or {}
    return False, {}


def _coluna(valores: Optional[dict], *prefixos: str) -> tuple[bool, float]:
    """(coluna existe?, valor com '-'→0,00). Rótulo achado por prefixo normalizado."""
    for prefixo in prefixos:
        for rotulo, v in (valores or {}).items():
            if rotulo.startswith(prefixo):
                return True, (float(v) if v is not None else 0.0)
    return False, 0.0


def _totais(payload: dict, aba: str) -> list[dict]:
    return (payload.get("totais_abas") or {}).get(aba) or []


def _blocos_posicao(entradas: list[dict], excluir_aluguel: bool = False) -> list[dict]:
    # 'posicao >' com o '>' de propósito: deixa de fora 'Posição Consolidada Por
    # Emissor >' (conferência por emissor do próprio extrato, não é bloco de posição).
    out = []
    for e in entradas:
        bloco = _norm(e.get("bloco"))
        if not bloco.startswith("posicao >"):
            continue
        if excluir_aluguel and "aluguel" in bloco:
            continue
        out.append(e)
    return out


def _avisos_do_parser(payload: dict, tipo: str) -> list[dict]:
    return [a for a in payload.get("avisos_parser") or [] if (a or {}).get("tipo") == tipo]


# ---------------------------------------------------------------------------
# Checks V1–V10
# ---------------------------------------------------------------------------

def _v1_sumario(payload: dict) -> list[dict]:
    checks = []
    for periodo, suf_p in (("atual", "FIM"), ("anterior", "INI")):
        bloco = _sumario_bloco(payload, periodo)
        mercados = bloco.get("mercados") or {}
        total = bloco.get("total") or {}
        for tipo, suf_t in (("bruto", "BRUTO"), ("liquido", "LIQ")):
            cid = f"V1_SUMARIO_{suf_t}_{suf_p}"
            rotulo = f"Sumário: Σ mercados = Total ({tipo}, {'fim' if periodo == 'atual' else 'início'})"
            if not mercados or total.get(tipo) is None:
                checks.append(_na(cid, rotulo, f"Sumário sem o período '{periodo}' ou sem o total {tipo}"))
                continue
            soma = round(sum((v or {}).get(tipo) or 0.0 for v in mercados.values()), 2)
            checks.append(_check(cid, rotulo, esperado=total[tipo], obtido=soma,
                                 detalhe=f"{len(mercados)} mercado(s)"))
    return checks


def _v2_rv(payload: dict) -> list[dict]:
    cid, rotulo = "V2_RV_TOTAL", "Renda Variável: Σ totais dos blocos + aluguel = Sumário"
    blocos = _blocos_posicao(_totais(payload, "renda_variavel"), excluir_aluguel=True)
    presente, mercado = _mercado(payload, "Renda Variável")
    soma = 0.0
    usados = 0
    for e in blocos:
        tem, v = _coluna(e.get("valores"), "saldo bruto")
        if tem:
            soma += v
            usados += 1
    # O Sumário do BTG soma o resultado acumulado do aluguel ao mercado de RV.
    aluguel = round(sum(_num(a.get("resultado_acumulado_liquido")) or 0.0
                        for a in payload.get("aluguel") or []), 2)
    if not usados and not presente:
        return [_na(cid, rotulo, "extrato sem blocos de posição de RV e sem o mercado no Sumário")]
    if not usados:
        return [_na(cid, rotulo, "nenhum bloco de posição de RV tem linha de total")]
    esperado = mercado.get("bruto") if presente else None
    return [_check(cid, rotulo, esperado=esperado if esperado is not None else 0.0,
                   obtido=round(soma + aluguel, 2),
                   detalhe=f"{usados} bloco(s) de posição; resultado de aluguel somado")]


def _v3_rf(payload: dict) -> list[dict]:
    checks: list[dict] = []
    secoes = _blocos_posicao(_totais(payload, "renda_fixa"))
    presente, mercado = _mercado(payload, "Renda Fixa")

    for tipo, suf in (("saldo bruto", "BRUTO"), ("saldo liquido", "LIQ")):
        cid = f"V3_RF_TOTAL_{suf}"
        rotulo = f"Renda Fixa: Σ totais das seções = Sumário ({'bruto' if suf == 'BRUTO' else 'líquido'})"
        if not secoes and not presente:
            checks.append(_na(cid, rotulo, "extrato sem seções de posição de RF e sem o mercado no Sumário"))
            continue
        soma = 0.0
        usados = 0
        for e in secoes:
            tem, v = _coluna(e.get("valores"), tipo)
            if tem:
                soma += v
                usados += 1
        esperado = mercado.get("bruto" if suf == "BRUTO" else "liquido") if presente else None
        if not usados:
            checks.append(_na(cid, rotulo, "nenhuma seção de posição de RF tem linha de total"))
            continue
        checks.append(_check(cid, rotulo, esperado=esperado if esperado is not None else 0.0,
                             obtido=round(soma, 2), detalhe=f"{usados} seção(ões)"))

    # Σ linhas = Total, seção a seção (pega linha de posição perdida DENTRO do bloco).
    usados_ids: dict[str, int] = {}
    for e in secoes:
        nome_bloco = (e.get("bloco") or "").split(">", 1)[-1].strip()
        base = f"V3_RF_SECAO_{_slug(nome_bloco) or 'SEM-NOME'}"
        n = usados_ids.get(base, 0)
        usados_ids[base] = n + 1
        cid = base if n == 0 else f"{base}_{n + 1}"
        rotulo = f"Renda Fixa: Σ linhas = Total da seção {nome_bloco or '?'}"
        tem_t, total = _coluna(e.get("valores"), "saldo bruto")
        tem_s, soma = _coluna(e.get("soma_linhas"), "saldo bruto")
        if not tem_t:
            checks.append(_na(cid, rotulo, "linha de total sem coluna de saldo bruto"))
            continue
        checks.append(_check(cid, rotulo, esperado=total, obtido=soma if tem_s else 0.0))

    # Estrutural: papéis distintos fundidos numa chave 'sem-vencimento' — a posição
    # agregada seria mentira (o parser só consegue avisar; o bloqueio é daqui).
    colisoes = _avisos_do_parser(payload, "colisao_sem_vencimento")
    if colisoes:
        detalhes = "; ".join(sorted({a.get("detalhe") or "" for a in colisoes}))
        checks.append(_check(
            "V3_RF_COLISAO_VENCIMENTO",
            "Renda Fixa: títulos distintos fundidos sem vencimento legível",
            None, None, detalhe=detalhes[:300], severidade="erro",
        ))
    return checks


def _v4_conta(payload: dict) -> list[dict]:
    """
    REUSA as diferenças já computadas em checagem.conta_corrente (não recalcula nada):
    o parser é quem conhece o razão linha a linha.
    """
    conta = (payload.get("checagem") or {}).get("conta_corrente") or {}
    rotulos = dict(_CHECKS_BASE)
    if not conta.get("encontrada"):
        return [
            _na(cid, rotulos[cid], "aba Conta Corrente sem a tabela de movimentações")
            for cid in ("V4_CC_RAZAO", "V4_CC_CREDITOS", "V4_CC_DEBITOS",
                        "V4_CC_VS_CAIXA", "V4_CC_VS_SUMARIO_ANTERIOR")
        ]

    checks: list[dict] = []
    saldo_final = _num(conta.get("saldo_final"))
    dif_razao = _num(conta.get("diferenca"))
    dc, dd = _num(conta.get("dif_creditos")), _num(conta.get("dif_debitos"))

    # Créditos/débitos: quando os DOIS lados divergem pelo MESMO valor e o razão fecha,
    # é o extrato contando uma liquidação pelo bruto nos totais e pelo líquido na linha
    # (visto em extrato real: crédito e débito nettados numa linha de bolsa). Nada se
    # perdeu — o saldo prova — então vira aviso, nunca erro.
    netting = (
        dc is not None and dd is not None
        and abs(dc - dd) <= TOLERANCIA_OK
        and dif_razao is not None and abs(dif_razao) <= TOLERANCIA_OK
    )

    if dif_razao is None:
        checks.append(_na("V4_CC_RAZAO", rotulos["V4_CC_RAZAO"], "razão sem saldo inicial ou final"))
    else:
        obtido = None
        if _num(conta.get("saldo_inicial")) is not None and _num(conta.get("soma_lancamentos")) is not None:
            obtido = round(conta["saldo_inicial"] + conta["soma_lancamentos"], 2)
        checks.append(_check(
            "V4_CC_RAZAO", rotulos["V4_CC_RAZAO"], esperado=saldo_final, obtido=obtido,
            diferenca=dif_razao,
            detalhe=f"{conta.get('linhas_descartadas', 0)} linha(s) sem valor; "
                    f"{conta.get('sinal_divergente', 0)} sinal(is) divergente(s)",
        ))

    for cid, dif, esperado, obtido in (
        ("V4_CC_CREDITOS", dc, _num(conta.get("creditos_extrato")), _num(conta.get("creditos"))),
        ("V4_CC_DEBITOS", dd, _num(conta.get("debitos_extrato")),
         abs(_num(conta.get("debitos")) or 0.0) if conta.get("debitos") is not None else None),
    ):
        if dif is None:
            checks.append(_na(cid, rotulos[cid], "extrato sem a linha de total correspondente"))
            continue
        sev = _severidade(dif)
        detalhe = ""
        if netting and sev == "erro":
            sev = "aviso"
            detalhe = ("créditos e débitos divergem pelo mesmo valor e o razão fecha — "
                       "liquidação nettada na linha e contada pelo bruto nos totais do extrato")
        checks.append(_check(cid, rotulos[cid], esperado=esperado, obtido=obtido,
                             diferenca=dif, severidade=sev, detalhe=detalhe))

    vs_caixa = _num(conta.get("vs_caixa"))
    if vs_caixa is None:
        checks.append(_na("V4_CC_VS_CAIXA", rotulos["V4_CC_VS_CAIXA"],
                          "sem posição CAIXA ou sem saldo final no razão"))
    else:
        esperado = round(saldo_final - vs_caixa, 2) if saldo_final is not None else None
        checks.append(_check("V4_CC_VS_CAIXA", rotulos["V4_CC_VS_CAIXA"],
                             esperado=esperado, obtido=saldo_final, diferenca=vs_caixa))

    vs_ant = _num(conta.get("vs_sumario_anterior"))
    if vs_ant is None:
        checks.append(_na("V4_CC_VS_SUMARIO_ANTERIOR", rotulos["V4_CC_VS_SUMARIO_ANTERIOR"],
                          "Sumário sem o mercado Conta Corrente no período anterior"))
    else:
        saldo_ini = _num(conta.get("saldo_inicial"))
        esperado = round(saldo_ini - vs_ant, 2) if saldo_ini is not None else None
        checks.append(_check("V4_CC_VS_SUMARIO_ANTERIOR", rotulos["V4_CC_VS_SUMARIO_ANTERIOR"],
                             esperado=esperado, obtido=saldo_ini, diferenca=vs_ant))
    return checks


def _v5_transito(payload: dict) -> list[dict]:
    checks = []
    linhas = payload.get("valores_em_transito") or []
    soma = round(sum(_num(v.get("valor")) or 0.0 for v in linhas), 2)
    entradas = _totais(payload, "valores_em_transito")
    total_aba: Optional[float] = None
    for e in entradas:
        tem, v = _coluna(e.get("valores"), "valor")
        if tem:
            total_aba = round((total_aba or 0.0) + v, 2)
    presente, mercado = _mercado(payload, "Valores em Trânsito")

    rotulo = "Valores em trânsito: Σ linhas = Total da aba"
    if total_aba is None and not linhas and not presente:
        checks.append(_na("V5_TRANSITO_TOTAL", rotulo, "extrato sem valores em trânsito"))
    elif total_aba is None:
        checks.append(_na("V5_TRANSITO_TOTAL", rotulo, "aba sem linha de total"))
    else:
        checks.append(_check("V5_TRANSITO_TOTAL", rotulo, esperado=total_aba, obtido=soma,
                             detalhe=f"{len(linhas)} linha(s)"))

    rotulo = "Valores em trânsito: Total da aba = Sumário"
    if not presente and total_aba is None and not linhas:
        checks.append(_na("V5_TRANSITO_SUMARIO", rotulo, "extrato sem valores em trânsito"))
    else:
        esperado = (mercado.get("bruto") if presente else None)
        obtido = total_aba if total_aba is not None else soma
        checks.append(_check("V5_TRANSITO_SUMARIO", rotulo,
                             esperado=esperado if esperado is not None else 0.0, obtido=obtido))
    return checks


def _v6_classe(payload: dict, aba: str, mercado_nome: str, coluna_total: str,
               classe: str, cid: str) -> list[dict]:
    """V6: o Total da aba (Fundos/CriptoAtivos) tem de bater com o mercado do Sumário."""
    rotulo = f"{mercado_nome}: Total da aba = Sumário"
    entradas = _blocos_posicao(_totais(payload, aba))
    presente, mercado = _mercado(payload, mercado_nome)
    tem_posicoes = any((p or {}).get("classe") == classe for p in payload.get("posicoes") or [])
    if not entradas and not presente and not tem_posicoes:
        return []          # extrato realmente sem a classe: check não se aplica
    total: Optional[float] = None
    for e in entradas:
        tem, v = _coluna(e.get("valores"), coluna_total)
        if tem:
            total = round((total or 0.0) + v, 2)
    if total is None:
        # Aba só com movimentações (posição zerada) ou sem linha de total: a soma das
        # posições lidas é o que há para comparar.
        total = round(sum(_num(p.get("valor_mercado")) or 0.0
                          for p in payload.get("posicoes") or []
                          if (p or {}).get("classe") == classe), 2)
    esperado = mercado.get("bruto") if presente else None
    return [_check(cid, rotulo, esperado=esperado if esperado is not None else 0.0,
                   obtido=total)]


def _v8_cobertura(payload: dict) -> list[dict]:
    mercados = _sumario_bloco(payload, "atual").get("mercados") or {}
    if not mercados:
        return [_na("V8_COBERTURA", "Cobertura: todo mercado do Sumário tem posições da classe",
                    "Sumário sem mercados")]
    presentes = {(p or {}).get("classe") for p in payload.get("posicoes") or []}
    checks = []
    for rotulo_mercado, valores in mercados.items():
        nome = _norm_mercado(rotulo_mercado)
        if nome == "total":
            continue
        cid = f"V8_COBERTURA_{_slug(nome)}"
        rotulo = f"Cobertura: {rotulo_mercado}"
        if nome not in _COBERTURA:
            checks.append(_check(cid, rotulo, None, None, severidade="erro",
                                 detalhe=f"mercado desconhecido no Sumário ('{rotulo_mercado}') — "
                                         "classe que o parser não lê; posições podem estar faltando"))
            continue
        classes = _COBERTURA[nome]
        if classes is None:
            continue       # trânsito: não é posição
        bruto = (valores or {}).get("bruto")
        if bruto is None or abs(bruto) <= 0.005:
            checks.append(_check(cid, rotulo, None, None, severidade="ok",
                                 detalhe="mercado zerado no fim do período"))
            continue
        if classes & presentes:
            checks.append(_check(cid, rotulo, None, None, severidade="ok",
                                 detalhe=f"coberto por {sorted(classes & presentes)}"))
        else:
            checks.append(_check(cid, rotulo, None, None, severidade="erro",
                                 detalhe=f"o Sumário aponta saldo em '{rotulo_mercado}' mas nenhuma "
                                         f"posição de {sorted(classes)} foi lida"))
    return checks


def _v9_datas(payload: dict) -> list[dict]:
    cid, rotulo = "V9_DATAS", "Datas: Capa, Sumário e posição CAIXA apontam o mesmo fim"
    fim = payload.get("data_referencia")
    if not fim:
        return [_na(cid, rotulo, "payload sem data_referencia")]
    problemas = []
    data_sumario = _sumario_bloco(payload, "atual").get("data")
    if data_sumario and data_sumario != fim:
        problemas.append(f"Sumário atual em {data_sumario}, Capa em {fim}")
    for p in payload.get("posicoes") or []:
        if (p or {}).get("classe") == "CAIXA":
            as_of = p.get("as_of")
            if as_of and as_of != fim:
                problemas.append(f"CAIXA com as_of {as_of}, Capa em {fim}")
            break
    emitido = ((payload.get("sumario") or {}).get("meta") or {}).get("emitido_em")
    if emitido and emitido < fim:
        problemas.append(f"emitido_em {emitido} anterior ao fim do período {fim}")
    if problemas:
        # Datas desencontradas não somem com dinheiro, mas datam errado a série: aviso.
        return [_check(cid, rotulo, None, None, severidade="aviso", detalhe="; ".join(problemas))]
    return [_check(cid, rotulo, None, None, severidade="ok", detalhe="")]


def _v10_qtde_preco(payload: dict) -> list[dict]:
    checks = []
    decorado = bool(_avisos_do_parser(payload, "ticker_decorado"))
    cid, rotulo = "V10_QTDE_PRECO", "Posições: quantidade × preço ≈ saldo"
    pior: Optional[tuple[float, float, float, str]] = None    # (|dif|, esperado, obtido, chave)
    ofensores: list[str] = []
    avaliadas = 0
    for p in payload.get("posicoes") or []:
        p = p or {}
        if p.get("classe") == "CAIXA":
            continue
        q, preco, saldo = _num(p.get("quantidade")), _num(p.get("preco_fechamento")), _num(p.get("valor_mercado"))
        if q is None or preco is None or saldo is None:
            continue
        avaliadas += 1
        dif = round(q * preco - saldo, 2)
        chave = p.get("chave_externa") or p.get("ticker") or p.get("nome") or "?"
        if abs(dif) > TOLERANCIA_OK:
            ofensores.append(f"{chave} (dif R$ {dif:,.2f})")
        if pior is None or abs(dif) > pior[0]:
            pior = (abs(dif), saldo, round(q * preco, 2), chave)
    if not avaliadas or pior is None:
        checks.append(_na(cid, rotulo, "nenhuma posição com quantidade e preço para conferir"))
    else:
        dif = round(pior[2] - pior[1], 2)
        sev = _severidade(dif)
        detalhe = f"{avaliadas} posição(ões); pior: {pior[3]}"
        if ofensores:
            detalhe += " | " + "; ".join(ofensores[:5])
        if decorado and sev != "ok":
            # Extrato de período aberto usa preço de datas distintas por posição: a
            # conta não fecha MESMO quando o parse está certo — vira nota informativa.
            sev = "aviso"
            detalhe += " | extrato decorado ('*'): preços de datas distintas, nota informativa"
        checks.append(_check(cid, rotulo, esperado=pior[1], obtido=pior[2],
                             severidade=sev, detalhe=detalhe))

    # Estrutural: quantidade 0 (ilegível e não-derivável) em classe com cotação ao vivo.
    zeradas = [
        (p or {}).get("chave_externa") or (p or {}).get("ticker") or "?"
        for p in payload.get("posicoes") or []
        if (p or {}).get("classe") in _CLASSES_COM_COTACAO
        and not _num((p or {}).get("quantidade"))
        and abs(_num((p or {}).get("valor_mercado")) or 0.0) > 0.005
    ]
    if zeradas:
        checks.append(_check(
            "V10_QTDE_ZERO", "Posições: quantidade ilegível (0) em classe com cotação",
            None, None, severidade="erro",
            detalhe="quantidade 0 não-derivável em: " + ", ".join(sorted(zeradas)[:8]),
        ))
    return checks


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def validar_extrato(payload: dict) -> dict:
    """
    Roda todas as invariantes sobre um payload do parser (ExtratoParsed.to_dict() ou o
    payload_json de um ExtratoImportado). Puro: não toca banco nem rede. Payload v1/v2
    não tem os campos necessários → todos os checks saem 'nao_avaliavel' e o veredito
    fica "ok" com uma nota em `avisos` (não dá para reprovar o que não dá para medir).
    """
    payload = payload or {}
    versao = int(payload.get("versao_parser") or 1)
    if versao < 3:
        checks = [
            _na(cid, rotulo, f"payload v{versao}, anterior ao validador")
            for cid, rotulo in _CHECKS_BASE
        ]
        resultado = _montar_resultado(checks)
        resultado["avisos"].append(
            f"Extrato arquivado com parser v{versao}, anterior ao validador — reenvie o "
            "XLSX (chat ou lote) para conferir as invariantes."
        )
        return resultado

    checks: list[dict] = []
    checks += _v1_sumario(payload)
    checks += _v2_rv(payload)
    checks += _v3_rf(payload)
    checks += _v4_conta(payload)
    checks += _v5_transito(payload)
    checks += _v6_classe(payload, "fundos", "Fundos de Investimento", "saldo bruto",
                         "FUNDO", "V6_FUNDOS")
    checks += _v6_classe(payload, "cripto", "CriptoAtivos", "valor bruto",
                         "CRIPTO", "V6_CRIPTO")
    checks += _v8_cobertura(payload)
    checks += _v9_datas(payload)
    checks += _v10_qtde_preco(payload)
    return _montar_resultado(checks)


def validar_encadeamento(session, payload: dict) -> list[dict]:
    """
    V7: o Sumário "anterior" deste payload tem de bater com o Sumário "atual" do mês
    arquivado imediatamente anterior (ExtratoImportado). Divergência aqui indica mês
    faltando ou extrato substituído — nunca passa de AVISO: meses não contíguos são
    legítimos (o motor de desempenho já os trata).
    """
    rotulos = {
        "V7_ENCADEAMENTO_BRUTO": "Encadeamento: Sumário anterior = mês arquivado anterior (bruto)",
        "V7_ENCADEAMENTO_LIQ": "Encadeamento: Sumário anterior = mês arquivado anterior (líquido)",
    }

    def _todos_na(detalhe: str) -> list[dict]:
        return [_na(cid, rot, detalhe) for cid, rot in rotulos.items()]

    payload = payload or {}
    if int(payload.get("versao_parser") or 1) < 3:
        return _todos_na(f"payload v{payload.get('versao_parser') or 1}, anterior ao validador")
    ref = payload.get("data_referencia")
    if session is None or not ref:
        return _todos_na("sem sessão de banco ou sem data de referência")

    from sqlmodel import select

    from ..models.extrato import ExtratoImportado

    try:
        ref_date = date.fromisoformat(str(ref))
    except ValueError:
        return _todos_na(f"data_referencia ilegível: {ref!r}")

    anterior_arquivado = session.exec(
        select(ExtratoImportado)
        .where(ExtratoImportado.data_referencia < ref_date)
        .order_by(ExtratoImportado.data_referencia.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    if anterior_arquivado is None:
        return _todos_na("nenhum mês anterior arquivado")

    try:
        payload_anterior = json.loads(anterior_arquivado.payload_json or "{}")
    except (TypeError, ValueError):
        return _todos_na("payload do mês anterior ilegível")

    atual_do_anterior = (payload_anterior.get("sumario") or {}).get("atual") or {}
    total_arquivado = atual_do_anterior.get("total") or {}
    anterior_deste = _sumario_bloco(payload, "anterior")
    total_deste = anterior_deste.get("total") or {}

    data_arquivada = atual_do_anterior.get("data") or anterior_arquivado.data_referencia.isoformat()
    data_deste = anterior_deste.get("data")
    if data_deste and data_arquivada and str(data_deste) != str(data_arquivada):
        return _todos_na(
            f"mês arquivado anterior termina em {data_arquivada}, mas este extrato compara "
            f"com {data_deste} — períodos não contíguos (pode haver mês faltando)"
        )

    checks = []
    for tipo, cid in (("bruto", "V7_ENCADEAMENTO_BRUTO"), ("liquido", "V7_ENCADEAMENTO_LIQ")):
        esperado = _num(total_arquivado.get(tipo))
        obtido = _num(total_deste.get(tipo))
        if esperado is None or obtido is None:
            checks.append(_na(cid, rotulos[cid],
                              "um dos lados não tem o total no Sumário (payload antigo?)"))
            continue
        dif = round(obtido - esperado, 2)
        sev = _severidade(dif)
        detalhe = f"vs mês arquivado de {data_arquivada}"
        if sev == "erro":
            sev = "aviso"      # máximo aviso, por contrato
            detalhe += " — série não encadeia: confira se há mês faltando ou substituído"
        checks.append(_check(cid, rotulos[cid], esperado=esperado, obtido=obtido,
                             severidade=sev, detalhe=detalhe))
    return checks


def anexar_validacao(extrato: ExtratoParsed, session=None) -> dict:
    """
    Único jeito sancionado de montar o payload bruto para arquivar: to_dict() + a chave
    `validacao` (IRMÃ de `checagem` — nunca dentro dela). Com `session`, inclui o V7.
    """
    payload = extrato.to_dict()
    resultado = validar_extrato(payload)
    if session is not None:
        resultado = _montar_resultado(list(resultado["checks"]) + validar_encadeamento(session, payload))
    payload["validacao"] = resultado
    return payload
