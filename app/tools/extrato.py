"""
Tool importar_extrato — parseia texto colado do extrato PDF do BTG.

Guardrail 4 (PLANO §3, §10): esta tool APENAS retorna o preview.
Nunca grava nada. A gravação acontece numa tool separada (gravar_posicoes)
somente após confirmação explícita do usuário no turno seguinte.
"""
import logging

from .btg_parser import parse_btg_text
from .schemas import tool_error

logger = logging.getLogger(__name__)


async def tool_importar_extrato(texto: str) -> dict:
    """
    Parseia o texto copiado do extrato PDF do BTG.
    Retorna preview estruturado — NÃO salva nenhuma posição.
    """
    if not texto or len(texto.strip()) < 50:
        return tool_error(
            "Texto muito curto ou vazio. Cole o texto completo do extrato "
            "(Ctrl+A → Ctrl+C no leitor de PDF)."
        )
    try:
        positions = parse_btg_text(texto)
    except Exception as e:
        logger.error("importar_extrato: erro no parser: %s", e)
        return tool_error(f"Erro ao processar o texto do extrato: {e}")

    if not positions:
        return tool_error(
            "Nenhuma posição encontrada. Verifique se o texto contém as seções "
            "'Renda variável - Posição' ou 'Renda fixa - Posição - TESOURO DIRETO'."
        )

    posicoes = [p.to_dict() for p in positions]
    total = sum(p.valor_mercado for p in positions)
    as_of = positions[0].as_of if positions else None

    # Agrupa por classe para resumo
    por_classe: dict[str, dict] = {}
    for p in positions:
        c = p.classe
        if c not in por_classe:
            por_classe[c] = {"count": 0, "valor": 0.0}
        por_classe[c]["count"] += 1
        por_classe[c]["valor"] += p.valor_mercado

    logger.info(
        "importar_extrato: %d posicoes extraidas, total R$ %.2f, ref=%s",
        len(positions), total, as_of,
    )

    return {
        "posicoes": posicoes,
        "total_posicoes": len(posicoes),
        "total_valor_mercado": round(total, 2),
        "data_referencia": as_of,
        "resumo_por_classe": {
            k: {"qtd_ativos": v["count"], "valor_total": round(v["valor"], 2)}
            for k, v in por_classe.items()
        },
        "source": "extrato_btg",
        "aviso": (
            "PREVIEW — nenhuma posição foi salva. "
            "Confirme com 'sim' para que eu grave estas posições na carteira. "
            "Nota: RF privada (CDB/LCI/LCA) não aparece no texto do PDF — "
            "lance manualmente se necessário."
        ),
    }
