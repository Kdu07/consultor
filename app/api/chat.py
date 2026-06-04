"""
Endpoint de chat — conecta a UI ao loop do agente.
Sessões mantidas em memória (single-user local — sem necessidade de persistir).
"""
import logging
from fastapi import APIRouter
from pydantic import BaseModel

from ..agent.loop import AgentResult, run_agent

logger = logging.getLogger(__name__)
router = APIRouter()

# Histórico por sessão (em memória — reinicia com o servidor)
_sessions: dict[str, list[dict]] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    tokens_input: int = 0
    tokens_output: int = 0
    iterations: int = 0
    cost_usd: float = 0.0
    anomaly: bool = False


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    history = _sessions.get(req.session_id, [])

    result: AgentResult = await run_agent(req.message, history)

    _sessions[req.session_id] = result.history

    if result.anomaly:
        logger.warning(
            "chat [%s]: ANOMALIA — %d iters, %d in / %d out tokens",
            req.session_id, result.iterations, result.tokens_input, result.tokens_output,
        )
    else:
        logger.info(
            "chat [%s]: %d iters | %d in / %d out tokens | ~US$ %.4f",
            req.session_id, result.iterations, result.tokens_input, result.tokens_output, result.cost_usd,
        )

    return ChatResponse(
        reply=result.reply,
        session_id=req.session_id,
        tokens_input=result.tokens_input,
        tokens_output=result.tokens_output,
        iterations=result.iterations,
        cost_usd=result.cost_usd,
        anomaly=result.anomaly,
    )


@router.delete("/chat/{session_id}", status_code=204)
async def limpar_sessao(session_id: str):
    """Limpa o histórico de uma sessão (inicia nova conversa)."""
    _sessions.pop(session_id, None)
