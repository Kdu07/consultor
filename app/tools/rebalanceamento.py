"""
Tool sugerir_rebalanceamento — filtra desvios e gera sugestões consultivas (PLANO §13 Fase 4).

Chama calcular_desvio internamente e filtra apenas itens onde fora_da_banda=True
e acima_do_piso=True. Estritamente consultivo — sem linguagem de execução (guardrail 2).
"""
import logging
from datetime import datetime, timezone

from .desvio import tool_calcular_desvio
from .schemas import tool_error

logger = logging.getLogger(__name__)


async def tool_sugerir_rebalanceamento() -> dict:
    """Gera sugestões de rebalanceamento. Nunca lança exceção."""
    try:
        return await _sugerir()
    except Exception as e:
        logger.error("sugerir_rebalanceamento: erro inesperado: %s", e)
        return tool_error(f"Erro interno ao gerar sugestões: {e}")


async def _sugerir() -> dict:
    desvio = await tool_calcular_desvio()
    if "error" in desvio:
        return desvio

    snapshot = desvio["snapshot"]
    por_classe = desvio.get("por_classe", [])
    por_ativo = desvio.get("por_ativo", [])

    # ------------------------------------------------------------------
    # Sugestões por classe
    # ------------------------------------------------------------------
    sugestoes_classe: list[dict] = []
    for c in por_classe:
        if not (c.get("fora_da_banda") and c.get("acima_do_piso")):
            continue
        desvio_pp = c["desvio_pp"]
        desvio_reais = c["desvio_reais"]
        acao = "REDUZIR" if desvio_reais > 0 else "AUMENTAR"
        sugestoes_classe.append({
            "nivel": "classe",
            "acao": acao,
            "classe": c["classe"],
            "ativo": None,
            "percentual_atual": c["percentual_atual"],
            "percentual_alvo": c["percentual_alvo"],
            "desvio_pp": desvio_pp,
            "desvio_reais": desvio_reais,
            "valor_a_mover": round(abs(desvio_reais), 2),
            "razao": (
                f"{c['classe']} está {abs(desvio_pp):.1f} p.p. "
                f"{'acima' if desvio_pp > 0 else 'abaixo'} do alvo "
                f"({c['percentual_atual']:.1f}% vs. alvo {c['percentual_alvo']:.1f}%)"
            ),
        })

    # ------------------------------------------------------------------
    # Sugestões por ativo (só quando alvos por ativo estão configurados)
    # ------------------------------------------------------------------
    sugestoes_ativo: list[dict] = []
    for a in por_ativo:
        if a.get("percentual_alvo") is None:
            continue
        if not (a.get("fora_da_banda") and a.get("acima_do_piso")):
            continue
        desvio_pp = a["desvio_pp"]
        desvio_reais = a["desvio_reais"]
        acao = "REDUZIR" if desvio_reais > 0 else "AUMENTAR"
        ident = a.get("ticker") or a.get("nome", "?")
        sugestoes_ativo.append({
            "nivel": "ativo",
            "acao": acao,
            "classe": a["classe"],
            "ativo": ident,
            "nome": a.get("nome"),
            "percentual_atual": a["percentual_atual"],
            "percentual_alvo": a["percentual_alvo"],
            "desvio_pp": desvio_pp,
            "desvio_reais": desvio_reais,
            "valor_a_mover": round(abs(desvio_reais), 2),
            "razao": (
                f"{ident} está {abs(desvio_pp):.1f} p.p. "
                f"{'acima' if desvio_pp > 0 else 'abaixo'} do alvo "
                f"({a['percentual_atual']:.1f}% vs. alvo {a['percentual_alvo']:.1f}%)"
            ),
        })

    # Ordena por valor_a_mover (maiores desvios primeiro)
    sugestoes_classe.sort(key=lambda x: x["valor_a_mover"], reverse=True)
    sugestoes_ativo.sort(key=lambda x: x["valor_a_mover"], reverse=True)

    total_sugestoes = len(sugestoes_classe) + len(sugestoes_ativo)
    status = "rebalanceamento_sugerido" if total_sugestoes > 0 else "dentro_da_banda"

    logger.info(
        "sugerir_rebalanceamento: %d sugestões (classe=%d, ativo=%d) | status=%s",
        total_sugestoes, len(sugestoes_classe), len(sugestoes_ativo), status,
    )

    return {
        "data_analise": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "valor_total": snapshot["valor_total"],
        "total_sugestoes": total_sugestoes,
        "sugestoes_por_classe": sugestoes_classe,
        "sugestoes_por_ativo": sugestoes_ativo,
        "snapshot": {
            "fracao_ao_vivo_pct": snapshot["fracao_ao_vivo_pct"],
            "fracao_extrato_pct": snapshot["fracao_extrato_pct"],
            "as_of_mais_antigo": snapshot["as_of_mais_antigo"],
            "data_ultima_atualizacao_posicoes": snapshot["data_ultima_atualizacao_posicoes"],
        },
        "nota_alvos_ativo": desvio.get("nota_alvos_ativo"),
    }
