"""
Tool importar_extrato — lê o extrato XLSX do BTG enviado pela UI.

Guardrail 4 (PLANO §3, §10): esta tool APENAS retorna o preview. Nunca grava nada.
A gravação acontece numa tool separada (gravar_posicoes) somente após confirmação
explícita do usuário no turno seguinte.

O arquivo em si nunca chega ao modelo: o upload (POST /extrato/upload) parseia no
servidor e deixa o preview em app/tools/extrato_staging.py — ver docs/PLANO_XLSX.md §3.
"""
import logging

from . import extrato_staging
from .btg_xlsx_parser import ExtratoParsed
from .schemas import tool_error

logger = logging.getLogger(__name__)


def montar_preview(extrato: ExtratoParsed, arquivo: str) -> dict:
    """
    Converte o resultado do parser no preview consumido pelo agente e pela UI.
    Formato compatível com o argumento `posicoes` de gravar_posicoes.
    """
    posicoes = [p.to_dict() for p in extrato.posicoes]
    total = sum(p.valor_mercado for p in extrato.posicoes)

    por_classe: dict[str, dict] = {}
    for p in extrato.posicoes:
        acc = por_classe.setdefault(p.classe, {"qtd_ativos": 0, "valor_total": 0.0})
        acc["qtd_ativos"] += 1
        acc["valor_total"] += p.valor_mercado
    for acc in por_classe.values():
        acc["valor_total"] = round(acc["valor_total"], 2)

    preview: dict = {
        "posicoes": posicoes,
        "total_posicoes": len(posicoes),
        "total_valor_mercado": round(total, 2),
        "data_referencia": extrato.data_referencia,
        "resumo_por_classe": por_classe,
        "source": "extrato_btg_xlsx",
        "arquivo": arquivo,
        "checagem_totais": extrato.checagem,
        "proventos_do_mes": _resumo_proventos(extrato),
        "aluguel_ativo": extrato.aluguel,
        "valores_em_transito": _resumo_transito(extrato),
        "comparativo_mes_anterior": _comparativo(extrato),
    }
    if extrato.linhas_ignoradas:
        preview["linhas_ignoradas"] = extrato.linhas_ignoradas

    preview["aviso"] = _montar_aviso(extrato)
    return preview


def _resumo_proventos(extrato: ExtratoParsed) -> dict:
    total_liquido = sum(p.get("valor_liquido") or 0.0 for p in extrato.proventos)
    return {
        "total_liquido": round(total_liquido, 2),
        "quantidade": len(extrato.proventos),
        "itens": extrato.proventos,
    }


def _resumo_transito(extrato: ExtratoParsed) -> dict:
    total = sum(v["valor"] for v in extrato.valores_em_transito)
    return {
        "total": round(total, 2),
        "itens": extrato.valores_em_transito,
        "nota": "Ainda não liquidado — fora da carteira, não entra no caixa.",
    }


def _comparativo(extrato: ExtratoParsed) -> dict | None:
    """Saldo bruto do mês atual vs. mês anterior, direto da aba Sumario."""
    atual = (extrato.sumario or {}).get("atual") or {}
    anterior = (extrato.sumario or {}).get("anterior") or {}
    v_atual = (atual.get("total") or {}).get("bruto")
    v_anterior = (anterior.get("total") or {}).get("bruto")
    if v_atual is None or v_anterior is None:
        return None
    variacao = v_atual - v_anterior
    return {
        "data_atual": atual.get("data"),
        "data_anterior": anterior.get("data"),
        "saldo_bruto_atual": round(v_atual, 2),
        "saldo_bruto_anterior": round(v_anterior, 2),
        "variacao_reais": round(variacao, 2),
        "variacao_pct": round(variacao / v_anterior * 100, 2) if v_anterior else None,
        "nota": (
            "Variação de saldo do extrato — inclui aportes, retiradas e proventos, "
            "não é rentabilidade da carteira."
        ),
    }


def _montar_aviso(extrato: ExtratoParsed) -> str:
    partes = [
        "PREVIEW — nenhuma posição foi salva. "
        "Confirme com 'sim' para que eu grave estas posições na carteira."
    ]
    checagem = extrato.checagem or {}
    if not checagem.get("ok") and checagem.get("aviso"):
        partes.append("ATENÇÃO: " + checagem["aviso"])
    if extrato.linhas_ignoradas:
        partes.append(
            f"{len(extrato.linhas_ignoradas)} linha(s) do extrato não foram interpretadas — "
            "veja 'linhas_ignoradas' e confira se falta alguma posição."
        )
    return " ".join(partes)


async def tool_importar_extrato() -> dict:
    """
    Retorna o preview do extrato XLSX que o usuário enviou pela UI.
    NÃO salva nenhuma posição.
    """
    estado = extrato_staging.get()
    if not estado:
        return tool_error(
            "Nenhum extrato foi enviado ainda. Peça ao usuário para clicar em "
            "'Importar extrato BTG' na interface e selecionar o arquivo XLSX da conta "
            "de investimento."
        )

    preview = dict(estado["preview"])
    preview["recebido_em"] = estado["recebido_em"]

    logger.info(
        "importar_extrato: preview de '%s' devolvido (%d posicoes, ref=%s)",
        estado.get("arquivo"), preview.get("total_posicoes"), preview.get("data_referencia"),
    )
    return preview
