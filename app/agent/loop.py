"""
Loop do agente consultor (PLANO §3).

Invariantes:
  - MAX_ITERS ≈ 6; estourou → degrada com elegância e loga como anomalia.
  - Tools NUNCA lançam exceção para dentro do loop (contrato de app/tools/).
  - Tools independentes no mesmo turno rodam em paralelo (asyncio.gather).
  - Logging de tokens por iteração E por conversa.
  - Sem prompt caching (decisão deliberada — PLANO §5).

Duas portas de entrada, mesmo comportamento:
  - run_agent()        → espera o turno inteiro e devolve um AgentResult.
  - run_agent_stream() → gerador de eventos (texto token-a-token + status de tools),
                         encerrando com o mesmo AgentResult no evento "done".
"""
import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import anthropic

from ..config import get_settings
from ..tools.ativo import tool_dados_ativo
from ..tools.carteira import tool_ler_carteira
from ..tools.desempenho_servico import tool_desempenho_carteira
from ..tools.desvio import tool_calcular_desvio
from ..tools.extrato import tool_importar_extrato
from ..tools.gravar import tool_gravar_posicoes
from ..tools.macro import tool_contexto_macro
from ..tools.noticias import tool_noticias
from ..tools.estrategia import tool_atualizar_estrategia
from ..tools.proposta import tool_proposta_rebalanceamento
from ..tools.rebalanceamento import tool_sugerir_rebalanceamento
from ..tools.schemas import TOOL_DEFINITIONS, to_tool_content
from .system_prompt import build_system_blocks

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dispatch de tools
# ---------------------------------------------------------------------------

