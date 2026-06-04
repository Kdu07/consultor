from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    tokens_input: int = 0
    tokens_output: int = 0


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """
    Endpoint principal do agente consultor.
    Fase 1: loop do agente implementado aqui (stub por ora).
    """
    # Stub — será substituído pelo loop do agente na Fase 1
    return ChatResponse(
        reply="[Fase 0] Agente ainda não implementado. Loop do agente vem na Fase 1.",
        session_id=req.session_id,
    )
