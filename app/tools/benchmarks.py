"""
CDI e IPCA mensais do BCB/SGS, com cache em IndicadorMensal (docs/PLANO_HISTORICO.md, Bloco 4).

CDI do mês M = Π(1 + taxa/100) − 1 sobre a série 12 (CDI diário, % a.d.), nas taxas datadas
em [fim(M−1), fim(M)). A taxa do dia t remunera de t até o dia útil seguinte, então essa é
exatamente a janela entre dois fechamentos de extrato. A série 4391 (CDI no mês) dá o mesmo
número arredondado em duas casas — jul/26: 1,2152% composto, 1,22 na 4391.

IPCA do mês M = série 433 na data 01/MM/AAAA. Sai por volta do dia 10 do mês seguinte.

Comportamento da SGS (conferido em 10/2026):
  - faixa ainda sem dados → HTTP 404 com JSON "Value(s) not found": não é erro, é "ainda não
    publicado";
  - série diária aceita no máximo 10 anos por consulta (HTTP 406) — a busca é fatiada;
  - às vezes a resposta é uma página HTML "Requisição inválida!": erro, nunca parsear.

Mesmo contrato de macro.py: nunca levanta. O que der errado vira status
  ok           — todo mês pedido tem CDI e IPCA
  parcial      — algum mês sem índice (não publicado ou falha), mas há dados
  indisponivel — o BCB falhou e nenhum mês pedido tem CDI
Sem rede no upload, no lote e no preview: só GET /desempenho e a tool chamam isto.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Sequence

import httpx
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..models.indicador_mensal import IndicadorMensal
from .desempenho import _fim_do_mes, mes_de

logger = logging.getLogger(__name__)

CDI = "CDI"
IPCA = "IPCA"
_SERIES = {CDI: (12, "sgs12"), IPCA: (433, "sgs433")}
_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados?formato=json&dataInicial={inicio}&dataFinal={fim}"
_TIMEOUT = 8.0
# Depois de uma busca que não completou os meses pedidos (falha ou mês não publicado), não
# insiste antes disto — a página do Histórico recarrega muito e o BCB não muda tão rápido.
_ESPERA = timedelta(minutes=30)
_MAX_DIAS_DIARIA = 365 * 9

# (série, meses que faltavam) → quando foi a última tentativa que não completou
_tentativas: dict[tuple[str, tuple[str, ...]], datetime] = {}


class ErroBCB(Exception):
    """A SGS respondeu algo que não é dado nem 'sem dados'."""


def limpar_estado() -> None:
    """Esquece as tentativas recentes (testes)."""
    _tentativas.clear()


def _novo_cliente() -> httpx.AsyncClient:
    """Ponto de troca nos testes (httpx.MockTransport)."""
    return httpx.AsyncClient(timeout=_TIMEOUT)


def _inicio_do_mes(mes: str) -> date:
    return date(int(mes[:4]), int(mes[5:7]), 1)


# ---------------------------------------------------------------------------
# SGS
# ---------------------------------------------------------------------------

async def _buscar_serie(
    cliente: httpx.AsyncClient, serie: int, inicio: date, fim: date
) -> list[tuple[date, float]]:
    """Valores da série no intervalo. [] quando a SGS diz que ainda não há dados."""
    url = _URL.format(serie=serie, inicio=inicio.strftime("%d/%m/%Y"), fim=fim.strftime("%d/%m/%Y"))
    try:
        resp = await cliente.get(url)
    except httpx.TransportError:
        # Timeout e conexão recusada são comuns e passageiros na SGS: uma segunda chance.
        resp = await cliente.get(url)
    try:
        dados = resp.json()
    except ValueError:
        raise ErroBCB(f"série {serie}: resposta não é JSON (HTTP {resp.status_code})")
    if resp.status_code == 404 and "not found" in resp.text.lower():
        return []
    if resp.status_code != 200 or not isinstance(dados, list):
        raise ErroBCB(f"série {serie}: HTTP {resp.status_code}")
    out: list[tuple[date, float]] = []
    for item in dados:
        try:
            out.append((datetime.strptime(item["data"], "%d/%m/%Y").date(), float(item["valor"])))
        except (KeyError, TypeError, ValueError):
            raise ErroBCB(f"série {serie}: item em formato inesperado")
    return out


async def _cdi_por_mes(cliente: httpx.AsyncClient, meses: Sequence[str], hoje: date) -> dict[str, float]:
    """CDI composto de cada mês pedido que já esteja completo."""
    inicio = _fim_do_mes(_inicio_do_mes(meses[0]) - timedelta(days=1))
    fim = min(_fim_do_mes(_inicio_do_mes(meses[-1])) + timedelta(days=10), hoje)
    diarias: list[tuple[date, float]] = []
    pedaco = inicio
    while pedaco <= fim:
        ate = min(pedaco + timedelta(days=_MAX_DIAS_DIARIA), fim)
        diarias.extend(await _buscar_serie(cliente, _SERIES[CDI][0], pedaco, ate))
        pedaco = ate + timedelta(days=1)
    if not diarias:
        return {}

    ultima = max(d for d, _ in diarias)
    out: dict[str, float] = {}
    for mes in meses:
        fim_mes = _fim_do_mes(_inicio_do_mes(mes))
        fim_anterior = _inicio_do_mes(mes) - timedelta(days=1)
        if ultima < fim_mes:
            continue   # a publicação é sequencial: sem taxa depois do fechamento, o mês não acabou
        fator = 1.0
        n = 0
        for d, taxa in diarias:
            if fim_anterior <= d < fim_mes:
                fator *= 1 + taxa / 100
                n += 1
        if n:
            out[mes] = round((fator - 1) * 100, 4)
    return out


async def _ipca_por_mes(cliente: httpx.AsyncClient, meses: Sequence[str]) -> dict[str, float]:
    valores = await _buscar_serie(
        cliente, _SERIES[IPCA][0], _inicio_do_mes(meses[0]), _inicio_do_mes(meses[-1])
    )
    pedidos = set(meses)
    return {mes_de(d): round(v, 4) for d, v in valores if mes_de(d) in pedidos}


# ---------------------------------------------------------------------------
# Cache + orquestração
# ---------------------------------------------------------------------------

def _cache(session: Session) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {CDI: {}, IPCA: {}}
    for ind in session.exec(select(IndicadorMensal)).all():
        out.setdefault(ind.serie, {})[ind.mes] = ind.valor_pct
    return out


def _pode_tentar(chave: tuple[str, tuple[str, ...]], agora: datetime) -> bool:
    ultima = _tentativas.get(chave)
    return ultima is None or agora - ultima >= _ESPERA


async def garantir_indicadores(
    session: Session,
    meses: Sequence[str],
    hoje: Optional[date] = None,
) -> dict:
    """
    CDI e IPCA dos meses pedidos ('YYYY-MM'). Lê o cache e só vai ao BCB pelos meses
    fechados que faltam; grava o que voltar completo. Nunca levanta.
    """
    hoje = hoje or date.today()
    agora = datetime.now(timezone.utc)
    corrente = mes_de(hoje)
    pedidos = sorted({m for m in meses if m < corrente})   # o mês corrente nunca está fechado
    cache = _cache(session)
    erros: list[str] = []

    buscas = {
        CDI: lambda cliente, faltam: _cdi_por_mes(cliente, faltam, hoje),
        IPCA: lambda cliente, faltam: _ipca_por_mes(cliente, faltam),
    }
    for serie, buscar in buscas.items():
        faltam = [m for m in pedidos if m not in cache[serie]]
        chave = (serie, tuple(faltam))
        if not faltam or not _pode_tentar(chave, agora):
            continue
        try:
            async with _novo_cliente() as cliente:
                novos = await buscar(cliente, faltam)
        except (ErroBCB, httpx.HTTPError) as e:
            # Timeout do httpx vem sem mensagem: o nome da exceção é o que diz o que houve.
            motivo = str(e) or e.__class__.__name__
            logger.warning("benchmarks: %s indisponivel (%s)", serie, motivo)
            erros.append(f"{serie}: {motivo}")
            _tentativas[chave] = agora
            continue
        for mes, valor in novos.items():
            session.add(IndicadorMensal(serie=serie, mes=mes, valor_pct=valor,
                                        fonte=_SERIES[serie][1], obtido_em=agora))
            cache[serie][mes] = valor
        _tentativas.pop(chave, None)
        restantes = tuple(m for m in faltam if m not in novos)
        if restantes:
            # O que sobrou ainda não foi publicado: a espera vale para esse conjunto, que é
            # o que a próxima chamada vai pedir.
            _tentativas[(serie, restantes)] = agora
    try:
        session.commit()
    except IntegrityError:
        # Outra requisição gravou os mesmos meses no meio do caminho: o cache já tem.
        session.rollback()

    cdi = {m: cache[CDI][m] for m in pedidos if m in cache[CDI]}
    ipca = {m: cache[IPCA][m] for m in pedidos if m in cache[IPCA]}
    if pedidos and not cdi and erros:
        status = "indisponivel"
    elif len(cdi) == len(pedidos) and len(ipca) == len(pedidos):
        status = "ok"
    else:
        status = "parcial"
    return {
        "cdi": cdi,
        "ipca": ipca,
        "status": status,
        "cdi_ate": max(cache[CDI]) if cache[CDI] else None,
        "ipca_ate": max(cache[IPCA]) if cache[IPCA] else None,
        "erro": "; ".join(erros) or None,
    }
