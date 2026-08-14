"""
Endpoint de chat — conecta a UI ao loop do agente.
Sessões mantidas em memória (single-user local — sem necessidade de persistir).

POST /chat        — turno completo, resposta única (mantido para scripts e testes).
POST /chat/stream — mesmo turno em SSE, token a token, com status das tools.
"""
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agent.loop import AgentResult, run_agent, run_agent_stream

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


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """
    Mesmo turno de /chat, entregue como Server-Sent Events.

    Cada linha `data:` é um JSON com um `type`:
      text        → {"type":"text","text":"..."}        delta a ser concatenado
      tools       → {"type":"tools","names":[...]}      tools rodando agora
      tools_done  → {"type":"tools_done","names":[...]}
      done        → {"type":"done","reply":...,"tokens_input":...,...}

    O histórico da sessão só é gravado no evento "done": se o cliente desistir no meio,
    o turno inteiro é descartado. É deliberado — abortar entre o `tool_use` e o seu
    `tool_result` deixaria um histórico que a API rejeita (todo tool_use exige o
    resultado correspondente), e a conversa quebraria da mensagem seguinte em diante.
    O preço é o agente esquecer um turno em que uma tool já escreveu no banco; como
    toda leitura passa por `ler_carteira`, ele se reorienta sozinho no turno seguinte.
    """
    history = _sessions.get(req.session_id, [])

    async def eventos() -> AsyncIterator[str]:
        async for ev in run_agent_stream(req.message, history):
            if ev["type"] != "done":
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                continue

            result: AgentResult = ev["result"]
            _sessions[req.session_id] = result.history

            if result.anomaly:
                logger.warning(
                    "chat/stream [%s]: ANOMALIA — %d iters, %d in / %d out tokens",
                    req.session_id, result.iterations, result.tokens_input, result.tokens_output,
                )
            else:
                logger.info(
                    "chat/stream [%s]: %d iters | %d in / %d out tokens | ~US$ %.4f",
                    req.session_id, result.iterations, result.tokens_input,
                    result.tokens_output, result.cost_usd,
                )

            payload = {
                "type": "done",
                "reply": result.reply,
                "session_id": req.session_id,
                "tokens_input": result.tokens_input,
                "tokens_output": result.tokens_output,
                "iterations": result.iterations,
                "cost_usd": result.cost_usd,
                "anomaly": result.anomaly,
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        eventos(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/chat/{session_id}", status_code=204)
async def limpar_sessao(session_id: str):
    """Limpa o histórico de uma sessão (inicia nova conversa)."""
    _sessions.pop(session_id, None)
