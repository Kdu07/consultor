"""
GET /rebalanceamento — sugestões de rebalanceamento consultivas sem invocar o agente.
"""
from fastapi import APIRouter

from ..tools.rebalanceamento import tool_sugerir_rebalanceamento

router = APIRouter(tags=["rebalanceamento"])


@router.get("/rebalanceamento")
async def get_rebalanceamento():
    """Sugestões de rebalanceamento para a UI (sem passar pelo loop do agente)."""
    return await tool_sugerir_rebalanceamento()
