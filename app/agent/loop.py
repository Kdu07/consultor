"""
Loop do agente consultor (PLANO §3).

Invariantes:
  - MAX_ITERS ≈ 6; estourou → degrada com elegância e loga como anomalia.
  - Tools NUNCA lançam exceção para dentro do loop (contrato de app/tools/).
  - Tools independentes no mesmo turno rodam em paralelo (asyncio.gather).
  - Logging de tokens por iteração E por conversa.
  - Sem prompt caching (decisão deliberada — PLANO §5).
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic

from ..config import get_settings
from ..tools.ativo import tool_dados_ativo
from ..tools.carteira import tool_ler_carteira
from ..tools.macro import tool_contexto_macro
from ..tools.schemas import TOOL_DEFINITIONS, to_tool_content
from .system_prompt import build_system_prompt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dispatch de tools
# ---------------------------------------------------------------------------

_TOOL_DISPATCH: dict[str, Any] = {
    "ler_carteira": lambda _inputs: tool_ler_carteira(),
    "dados_ativo": lambda inputs: tool_dados_ativo(inputs["ticker"]),
    "contexto_macro": lambda _inputs: tool_contexto_macro(),
}


async def _dispatch(name: str, inputs: dict) -> dict:
    """Executa uma tool pelo nome. Nunca lança exceção — retorna {"error":...} em falha."""
    handler = _TOOL_DISPATCH.get(name)
    if handler is None:
        logger.warning("tool desconhecida: '%s'", name)
        return {"error": f"Tool '{name}' não existe."}
    try:
        return await handler(inputs)
    except Exception as e:
        logger.error("dispatch '%s': exceção inesperada: %s", name, e)
        return {"error": f"Falha interna na tool '{name}': {e}"}


# ---------------------------------------------------------------------------
# Resultado do loop
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    reply: str
    history: list[dict]
    tokens_input: int = 0
    tokens_output: int = 0
    iterations: int = 0
    cost_usd: float = 0.0
    anomaly: bool = False          # True se MAX_ITERS estourado ou stop_reason inesperado


# Preços Sonnet 4.6 por milhão de tokens (confirmar em console.anthropic.com)
_PRICE_IN_PER_M  = 3.0   # USD por 1M tokens de entrada
_PRICE_OUT_PER_M = 15.0  # USD por 1M tokens de saída


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

async def run_agent(message: str, history: list[dict]) -> AgentResult:
    """
    Executa uma rodada do agente:
      1. Adiciona a mensagem do usuário ao histórico.
      2. Loop até end_turn ou MAX_ITERS.
      3. Retorna AgentResult com a resposta e o histórico atualizado.

    O histórico é gerenciado pelo chamador (mantido por sessão).
    """
    settings = get_settings()

    if not settings.anthropic_api_key:
        return AgentResult(
            reply="Chave ANTHROPIC_API_KEY não configurada. Adicione-a no arquivo .env.",
            history=history,
            anomaly=True,
        )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    system = build_system_prompt()

    # Adiciona mensagem do usuário
    messages: list[dict] = list(history) + [{"role": "user", "content": message}]

    total_in = total_out = 0
    last_response = None

    for iteration in range(1, settings.agent_max_iters + 1):
        logger.info("loop iter %d/%d — chamando modelo...", iteration, settings.agent_max_iters)

        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=4096,
            system=system,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )
        last_response = response

        iter_in  = response.usage.input_tokens
        iter_out = response.usage.output_tokens
        total_in  += iter_in
        total_out += iter_out

        logger.info(
            "iter %d: stop_reason=%s | tokens=%d in / %d out",
            iteration, response.stop_reason, iter_in, iter_out,
        )

        # --- end_turn: resposta final ---
        if response.stop_reason == "end_turn":
            text = _extract_text(response.content)
            messages.append({"role": "assistant", "content": _content_to_dicts(response.content)})
            cost = _calc_cost(total_in, total_out)
            logger.info(
                "conversa encerrada: %d iters | %d in / %d out tokens | ~US$ %.4f",
                iteration, total_in, total_out, cost,
            )
            return AgentResult(
                reply=text,
                history=messages,
                tokens_input=total_in,
                tokens_output=total_out,
                iterations=iteration,
                cost_usd=cost,
            )

        # --- tool_use: executa tools em paralelo ---
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": _content_to_dicts(response.content)})

            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            logger.info(
                "iter %d: %d tool(s) solicitada(s): %s",
                iteration, len(tool_blocks), [b.name for b in tool_blocks],
            )

            results = await asyncio.gather(*[_dispatch(b.name, b.input) for b in tool_blocks])

            tool_results = [
                {
                    "type": "tool_result",
                    "tool_use_id": b.id,
                    "content": to_tool_content(r),
                }
                for b, r in zip(tool_blocks, results)
            ]
            messages.append({"role": "user", "content": tool_results})
            continue

        # --- max_tokens: tenta continuar com nudge ---
        if response.stop_reason == "max_tokens":
            partial = _extract_text(response.content)
            messages.append({"role": "assistant", "content": _content_to_dicts(response.content)})
            messages.append({"role": "user", "content": "Continue."})
            logger.warning("iter %d: max_tokens atingido — empurrando com 'Continue.'", iteration)
            continue

        # --- stop_reason desconhecido ---
        logger.error("iter %d: stop_reason inesperado: '%s'", iteration, response.stop_reason)
        break

    # MAX_ITERS esgotado ou break por stop_reason desconhecido
    logger.error(
        "loop: MAX_ITERS=%d esgotado ou stop_reason inesperado — degradando com elegância",
        settings.agent_max_iters,
    )
    partial_text = _extract_text(last_response.content) if last_response else ""
    reply = (
        (partial_text + "\n\n_(Atingi o limite de iterações. Esta resposta pode estar incompleta.)_")
        if partial_text
        else "_(Não consegui concluir a consulta. Por favor, tente novamente com uma pergunta mais específica.)_"
    )
    cost = _calc_cost(total_in, total_out)
    return AgentResult(
        reply=reply,
        history=messages,
        tokens_input=total_in,
        tokens_output=total_out,
        iterations=settings.agent_max_iters,
        cost_usd=cost,
        anomaly=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text(content: list) -> str:
    return "\n".join(b.text for b in content if hasattr(b, "text") and b.text)


def _content_to_dicts(content: list) -> list[dict]:
    """Converte ContentBlocks do SDK para dicts serializáveis."""
    out = []
    for block in content:
        if block.type == "text":
            out.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            out.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return out


def _calc_cost(tokens_in: int, tokens_out: int) -> float:
    return (tokens_in * _PRICE_IN_PER_M + tokens_out * _PRICE_OUT_PER_M) / 1_000_000
