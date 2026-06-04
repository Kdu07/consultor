"""
Tool ler_carteira — retorna posições ativas do SQLite com source/as_of.
Contrato: nunca lança exceção.
"""
import logging

from sqlmodel import Session, select

from ..database import engine
from ..models.posicao import Posicao
from .schemas import tool_error

logger = logging.getLogger(__name__)


async def tool_ler_carteira() -> dict:
    """
    Retorna todas as posições ativas.
    Nunca lança exceção.
    """
    try:
        with Session(engine) as session:
            posicoes = session.exec(
                select(Posicao).where(Posicao.ativo == True)
            ).all()

        if not posicoes:
            return {
                "posicoes": [],
                "total_posicoes": 0,
                "nota": "Carteira vazia. Use POST /posicoes para adicionar posições manualmente.",
            }

        items = []
        for p in posicoes:
            item: dict = {
                "id": p.id,
                "nome": p.nome,
                "classe": p.classe.value,
                "quantidade": p.quantidade,
                "source": p.source,
            }
            if p.ticker:
                item["ticker"] = p.ticker
            if p.preco_medio is not None:
                item["preco_medio"] = p.preco_medio
            if p.valor_mercado is not None:
                item["valor_mercado"] = p.valor_mercado
            if p.as_of:
                item["as_of"] = p.as_of.isoformat()
            if p.notas:
                item["notas"] = p.notas
            items.append(item)

        logger.info("ler_carteira: %d posicoes retornadas", len(items))
        return {
            "posicoes": items,
            "total_posicoes": len(items),
            "atualizado_em": max(
                (p.atualizado_em for p in posicoes), default=None
            ),
        }

    except Exception as e:
        logger.error("ler_carteira: erro: %s", e)
        return tool_error(f"Erro ao ler carteira: {e}")
