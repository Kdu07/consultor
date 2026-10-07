"""
Desempenho da carteira — orquestração (docs/PLANO_HISTORICO.md, Blocos 3, 4, 6 e 9).

Carrega os extratos arquivados e as regras do dono, chama os motores puros (desempenho.py,
composicao.py) e, quando disponíveis, CDI e IPCA (benchmarks.py). É daqui que saem
GET /desempenho*, os CSVs e a tool desempenho_carteira.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import date
from typing import Any, Optional, Sequence

from sqlmodel import Session, select

from .. import database
from ..models.extrato import ExtratoImportado
from .benchmarks import garantir_indicadores
from .composicao import acumular, composicao_mes, historico_do_papel, transferencias_de_ativos
from .desempenho import _mes_somado, extrair_mes, janela, meses_entre, resumo
from .lancamentos import Regra
from .regras_lancamento import carregar_regras
from .schemas import tool_error

logger = logging.getLogger(__name__)

FONTE = "extratos BTG arquivados; CDI BCB/SGS 12 (diário composto); IPCA BCB/SGS 433"
JANELAS_COMPOSICAO = ("mes", "ano", "12m", "inicio")


def carregar_meses(session: Session) -> list[dict]:
    """[{data_referencia, payload}] em ordem de data. Payload ilegível é pulado (e logado)."""
    registros = session.exec(
        select(ExtratoImportado).order_by(ExtratoImportado.data_referencia)
    ).all()
    out: list[dict] = []
    for r in registros:
        try:
            payload = json.loads(r.payload_json)
        except json.JSONDecodeError:
            logger.error("desempenho: payload ilegivel no extrato id=%s — mes ignorado", r.id)
            continue
        out.append({"data_referencia": r.data_referencia.isoformat(), "payload": payload})
    return out


def _indice_mensal(meses: Sequence[dict]) -> dict[str, int]:
    """'AAAA-MM' → posição do arquivo do mês completo (o mais recente vence, como na série)."""
    return {m["mes"]: i for i, m in enumerate(meses) if m["status"] != "periodo_parcial"}


def _datas(mes: dict) -> Optional[tuple[date, date]]:
    if not mes.get("data_ini") or not mes.get("data_fim"):
        return None
    return date.fromisoformat(mes["data_ini"]), date.fromisoformat(mes["data_fim"])


def _calcular(session: Session) -> tuple[list[dict], list[dict], list[Regra]]:
    """
    (arquivos, meses calculados, regras). Ativo trazido ou levado de outra corretora (regra
    ativo_mes do dono) entra como aporte/resgate no total — e o valor dele sai da comparação
    com o fechamento anterior, por isso o mês é recalculado com esse fluxo a mais.
    """
    regras = carregar_regras(session)
    arquivos = carregar_meses(session)
    meses = [extrair_mes(a["data_referencia"], a["payload"], regras) for a in arquivos]
    if any(r.escopo == "ativo_mes" for r in regras):
        indice = _indice_mensal(meses)
        for mes, i in indice.items():
            j = indice.get(_mes_somado(mes, -1))
            datas = _datas(meses[i])
            if j is None or datas is None:
                continue
            extras = transferencias_de_ativos(
                arquivos[i]["data_referencia"], arquivos[i]["payload"], arquivos[j]["payload"],
                *datas, regras,
            )
            if extras:
                meses[i] = extrair_mes(
                    arquivos[i]["data_referencia"], arquivos[i]["payload"], regras, fluxos_extras=extras
                )
    return arquivos, meses, regras


def meses_calculados(session: Session) -> tuple[list[dict], list[dict]]:
    """(meses calculados, posições do arquivo mais recente)."""
    arquivos, meses, _ = _calcular(session)
    posicoes = (arquivos[-1]["payload"].get("posicoes") or []) if arquivos else []
    return meses, posicoes


def calcular_desempenho(
    session: Session,
    cdi: Optional[dict[str, float]] = None,
    ipca: Optional[dict[str, float]] = None,
) -> dict:
    """Desempenho com os benchmarks que o chamador já tiver (sem rede)."""
    meses, posicoes = meses_calculados(session)
    return resumo(meses, posicoes, cdi=cdi, ipca=ipca)


async def desempenho_completo(session: Session, hoje: Optional[date] = None) -> dict:
    """
    Desempenho com CDI e IPCA. Os índices saem do cache e, para meses fechados que ainda
    faltam, do BCB — que pode falhar sem derrubar nada: `benchmarks.status` diz o que houve.
    """
    meses, posicoes = meses_calculados(session)
    arquivados = [m["mes"] for m in meses if m["status"] != "periodo_parcial"]
    indicadores = await garantir_indicadores(session, arquivados, hoje=hoje)
    dados = resumo(meses, posicoes, cdi=indicadores["cdi"], ipca=indicadores["ipca"])
    dados["benchmarks"] = {
        k: indicadores[k] for k in ("status", "cdi_ate", "ipca_ate", "erro")
    }
    return dados


# ---------------------------------------------------------------------------
# Composição por classe e por ativo (Bloco 9)
# ---------------------------------------------------------------------------

def composicoes_por_mes(
    arquivos: Sequence[dict], meses: Sequence[dict], regras: Sequence[Regra]
) -> dict[str, dict]:
    """{'AAAA-MM': composição} de cada mês completo arquivado, com o arquivo do mês anterior."""
    indice = _indice_mensal(meses)
    out: dict[str, dict] = {}
    for mes, i in sorted(indice.items()):
        datas = _datas(meses[i])
        if datas is None:
            continue
        j = indice.get(_mes_somado(mes, -1))
        out[mes] = composicao_mes(
            meses[i]["data_referencia"], arquivos[i]["payload"],
            arquivos[j]["payload"] if j is not None else None,
            *datas, regras,
            ganho_total=meses[i].get("ganho"), v_ini_total=meses[i].get("patrimonio_ini"),
        )
    return out


def meses_da_janela(disponiveis: Sequence[str], tipo: str, mes: Optional[str] = None) -> list[str]:
    """
    Meses de uma janela contada a partir do último mês com extrato. Aqui 'inicio' é o
    primeiro extrato arquivado — a composição de um papel não depende do razão da conta.
    """
    if tipo not in JANELAS_COMPOSICAO:
        raise ValueError(f"janela desconhecida: {tipo}")
    ultimo = disponiveis[-1]
    if tipo == "mes":
        return [mes or ultimo]
    if tipo == "ano":
        return meses_entre(f"{ultimo[:4]}-01", ultimo)
    if tipo == "12m":
        return meses_entre(_mes_somado(ultimo, -11), ultimo)
    return meses_entre(disponiveis[0], ultimo)


def _composicoes_da_janela(
    session: Session, tipo: str, mes: Optional[str] = None
) -> tuple[list[str], list[dict]]:
    arquivos, meses, regras = _calcular(session)
    todas = composicoes_por_mes(arquivos, meses, regras)
    if not todas:
        return [], []
    lista = meses_da_janela(sorted(todas), tipo, mes)
    return lista, [todas[m] for m in lista if m in todas]


def composicao_janela(session: Session, tipo: str = "12m", mes: Optional[str] = None) -> dict:
    """Classes, ativos, caixa e conferência acumulados na janela — o que GET /desempenho/composicao devolve."""
    lista, escolhidas = _composicoes_da_janela(session, tipo, mes)
    if not escolhidas:
        return {"vazio": True, "janela": {"tipo": tipo, "de": lista[0] if lista else None,
                                          "ate": lista[-1] if lista else None}}
    com_extrato = {c["mes"] for c in escolhidas}
    primeiro = escolhidas[0]["mes"]
    return {
        "vazio": False,
        "janela": {
            "tipo": tipo,
            "de": lista[0],
            "ate": lista[-1],
            "meses": len(lista),
            # Buraco entre extratos; antes do primeiro é só o começo do histórico
            "lacunas": [m for m in lista if m >= primeiro and m not in com_extrato],
            "sem_mes_anterior": [c["mes"] for c in escolhidas if "sem_mes_anterior" in c["avisos"]],
        },
        **acumular(escolhidas),
    }


def historico_do_ativo(session: Session, chave: str, tipo: str = "inicio") -> Optional[dict]:
    lista, escolhidas = _composicoes_da_janela(session, tipo)
    if not escolhidas:
        return None
    dados = historico_do_papel(escolhidas, chave)
    if dados is None:
        return None
    return {"chave": chave, "janela": {"tipo": tipo, "de": lista[0], "ate": lista[-1]}, **dados}


# ---------------------------------------------------------------------------
# Exportação CSV — Excel em português: ';', vírgula decimal, BOM UTF-8
# ---------------------------------------------------------------------------

def _br(valor: Optional[float], casas: int = 2) -> str:
    return "" if valor is None else f"{valor:.{casas}f}".replace(".", ",")


def _quantidade_br(valor: Optional[float]) -> str:
    if valor is None:
        return ""
    return f"{valor:.6f}".rstrip("0").rstrip(".").replace(".", ",")


def _csv(cabecalho: Sequence[str], linhas: Sequence[Sequence[Any]]) -> str:
    buf = io.StringIO()
    escritor = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    escritor.writerow(cabecalho)
    escritor.writerows(linhas)
    return "﻿" + buf.getvalue()


async def csv_mensal(session: Session, tipo: str = "inicio") -> str:
    """Uma linha por mês da janela, com CDI e IPCA — a tabela 'Mês a mês' da tela."""
    dados = await desempenho_completo(session)
    serie = dados.get("meses") or []
    arquivados = [m["mes"] for m in serie if m.get("status") != "lacuna"]
    janela_meses = set(meses_da_janela(arquivados, tipo)) if arquivados else set()
    linhas = [
        [
            m["mes"], m.get("status"),
            _br(m.get("patrimonio_ini")), _br(m.get("patrimonio_fim")),
            _br(m.get("aportes")), _br(m.get("resgates")), _br(m.get("aportes_liquidos")),
            _br(m.get("ganho")), _br(m.get("rentabilidade_pct"), 4),
            _br(m.get("cdi_pct"), 4), _br(m.get("pct_do_cdi")),
            _br(m.get("ipca_pct"), 4), _br(m.get("retorno_real_pct"), 4),
            _br((m.get("proventos") or {}).get("total")),
        ]
        for m in serie if m["mes"] in janela_meses
    ]
    return _csv(
        ["mês", "status", "patrimônio início", "patrimônio fim", "aportes", "resgates",
         "aportes líquidos", "ganho", "rentabilidade %", "CDI %", "% do CDI", "IPCA %",
         "retorno real %", "proventos"],
        linhas,
    )


def csv_ativos(session: Session, tipo: str = "inicio") -> str:
    """Uma linha por mês e papel da janela — pronta para tabela dinâmica."""
    _, escolhidas = _composicoes_da_janela(session, tipo)
    linhas = [
        [
            comp["mes"], a["classe"], a.get("ticker") or "", a.get("nome") or "", a["chave"],
            _quantidade_br(a["quantidade_ini"]), _quantidade_br(a["quantidade_fim"]),
            _br(a["preco_ini"]), _br(a["preco_fim"]), _br(a["valor_ini"]), _br(a["valor_fim"]),
            _br(a["compras"]), _br(a["vendas"]), _br(a["renda"]), _br(a["resultado"]),
            _br(a["rentabilidade_pct"], 4), a["status"],
        ]
        for comp in escolhidas for a in comp["ativos"]
    ]
    return _csv(
        ["mês", "classe", "ticker", "nome", "chave", "quantidade início", "quantidade fim",
         "preço início", "preço fim", "valor início", "valor fim", "compras", "vendas", "renda",
         "resultado", "rentabilidade %", "status"],
        linhas,
    )


# ---------------------------------------------------------------------------
# Tool desempenho_carteira (Bloco 6)
# ---------------------------------------------------------------------------

PERIODOS = ("mes", "ano", "12m", "inicio")
NIVEIS = ("carteira", "classe", "ativo")
_MAX_LINHAS = 36
_MAX_ATIVOS = 10

_MOTIVO_FALTANTE = {
    "lacuna": "sem extrato arquivado",
    "sem_lancamentos": "arquivo antigo, sem o razão da conta — reenvie o XLSX pela tela Histórico",
    "sem_base": "sem patrimônio de início (primeiro mês da conta)",
    None: "sem extrato arquivado",
}


def _mes_br(mes: str) -> str:
    nomes = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
    return f"{nomes[int(mes[5:7]) - 1]}/{mes[2:4]}"


def _pct2(valor: Optional[float]) -> Optional[float]:
    return None if valor is None else round(valor, 2)


def _faixas(meses: Sequence[str]) -> str:
    """['2025-08', ..., '2026-05', '2026-07'] → 'ago/25–mai/26, jul/26'."""
    faixas: list[list[str]] = []
    for m in meses:
        if faixas and _mes_somado(faixas[-1][-1], 1) == m:
            faixas[-1].append(m)
        else:
            faixas.append([m])
    return ", ".join(
        _mes_br(f[0]) if len(f) == 1 else f"{_mes_br(f[0])}–{_mes_br(f[-1])}" for f in faixas
    )


def _composicao_para_tool(comp: dict, nivel: str, avisos: list[str]) -> dict:
    """Classes (e, em nivel='ativo', os 10 papéis de maior |resultado|) em formato colunar."""
    j = comp["janela"]
    out: dict[str, Any] = {
        "composicao_periodo": f"{j['de']} a {j['ate']}",
        "classes_colunas": ["classe", "valor_fim_rs", "peso_pct", "resultado_rs", "rent_pct", "status"],
        "classes": [
            [c["classe"], c["valor_fim"], c["peso_fim_pct"], c["resultado"],
             _pct2(c["rentabilidade_pct"]), c["status"]]
            for c in comp["classes"]
        ],
    }
    if nivel == "ativo":
        ativos = comp["ativos"]
        out["ativos_colunas"] = ["ativo", "classe", "valor_fim_rs", "resultado_rs", "rent_pct", "renda_rs", "status"]
        out["ativos"] = [
            [a.get("ticker") or a["chave"], a["classe"], a["valor_fim"], a["resultado"],
             _pct2(a["rentabilidade_pct"]), a["renda"], a["status"]]
            for a in ativos[:_MAX_ATIVOS]
        ]
        if len(ativos) > _MAX_ATIVOS:
            out["ativos_omitidos"] = len(ativos) - _MAX_ATIVOS
    out["nota_composicao"] = (
        "Resultado = valorização + renda − compras + vendas. % do ativo pelo preço unitário; "
        "da classe, Dietz. 'parcial' = mês sem número; 'estimado' = resgate sem valor no razão."
    )

    if comp["pendencias"]:
        papeis = sorted({f"{p.get('ticker') or p['chave']} ({_mes_br(p['mes'])})" for p in comp["pendencias"]})
        avisos.append(
            f"Quantidade mudou sem compra ou venda em {', '.join(papeis)}: esse resultado fica "
            "de fora até o usuário dizer o que houve (tela Histórico › Desempenho)."
        )
    if "residuo_alto" in comp["avisos"]:
        avisos.append("Em algum mês a soma por papel não fecha com o total: composição aproximada.")
    if j.get("sem_mes_anterior"):
        avisos.append(
            f"Sem o extrato do mês anterior a {', '.join(_mes_br(m) for m in j['sem_mes_anterior'])}: "
            "papéis que já existiam ficam sem número nesse mês."
        )
    return out


async def tool_desempenho_carteira(
    periodo: str = "12m",
    nivel: str = "carteira",
    mes: Optional[str] = None,
) -> dict:
    """
    Rentabilidade da carteira descontados aportes e resgates, contra CDI e IPCA do mesmo
    período, com a renda passiva e a série mensal. Nunca levanta: erro vira tool_error.
    """
    if periodo not in PERIODOS:
        return tool_error(f"periodo deve ser um de {', '.join(PERIODOS)}.")
    if nivel not in NIVEIS:
        return tool_error(f"nivel deve ser um de {', '.join(NIVEIS)}.")
    if mes is not None and (periodo != "mes" or not re.fullmatch(r"\d{4}-\d{2}", mes)):
        return tool_error("mes só vale com periodo='mes', no formato AAAA-MM.")

    try:
        with Session(database.engine) as session:
            dados = await desempenho_completo(session)
    except Exception as e:  # noqa: BLE001 — contrato das tools: nunca levantar
        logger.error("desempenho_carteira: falha ao calcular: %s", e)
        return tool_error(f"Não consegui calcular o desempenho: {e}")

    if dados.get("vazio"):
        return tool_error(
            "Nenhum extrato arquivado ainda — sem histórico não há rentabilidade. O usuário "
            "pode importar o extrato do mês pelo chat ou enviar os meses antigos de uma vez "
            "na tela Histórico › Extratos."
        )

    serie = dados["meses"]
    por_mes = {m["mes"]: m for m in serie}
    if mes:
        cdi = {m["mes"]: m["cdi_pct"] for m in serie if m.get("cdi_pct") is not None}
        ipca = {m["mes"]: m["ipca_pct"] for m in serie if m.get("ipca_pct") is not None}
        j = janela(serie, "mes", cdi, ipca, mes=mes)
    else:
        j = dados["janelas"][periodo]

    meses_janela = meses_entre(j["de"], j["ate"]) if j["de"] else []
    proventos = sum(
        ((por_mes.get(m) or {}).get("proventos") or {}).get("total") or 0.0 for m in meses_janela
    )

    avisos: list[str] = []
    if j["faltantes"]:
        por_motivo: dict[str, list[str]] = {}
        for m in j["faltantes"]:
            motivo = _MOTIVO_FALTANTE.get((por_mes.get(m) or {}).get("status"), "sem rentabilidade")
            por_motivo.setdefault(motivo, []).append(m)
        detalhes = "; ".join(f"{_faixas(meses)} ({motivo})" for motivo, meses in por_motivo.items())
        avisos.append(
            f"Acumulado de {len(j['considerados'])} de {j['meses']} meses. Fora da conta: {detalhes}."
        )
    provisorios = [m for m in j["considerados"] if por_mes[m]["status"] == "provisorio"]
    if provisorios:
        avisos.append(
            "Provisório: há lançamentos da conta sem classificação (ou razão que não fecha) em "
            f"{', '.join(_mes_br(m) for m in provisorios)}. O número muda se algum deles for "
            "aporte ou resgate — o usuário classifica na tela Histórico › Extratos."
        )
    if j["ipca_pendente"]:
        avisos.append(
            f"IPCA de {', '.join(_mes_br(m) for m in j['ipca_pendente'])} ainda não disponível "
            "(o IBGE publica por volta do dia 10) — retorno real não calculado."
        )
    if j["cdi_pendente"]:
        avisos.append(f"CDI de {', '.join(_mes_br(m) for m in j['cdi_pendente'])} indisponível.")
    if (dados.get("benchmarks") or {}).get("status") == "indisponivel":
        avisos.append("BCB fora do ar agora: sem comparação com CDI e IPCA.")
    for m in j["considerados"]:
        if "fluxo_relevante" in por_mes[m].get("avisos", []):
            avisos.append(
                f"Em {_mes_br(m)}, aportes/resgates acima de 10% do patrimônio: a rentabilidade "
                "do mês é aproximada (Modified Dietz)."
            )
        if "transferencia_de_ativos" in por_mes[m].get("avisos", []):
            avisos.append(
                f"Em {_mes_br(m)}, ativos trazidos ou levados de outra corretora contam como "
                "aporte ou resgate."
            )

    composicao: dict[str, Any] = {}
    if nivel != "carteira":
        try:
            with Session(database.engine) as session:
                comp = composicao_janela(session, periodo, mes)
            if not comp.get("vazio"):
                composicao = _composicao_para_tool(comp, nivel, avisos)
        except Exception as e:  # noqa: BLE001 — sem composição, o total ainda serve
            logger.error("desempenho_carteira: falha na composição: %s", e)
            avisos.append("Composição por classe e ativo indisponível agora; o total está certo.")

    linhas = []
    for m in meses_janela[-_MAX_LINHAS:]:
        info = por_mes.get(m) or {}
        if info.get("status", "lacuna") == "lacuna":
            continue            # mês sem extrato: já está em periodo.faltantes
        linhas.append([
            m,
            info.get("rentabilidade_pct"),
            info.get("cdi_pct"),
            info.get("aportes_liquidos"),
            (info.get("proventos") or {}).get("total"),
            info.get("status") or "lacuna",
        ])

    saida: dict[str, Any] = {
        "source": FONTE,
        "as_of": dados.get("ultimo_fechamento"),
        "periodo": {
            "tipo": j["tipo"],
            "de": j["de"],
            "ate": j["ate"],
            "meses": j["meses"],
            "considerados": len(j["considerados"]),
            "faltantes": j["faltantes"],
        },
        "rentabilidade_pct": j["rentabilidade_pct"],
        "ganho_rs": j["ganho"],
        "aportes_liquidos_rs": j["aportes_liquidos"],
        "patrimonio_inicio_rs": j["patrimonio_ini"],
        "patrimonio_fim_rs": j["patrimonio_fim"],
        "cdi_pct": j["cdi_pct"],
        "pct_do_cdi": j["pct_do_cdi"],
        "ipca_pct": j["ipca_pct"],
        "retorno_real_pct": j["retorno_real_pct"],
        "anualizado_pct": j["anualizado_pct"],
        "proventos_rs": round(proventos, 2),
        "status": "provisorio" if j["provisorio"] else ("parcial" if j["parcial"] else "ok"),
        "avisos": avisos,
        "mensal_colunas": ["mes", "rent_pct", "cdi_pct", "aportes_liquidos_rs", "proventos_rs", "status"],
        "mensal": linhas,
        "nota": (
            "Rentabilidade bruta (antes de IR), Modified Dietz por mês sobre o patrimônio do "
            "extrato, encadeada no período; CDI e IPCA dos mesmos meses."
        ),
        **composicao,
    }
    return {k: v for k, v in saida.items() if v is not None and v != []}
