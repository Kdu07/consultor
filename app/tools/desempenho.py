"""
Motor de desempenho da carteira (docs/PLANO_HISTORICO.md, Bloco 3) — funções puras.

Entrada: os extratos arquivados (o payload de ExtratoImportado, já como dict), as regras de
classificação e, opcionalmente, CDI e IPCA por mês. Saída: a série mensal com rentabilidade,
as janelas acumuladas (mês, ano, 12 meses, desde o início) e a renda passiva. Sem banco e sem
rede: quem carrega os dados é desempenho_servico.py.

Rentabilidade do mês — Modified Dietz sobre o patrimônio oficial do extrato:

    V_ini = Total Bruto do Sumário no fim do mês anterior (inclui valores em trânsito)
    V_fim = Total Bruto do Sumário no fim do mês
    F     = aportes (+) e resgates (−) do razão da conta corrente, cada um na sua data
    w     = (data_fim − data do fluxo) / dias do período       (fluxo no fim do dia)
    r     = (V_fim − V_ini − ΣF) / (V_ini + Σ w·F)

Bruto e com trânsito de propósito: é comparável ao CDI (que é bruto) e é competência — o
provento a receber compensa, no mesmo mês, a queda do papel na data-ex.

O acumulado de uma janela encadeia os meses (TWR): Π(1 + r) − 1. Mês sem extrato, sem razão
(arquivo anterior à v2 do parser), sem base ou de período quebrado não entra — e a janela diz
que ficou parcial. Nunca se inventa o mês que falta.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any, Iterable, Optional, Sequence

from .btg_xlsx_parser import _norm
from .lancamentos import (
    ALUGUEL,
    NAO_CLASSIFICADO,
    PROVENTO,
    Regra,
    classificar_mes,
    fluxos_externos,
)

STATUS_CONSIDERADOS = ("ok", "provisorio")
JANELAS = ("mes", "ano", "12m", "inicio")

# Diferença entre o V_fim de um mês e o V_ini do seguinte que vira aviso: o BTG pode
# reapresentar o mês anterior; vale sempre o V_ini do próprio extrato.
LIMIAR_CONTINUIDADE = 1.00
# Acima disto (Σ|fluxos| / V_ini) o Dietz deixa de ser uma boa aproximação do TWR do mês.
LIMIAR_FLUXO_RELEVANTE = 0.10


# ---------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------

def _data(valor: Any) -> Optional[date]:
    if isinstance(valor, date):
        return valor
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def mes_de(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _fim_do_mes(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _mes_somado(mes: str, n: int) -> str:
    ano, m = int(mes[:4]), int(mes[5:7])
    total = ano * 12 + (m - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def meses_entre(primeiro: str, ultimo: str) -> list[str]:
    """Meses de `primeiro` a `ultimo`, inclusive ('YYYY-MM')."""
    out: list[str] = []
    atual = primeiro
    while atual <= ultimo:
        out.append(atual)
        atual = _mes_somado(atual, 1)
    return out


def _periodo_mensal(periodo_inicio: Optional[date], data_fim: Optional[date]) -> bool:
    """O extrato cobre exatamente um mês civil? (o BTG exporta períodos arbitrários)"""
    if data_fim is None or data_fim != _fim_do_mes(data_fim):
        return False
    if periodo_inicio is None:
        return True
    return periodo_inicio == data_fim.replace(day=1)


# ---------------------------------------------------------------------------
# Dietz
# ---------------------------------------------------------------------------

def dietz(
    v_ini: float,
    v_fim: float,
    fluxos: Iterable[tuple[Any, float]],
    data_ini: date,
    data_fim: date,
) -> tuple[Optional[float], float, float]:
    """
    (r, ganho, base). r é None quando a base não é positiva (ex.: conta aberta no mês).
    Fluxo sem data entra no meio do período; data fora do período é presa às pontas.
    """
    dias = max((data_fim - data_ini).days, 1)
    soma = 0.0
    ponderado = 0.0
    for quando, valor in fluxos:
        d = _data(quando)
        peso = 0.5 if d is None else min(max((data_fim - d).days / dias, 0.0), 1.0)
        soma += valor
        ponderado += peso * valor
    ganho = v_fim - v_ini - soma
    base = v_ini + ponderado
    if base <= 0:
        return None, ganho, base
    return ganho / base, ganho, base


# ---------------------------------------------------------------------------
# Um mês arquivado
# ---------------------------------------------------------------------------

def extrair_mes(
    data_referencia: Any,
    payload: dict,
    regras: Sequence[Regra] = (),
    fluxos_extras: Sequence[tuple[Any, float]] = (),
) -> dict:
    """
    Lê um extrato arquivado e devolve o mês calculado: patrimônio, fluxos externos,
    rentabilidade, status e proventos. `payload` é o dict do parser (bruto) ou, em
    arquivamentos antigos, o preview. `fluxos_extras` são aportes e resgates que não
    passam pelo razão — ativos trazidos ou levados de outra corretora (composicao.py).
    """
    ref = _data(data_referencia) or _data(payload.get("data_referencia"))
    sumario = payload.get("sumario") or {}
    meta = sumario.get("meta") or {}
    atual = sumario.get("atual") or {}
    anterior = sumario.get("anterior") or {}
    comparativo = payload.get("comparativo_mes_anterior") or {}

    v_fim = _num((atual.get("total") or {}).get("bruto"))
    v_ini = _num((anterior.get("total") or {}).get("bruto"))
    data_fim = _data(atual.get("data")) or ref
    data_ini = _data(anterior.get("data"))
    periodo_inicio = _data(meta.get("periodo_inicio"))
    # Arquivo sem Sumário (preview arquivado à mão): o comparativo tem os dois saldos.
    if v_fim is None:
        v_fim = _num(comparativo.get("saldo_bruto_atual"))
    if v_ini is None:
        v_ini = _num(comparativo.get("saldo_bruto_anterior"))
    if data_ini is None:
        data_ini = _data(comparativo.get("data_anterior"))
    if data_ini is None and periodo_inicio is not None:
        data_ini = periodo_inicio - timedelta(days=1)
    if data_ini is None and data_fim is not None:
        data_ini = data_fim.replace(day=1) - timedelta(days=1)

    posicoes = payload.get("posicoes") or []
    versao = int(payload.get("versao_parser") or 1)
    tem_razao = versao >= 2
    ref_iso = ref.isoformat() if ref else None
    classificados = (
        classificar_mes(ref_iso, payload.get("lancamentos_conta") or [], regras) if tem_razao else []
    )
    fluxos = fluxos_externos(classificados) + [(d, float(v)) for d, v in fluxos_extras]
    pendentes = [c for c in classificados if c["tipo"] == NAO_CLASSIFICADO]
    razao_ok = (
        ((payload.get("checagem") or {}).get("conta_corrente") or {}).get("ok") if tem_razao else None
    )

    mes: dict[str, Any] = {
        "mes": mes_de(data_fim or ref),
        "data_referencia": ref_iso,
        "data_ini": data_ini.isoformat() if data_ini else None,
        "data_fim": data_fim.isoformat() if data_fim else None,
        "versao_parser": versao,
        "patrimonio_ini": _r2(v_ini),
        "patrimonio_fim": _r2(v_fim),
        "patrimonio_posicoes_fim": _r2(sum(_num(p.get("valor_mercado")) or 0.0 for p in posicoes)),
        "variacao_saldo": _r2(v_fim - v_ini) if v_fim is not None and v_ini is not None else None,
        "aportes": _r2(sum(v for _, v in fluxos if v > 0)),
        "resgates": _r2(-sum(v for _, v in fluxos if v < 0)),
        "aportes_liquidos": _r2(sum(v for _, v in fluxos)),
        "nao_classificados": len(pendentes),
        "valor_nao_classificado": _r2(sum(abs(c["valor"]) for c in pendentes)),
        "razao_ok": razao_ok,
        "ganho": None,
        "rentabilidade_pct": None,
        "status": "ok",
        "motivos": [],
        "avisos": ["transferencia_de_ativos"] if fluxos_extras else [],
    }

    if not _periodo_mensal(periodo_inicio, data_fim):
        mes["status"] = "periodo_parcial"
    elif v_ini is None or v_fim is None or v_ini <= 0:
        mes["status"] = "sem_base"
    elif not tem_razao:
        mes["status"] = "sem_lancamentos"
    else:
        r, ganho, base = dietz(v_ini, v_fim, fluxos, data_ini, data_fim)
        if r is None:
            mes["status"] = "sem_base"
        else:
            mes["ganho"] = _r2(ganho)
            mes["rentabilidade_pct"] = _pct(r)
            if pendentes:
                mes["motivos"].append("nao_classificados")
            if razao_ok is False:
                mes["motivos"].append("razao_nao_fecha")
            elif razao_ok is None:
                mes["motivos"].append("razao_ausente")
            mes["status"] = "provisorio" if mes["motivos"] else "ok"
            movimentado = sum(abs(v) for _, v in fluxos)
            if v_ini and movimentado > LIMIAR_FLUXO_RELEVANTE * v_ini:
                mes["avisos"].append("fluxo_relevante")

    mes["proventos"] = proventos_do_mes(payload, classificados)
    return mes


def _num(valor: Any) -> Optional[float]:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _r2(valor: Optional[float]) -> Optional[float]:
    return None if valor is None else round(float(valor), 2)


def _pct(fracao: Optional[float]) -> Optional[float]:
    """Fração → pontos percentuais com 4 casas (0.012345 → 1.2345)."""
    return None if fracao is None else round(fracao * 100, 4)


# ---------------------------------------------------------------------------
# Proventos e renda passiva
# ---------------------------------------------------------------------------

def proventos_do_mes(payload: dict, classificados: Sequence[dict]) -> dict:
    """
    Renda do mês, líquida. Fonte principal: a movimentação de RV (`proventos`), que existe
    em todo arquivo, inclusive v1. O razão (v2) acrescenta o que a RV não mostra — cupom de
    Tesouro, aluguel de ações — sem contar duas vezes o provento que aparece nos dois.
    Amortização devolve capital: fica separada e não entra no yield.
    """
    itens = payload.get("proventos")
    if itens is None:
        itens = (payload.get("proventos_do_mes") or {}).get("itens") or []
    classe_por_ticker = {
        p.get("ticker"): p.get("classe") for p in payload.get("posicoes") or [] if p.get("ticker")
    }

    por_classe: dict[str, float] = {}
    por_ticker: dict[str, dict] = {}
    total = 0.0
    amortizacao = 0.0
    quantidade = 0
    for item in itens:
        valor = _num(item.get("valor_liquido"))
        if valor is None:
            valor = _num(item.get("valor_bruto")) or 0.0
        eh_amortizacao = (
            item["amortizacao"] if "amortizacao" in item
            else "amortizacao" in _norm(item.get("transacao"))
        )
        if eh_amortizacao:
            amortizacao += valor
            continue
        ticker = item.get("ticker")
        classe = item.get("classe") or classe_por_ticker.get(ticker) or "OUTRO"
        total += valor
        quantidade += 1
        por_classe[classe] = por_classe.get(classe, 0.0) + valor
        if ticker:
            acc = por_ticker.setdefault(ticker, {"ticker": ticker, "classe": classe, "total": 0.0, "pagamentos": 0})
            acc["total"] += valor
            acc["pagamentos"] += 1

    aluguel = 0.0
    for c in classificados:
        if c.get("tipo") == ALUGUEL and c["valor"] > 0:
            aluguel += c["valor"]
        elif c.get("tipo") == PROVENTO and c["valor"] > 0 and not _ja_contado(c, itens):
            classe = "TESOURO" if _parece_tesouro(c.get("descricao")) else "OUTRO"
            total += c["valor"]
            quantidade += 1
            por_classe[classe] = por_classe.get(classe, 0.0) + c["valor"]

    return {
        "total": _r2(total + aluguel),
        "proventos": _r2(total),
        "aluguel": _r2(aluguel),
        "amortizacao": _r2(amortizacao),
        "quantidade": quantidade,
        "por_classe": {k: _r2(v) for k, v in sorted(por_classe.items())},
        "por_ticker": [
            {**v, "total": _r2(v["total"])} for v in sorted(por_ticker.values(), key=lambda v: -v["total"])
        ],
    }


def _ja_contado(lancamento: dict, itens: Sequence[dict]) -> bool:
    """O crédito do razão é um provento que a movimentação de RV já trouxe?"""
    descricao = (lancamento.get("descricao") or "").upper()
    for item in itens:
        valor = _num(item.get("valor_liquido"))
        if valor is None or abs(valor - lancamento["valor"]) > 0.01:
            continue
        ticker = (item.get("ticker") or "").upper()
        if not ticker or ticker in descricao:
            return True
    return False


def _parece_tesouro(descricao: Optional[str]) -> bool:
    n = _norm(descricao)
    return any(m in n for m in ("tesouro", "ntn", "ltn", "lft", "cupom"))


# ---------------------------------------------------------------------------
# Série e janelas
# ---------------------------------------------------------------------------

def montar_serie(meses: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    """
    (série, períodos parciais). Um mês por linha, em ordem; o que falta entre o primeiro e o
    último arquivado vira 'lacuna'. Dois arquivos do mesmo mês (um parcial, um completo):
    vale o completo — o parcial fica de fora, listado à parte.
    """
    por_mes: dict[str, dict] = {}
    parciais: list[dict] = []
    for m in sorted(meses, key=lambda m: m.get("data_referencia") or ""):
        if m["status"] == "periodo_parcial":
            parciais.append(m)
            continue
        por_mes[m["mes"]] = m   # o mais recente do mês prevalece
    if not por_mes:
        return [], parciais

    serie: list[dict] = []
    anterior: Optional[dict] = None
    for mes in meses_entre(min(por_mes), max(por_mes)):
        m = por_mes.get(mes)
        if m is None:
            serie.append({"mes": mes, "status": "lacuna", "motivos": [], "avisos": []})
            anterior = None
            continue
        if (anterior is not None and anterior.get("patrimonio_fim") is not None
                and m.get("patrimonio_ini") is not None
                and abs(anterior["patrimonio_fim"] - m["patrimonio_ini"]) > LIMIAR_CONTINUIDADE):
            m["avisos"] = [*m["avisos"], "continuidade"]
        serie.append(m)
        anterior = m
    return serie, parciais


def aplicar_benchmarks(
    serie: Sequence[dict],
    cdi: dict[str, float],
    ipca: dict[str, float],
) -> None:
    """CDI, % do CDI, IPCA e retorno real em cada mês (no lugar)."""
    for m in serie:
        if m.get("status") == "lacuna":
            continue
        c = cdi.get(m["mes"])
        i = ipca.get(m["mes"])
        r = m.get("rentabilidade_pct")
        m["cdi_pct"] = c
        m["ipca_pct"] = i
        m["pct_do_cdi"] = round(r / c * 100, 2) if r is not None and c else None
        m["retorno_real_pct"] = (
            _pct((1 + r / 100) / (1 + i / 100) - 1) if r is not None and i is not None else None
        )


def janela(
    serie: Sequence[dict],
    tipo: str,
    cdi: Optional[dict[str, float]] = None,
    ipca: Optional[dict[str, float]] = None,
    mes: Optional[str] = None,
) -> Optional[dict]:
    """Acumulado de uma janela — ver JANELAS. None se não há nenhum mês arquivado."""
    cdi = cdi or {}
    ipca = ipca or {}
    arquivados = [m for m in serie if m.get("status") != "lacuna"]
    if not arquivados:
        return None
    ultimo = arquivados[-1]["mes"]
    por_mes = {m["mes"]: m for m in serie}

    if tipo == "mes":
        lista = [mes or ultimo]
    elif tipo == "ano":
        lista = meses_entre(f"{ultimo[:4]}-01", ultimo)
    elif tipo == "12m":
        lista = meses_entre(_mes_somado(ultimo, -11), ultimo)
    elif tipo == "inicio":
        primeiro = next((m["mes"] for m in serie if m.get("status") in STATUS_CONSIDERADOS), None)
        lista = meses_entre(primeiro, ultimo) if primeiro else []
    else:
        raise ValueError(f"janela desconhecida: {tipo}")

    considerados = [por_mes[m] for m in lista if por_mes.get(m, {}).get("status") in STATUS_CONSIDERADOS]
    faltantes = [m for m in lista if por_mes.get(m, {}).get("status") not in STATUS_CONSIDERADOS]

    resultado: dict[str, Any] = {
        "tipo": tipo,
        "de": lista[0] if lista else None,
        "ate": lista[-1] if lista else None,
        "meses": len(lista),
        "considerados": [m["mes"] for m in considerados],
        "faltantes": faltantes,
        "parcial": bool(faltantes),
        "provisorio": any(m["status"] == "provisorio" for m in considerados),
        "rentabilidade_pct": None,
        "ganho": None,
        "aportes_liquidos": None,
        "patrimonio_ini": None,
        "patrimonio_fim": None,
        "cdi_pct": None,
        "pct_do_cdi": None,
        "ipca_pct": None,
        "retorno_real_pct": None,
        "cdi_pendente": [],
        "ipca_pendente": [],
        "anualizado_pct": None,
    }
    if not considerados:
        return resultado

    fator = 1.0
    for m in considerados:
        fator *= 1 + m["rentabilidade_pct"] / 100
    r = fator - 1
    resultado.update({
        "rentabilidade_pct": _pct(r),
        "ganho": _r2(sum(m["ganho"] for m in considerados)),
        "aportes_liquidos": _r2(sum(m["aportes_liquidos"] for m in considerados)),
        "patrimonio_ini": considerados[0]["patrimonio_ini"],
        "patrimonio_fim": considerados[-1]["patrimonio_fim"],
    })
    if tipo == "inicio" and len(considerados) >= 12:
        resultado["anualizado_pct"] = _pct(fator ** (12 / len(considerados)) - 1)

    fator_cdi, cdi_pendente = _encadear(considerados, cdi)
    fator_ipca, ipca_pendente = _encadear(considerados, ipca)
    resultado["cdi_pendente"] = cdi_pendente
    resultado["ipca_pendente"] = ipca_pendente
    if not cdi_pendente:
        resultado["cdi_pct"] = _pct(fator_cdi - 1)
        if fator_cdi - 1 > 0:
            resultado["pct_do_cdi"] = round(r / (fator_cdi - 1) * 100, 2)
    if not ipca_pendente:
        resultado["ipca_pct"] = _pct(fator_ipca - 1)
        resultado["retorno_real_pct"] = _pct(fator / fator_ipca - 1)
    return resultado


def _encadear(meses: Sequence[dict], indice: dict[str, float]) -> tuple[float, list[str]]:
    fator = 1.0
    pendentes: list[str] = []
    for m in meses:
        valor = indice.get(m["mes"])
        if valor is None:
            pendentes.append(m["mes"])
        else:
            fator *= 1 + valor / 100
    return fator, pendentes


def periodo_entre(meses: Sequence[dict], de: date, ate: date) -> dict:
    """
    O que aconteceu entre dois fechamentos: os meses depois de `de` até `ate`, inclusive.
    Rentabilidade encadeada só sobre os meses calculáveis (como numa janela); proventos de
    todo mês arquivado, porque vêm da movimentação de RV e existem até nos arquivos v1.
    """
    serie, _ = montar_serie(meses)
    lista = [m for m in serie if mes_de(de) < m["mes"] <= mes_de(ate)]
    considerados = [m for m in lista if m.get("status") in STATUS_CONSIDERADOS]
    fator = 1.0
    for m in considerados:
        fator *= 1 + m["rentabilidade_pct"] / 100
    return {
        "meses": [m["mes"] for m in lista],
        "considerados": [m["mes"] for m in considerados],
        "faltantes": [m["mes"] for m in lista if m.get("status") not in STATUS_CONSIDERADOS],
        "provisorio": any(m["status"] == "provisorio" for m in considerados),
        "rentabilidade_pct": _pct(fator - 1) if considerados else None,
        "ganho": _r2(sum(m["ganho"] for m in considerados)) if considerados else None,
        "aportes_liquidos": _r2(sum(m["aportes_liquidos"] for m in considerados)) if considerados else None,
        "proventos": _r2(sum((m.get("proventos") or {}).get("total") or 0.0 for m in lista)),
    }


# ---------------------------------------------------------------------------
# Renda passiva acumulada
# ---------------------------------------------------------------------------

def renda_passiva(serie: Sequence[dict], posicoes_atuais: Sequence[dict]) -> dict:
    """
    Proventos por mês e dos últimos 12 meses, com yield sobre o patrimônio em posições do
    último fechamento e, por ativo, também sobre o custo.
    """
    arquivados = [m for m in serie if m.get("status") != "lacuna" and m.get("proventos")]
    por_mes = [{"mes": m["mes"], **{k: v for k, v in m["proventos"].items() if k != "por_ticker"}}
               for m in arquivados]
    if not arquivados:
        return {"por_mes": [], "ultimos_12m": None, "por_ativo_12m": []}

    ultimo = arquivados[-1]
    janela_12 = set(meses_entre(_mes_somado(ultimo["mes"], -11), ultimo["mes"]))
    no_ano = [m for m in arquivados if m["mes"] in janela_12]
    total_12 = sum(m["proventos"]["total"] or 0.0 for m in no_ano)
    base = ultimo.get("patrimonio_posicoes_fim") or 0.0

    por_ativo: dict[str, dict] = {}
    for m in no_ano:
        for t in m["proventos"]["por_ticker"]:
            acc = por_ativo.setdefault(t["ticker"], {
                "chave": f"B3:{t['ticker']}", "ticker": t["ticker"], "classe": t["classe"],
                "total": 0.0, "pagamentos": 0,
            })
            acc["total"] += t["total"]
            acc["pagamentos"] += t["pagamentos"]

    posicao_por_ticker = {p.get("ticker"): p for p in posicoes_atuais if p.get("ticker")}
    for acc in por_ativo.values():
        p = posicao_por_ticker.get(acc["ticker"]) or {}
        valor_atual = _num(p.get("valor_mercado"))
        custo = None
        if _num(p.get("preco_medio")) and _num(p.get("quantidade")):
            custo = _num(p["preco_medio"]) * _num(p["quantidade"])
        acc["total"] = _r2(acc["total"])
        acc["valor_atual"] = _r2(valor_atual)
        acc["yield_pct"] = round(acc["total"] / valor_atual * 100, 2) if valor_atual else None
        acc["yield_sobre_custo_pct"] = round(acc["total"] / custo * 100, 2) if custo else None

    return {
        "por_mes": por_mes,
        "ultimos_12m": {
            "total": _r2(total_12),
            "meses_com_dado": len(no_ano),
            "parcial": len(no_ano) < 12,
            "yield_pct": round(total_12 / base * 100, 2) if base else None,
        },
        "por_ativo_12m": sorted(por_ativo.values(), key=lambda a: -a["total"]),
    }


# ---------------------------------------------------------------------------
# Resumo completo (o que GET /desempenho devolve)
# ---------------------------------------------------------------------------

def resumo(
    meses: Sequence[dict],
    posicoes_atuais: Sequence[dict] = (),
    cdi: Optional[dict[str, float]] = None,
    ipca: Optional[dict[str, float]] = None,
) -> dict:
    serie, parciais = montar_serie(meses)
    if not serie:
        return {"vazio": True, "meses": [], "janelas": {}, "proventos": renda_passiva([], []),
                "pendencias": _pendencias([], parciais)}

    aplicar_benchmarks(serie, cdi or {}, ipca or {})
    arquivados = [m for m in serie if m.get("status") != "lacuna"]
    return {
        "vazio": False,
        "ultimo_fechamento": arquivados[-1].get("data_fim"),
        "meses": serie,
        "janelas": {t: janela(serie, t, cdi, ipca) for t in JANELAS},
        "proventos": renda_passiva(serie, posicoes_atuais),
        "pendencias": _pendencias(serie, parciais),
    }


def _pendencias(serie: Sequence[dict], parciais: Sequence[dict]) -> dict:
    return {
        "nao_classificados": sum(m.get("nao_classificados") or 0 for m in serie),
        "valor_nao_classificado": _r2(sum(m.get("valor_nao_classificado") or 0.0 for m in serie)),
        "meses_sem_lancamentos": [m["mes"] for m in serie if m.get("status") == "sem_lancamentos"],
        "meses_faltantes": [m["mes"] for m in serie if m.get("status") == "lacuna"],
        "meses_razao_nao_fecha": [m["mes"] for m in serie if "razao_nao_fecha" in (m.get("motivos") or [])],
        "periodos_parciais": [m.get("data_referencia") for m in parciais],
        "quebras_continuidade": _quebras_continuidade(serie),
    }


def _quebras_continuidade(serie: Sequence[dict]) -> list[str]:
    """
    Expõe o aviso 'continuidade' que montar_serie marca e ninguém mostrava: o fechamento
    de um mês não bate com a abertura do seguinte (mês faltando ou extrato substituído).
    Mesma caminhada de montar_serie — depois de lacuna não há com quem comparar.
    """
    quebras: list[str] = []
    anterior: Optional[dict] = None
    for m in serie:
        if m.get("status") == "lacuna":
            anterior = None
            continue
        if anterior is not None and "continuidade" in (m.get("avisos") or []):
            mensagem = f"O fechamento de {anterior['mes']} não bate com a abertura de {m['mes']}"
            if anterior.get("patrimonio_fim") is not None and m.get("patrimonio_ini") is not None:
                dif = round(m["patrimonio_ini"] - anterior["patrimonio_fim"], 2)
                mensagem += f" (diferença R$ {dif:,.2f})"
            quebras.append(mensagem)
        anterior = m
    return quebras
