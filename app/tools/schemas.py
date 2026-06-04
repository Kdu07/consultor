"""
Contrato das tools do agente (PLANO §3).

Regra inegociável: tools NUNCA lançam exceção para dentro do loop.
  Sucesso → dict com dados + source + as_of + is_cached
  Falha   → {"error": "<motivo legível>"}

O modelo traduz "error" em "não tenho esse dado" — o guardrail antialucinação
é aplicado aqui, no loop, não só no prompt.
"""
import json
from typing import Any


def tool_error(msg: str) -> dict:
    """Retorna estrutura de falha padronizada."""
    return {"error": msg}


def to_tool_content(result: dict) -> str:
    """Serializa o resultado da tool para string JSON enviada ao modelo."""
    return json.dumps(result, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Definições das tools para o SDK Anthropic (input_schema em JSON Schema)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "ler_carteira",
        "description": (
            "Retorna todas as posições ativas da carteira com ticker, nome, classe, "
            "quantidade, preço médio, valor de mercado, source e as_of para cada ativo. "
            "Sempre chame esta tool antes de responder sobre a carteira — nunca use memória da conversa anterior."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "dados_ativo",
        "description": (
            "Retorna preço atual, variação no dia (%), P/L e setor de um ativo com ticker. "
            "Usa cache de 15 min. Para renda variável (ações, FIIs, ETFs, BDRs): passe o ticker B3 (ex: PETR4, MXRF11). "
            "Para Tesouro Direto: passe o nome parcial (ex: 'Tesouro IPCA+ 2035', 'Tesouro Selic 2027'). "
            "Resultado inclui source (brapi/yfinance/tesouro) e as_of."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Ticker B3 (PETR4) ou nome parcial do Tesouro Direto ('Tesouro IPCA+ 2035').",
                }
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "contexto_macro",
        "description": (
            "Retorna dados macroeconômicos do Brasil via API pública do BCB: "
            "Meta Selic (% a.a.), IPCA variação mensal (% a.m.) e câmbio USD/BRL. "
            "Todos os valores com source='BCB' e data de referência."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]