_TOOL_DISPATCH: dict[str, Any] = {
    "ler_carteira":    lambda _i: tool_ler_carteira(),
    "dados_ativo":     lambda i: tool_dados_ativo(i["ticker"]),
    "contexto_macro":  lambda _i: tool_contexto_macro(),
    "calcular_desvio":   lambda _i: tool_calcular_desvio(),
    "importar_extrato":  lambda _i: tool_importar_extrato(),
    "gravar_posicoes":   lambda i: tool_gravar_posicoes(i.get("posicoes")),
    "noticias":                lambda i: tool_noticias(i["ticker_ou_tema"]),
    "sugerir_rebalanceamento":    lambda _i: tool_sugerir_rebalanceamento(),
    "atualizar_estrategia":       lambda i: tool_atualizar_estrategia(i),
    "proposta_rebalanceamento":   lambda i: tool_proposta_rebalanceamento(i["operacoes"]),
    "desempenho_carteira":        lambda i: tool_desempenho_carteira(
        i.get("periodo", "12m"), i.get("nivel", "carteira"), i.get("mes")
    ),
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
# Cache de prompt (system prompt fixo + tools — ver build_system_blocks): gravar custa
# 1,25× a entrada (TTL de 5 min); ler do cache custa 0,1×.
_MULT_CACHE_GRAVADO = 1.25
_MULT_CACHE_LIDO = 0.10


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
    system = build_system_blocks()

    # Adiciona mensagem do usuário
    messages: list[dict] = list(history) + [{"role": "user", "content": message}]

    total_in = total_out = cache_gravado = cache_lido = 0
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

        iter_in, iter_out, iter_gravado, iter_lido = _uso(response.usage)
        total_in  += iter_in
        total_out += iter_out
        cache_gravado += iter_gravado
        cache_lido += iter_lido

        logger.info(
            "iter %d: stop_reason=%s | tokens=%d in / %d out | cache %d gravado / %d lido",
            iteration, response.stop_reason, iter_in, iter_out, iter_gravado, iter_lido,
        )

        # --- end_turn: resposta final ---
        if response.stop_reason == "end_turn":
            text = _extract_text(response.content)
            messages.append({"role": "assistant", "content": _content_to_dicts(response.content)})
            cost = _calc_cost(total_in, total_out, cache_gravado, cache_lido)
            logger.info(
                "conversa encerrada: %d iters | %d in / %d out tokens | ~US$ %.4f",
                iteration, total_in, total_out, cost,
            )
            return AgentResult(
                reply=text,
                history=messages,
                tokens_input=total_in + cache_gravado + cache_lido,
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
    cost = _calc_cost(total_in, total_out, cache_gravado, cache_lido)
    return AgentResult(
        reply=reply,
        history=messages,
        tokens_input=total_in + cache_gravado + cache_lido,
        tokens_output=total_out,
        iterations=settings.agent_max_iters,
        cost_usd=cost,
        anomaly=True,
    )


# ---------------------------------------------------------------------------
# Loop em streaming
# ---------------------------------------------------------------------------

async def run_agent_stream(message: str, history: list[dict]) -> AsyncIterator[dict]:
    """
    Mesma máquina de estados de run_agent(), emitindo eventos conforme acontecem:

      {"type": "text",   "text": "..."}          delta de texto do modelo
      {"type": "tools",  "names": [...]}         tools que vão rodar agora
      {"type": "tools_done", "names": [...]}     tools terminaram
      {"type": "done",   "result": AgentResult}  fim do turno (sempre o último)

    O evento "done" carrega o AgentResult inteiro (inclusive o histórico) — cabe à
    camada HTTP decidir o que serializar. Nunca propaga exceção: falha da API vira
    um "done" com anomaly=True.
    """
    settings = get_settings()

    if not settings.anthropic_api_key:
        yield {"type": "done", "result": AgentResult(
            reply="Chave ANTHROPIC_API_KEY não configurada. Adicione-a no arquivo .env.",
            history=history,
            anomaly=True,
        )}
        return

    # build_system_blocks() lê o banco (tese, planos): se falhar, precisa virar um
    # "done", senão o SSE morre no meio sem o cliente saber por quê.
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        system = build_system_blocks()
    except Exception as e:
        logger.error("stream: falha ao montar o contexto do turno: %s", e)
        yield {"type": "done", "result": AgentResult(
            reply=f"Não consegui montar o contexto da conversa: {e}",
            history=history,
            anomaly=True,
        )}
        return

    messages: list[dict] = list(history) + [{"role": "user", "content": message}]

    total_in = total_out = cache_gravado = cache_lido = 0
    # Texto do turno montado exatamente como o cliente o recebeu: os deltas entram
    # colados e a quebra de parágrafo só é inserida antes de uma rodada de tools
    # (o frontend faz o mesmo). Juntar tudo com "\n\n" no fim partiria ao meio a
    # frase que o max_tokens cortou e depois continuou.
    texto = ''

    for iteration in range(1, settings.agent_max_iters + 1):
        logger.info("stream iter %d/%d — chamando modelo...", iteration, settings.agent_max_iters)

        try:
            async with client.messages.stream(
                model=settings.anthropic_model,
                max_tokens=4096,
                system=system,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            ) as stream:
                async for event in stream:
                    if event.type == "text":
                        yield {"type": "text", "text": event.text}
                response = await stream.get_final_message()
        except Exception as e:
            logger.error("stream iter %d: falha na chamada ao modelo: %s", iteration, e)
            yield {"type": "done", "result": AgentResult(
                reply=(f"{texto}\n\n_(A conexão com o modelo falhou no meio da resposta: {e})_"
                       if texto else f"Falha ao falar com o modelo: {e}"),
                history=messages,
                tokens_input=total_in + cache_gravado + cache_lido,
                tokens_output=total_out,
                iterations=iteration,
                cost_usd=_calc_cost(total_in, total_out, cache_gravado, cache_lido),
                anomaly=True,
            )}
            return

        iter_in, iter_out, iter_gravado, iter_lido = _uso(response.usage)
        total_in += iter_in
        total_out += iter_out
        cache_gravado += iter_gravado
        cache_lido += iter_lido

        texto += _extract_text(response.content)

        logger.info(
            "stream iter %d: stop_reason=%s | tokens=%d in / %d out | cache %d gravado / %d lido",
            iteration, response.stop_reason, iter_in, iter_out, iter_gravado, iter_lido,
        )

        # --- end_turn: resposta final ---
        if response.stop_reason == "end_turn":
            messages.append({"role": "assistant", "content": _content_to_dicts(response.content)})
            cost = _calc_cost(total_in, total_out, cache_gravado, cache_lido)
            logger.info(
                "conversa encerrada (stream): %d iters | %d in / %d out tokens | ~US$ %.4f",
                iteration, total_in, total_out, cost,
            )
            yield {"type": "done", "result": AgentResult(
                reply=texto,
                history=messages,
                tokens_input=total_in + cache_gravado + cache_lido,
                tokens_output=total_out,
                iterations=iteration,
                cost_usd=cost,
            )}
            return

        # --- tool_use: executa tools em paralelo, avisando a UI ---
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": _content_to_dicts(response.content)})

            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            nomes = [b.name for b in tool_blocks]
            logger.info("stream iter %d: %d tool(s): %s", iteration, len(tool_blocks), nomes)

            if texto and not texto.endswith("\n"):
                texto += "\n\n"

            yield {"type": "tools", "names": nomes}
            results = await asyncio.gather(*[_dispatch(b.name, b.input) for b in tool_blocks])
            yield {"type": "tools_done", "names": nomes}

            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": b.id, "content": to_tool_content(r)}
                for b, r in zip(tool_blocks, results)
            ]})
            continue

        # --- max_tokens: tenta continuar com nudge ---
        if response.stop_reason == "max_tokens":
            messages.append({"role": "assistant", "content": _content_to_dicts(response.content)})
            messages.append({"role": "user", "content": "Continue."})
            logger.warning("stream iter %d: max_tokens atingido — empurrando com 'Continue.'", iteration)
            continue

        logger.error("stream iter %d: stop_reason inesperado: '%s'", iteration, response.stop_reason)
        break

    logger.error("stream: MAX_ITERS=%d esgotado ou stop_reason inesperado", settings.agent_max_iters)
    aviso = (
        "\n\n_(Atingi o limite de iterações. Esta resposta pode estar incompleta.)_"
        if texto
        else "_(Não consegui concluir a consulta. Por favor, tente novamente com uma pergunta mais específica.)_"
    )
    yield {"type": "done", "result": AgentResult(
        reply=texto + aviso,
        history=messages,
        tokens_input=total_in + cache_gravado + cache_lido,
        tokens_output=total_out,
        iterations=settings.agent_max_iters,
        cost_usd=_calc_cost(total_in, total_out, cache_gravado, cache_lido),
        anomaly=True,
    )}


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


def _uso(usage) -> tuple[int, int, int, int]:
    """(entrada sem cache, saída, gravado no cache, lido do cache) de uma resposta."""
    return (
        usage.input_tokens,
        usage.output_tokens,
        getattr(usage, "cache_creation_input_tokens", 0) or 0,
        getattr(usage, "cache_read_input_tokens", 0) or 0,
    )


def _calc_cost(tokens_in: int, tokens_out: int, cache_gravado: int = 0, cache_lido: int = 0) -> float:
    entrada = (
        tokens_in
        + cache_gravado * _MULT_CACHE_GRAVADO
        + cache_lido * _MULT_CACHE_LIDO
    )
    return (entrada * _PRICE_IN_PER_M + tokens_out * _PRICE_OUT_PER_M) / 1_000_000
