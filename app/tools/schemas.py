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
    {
        "name": "calcular_desvio",
        "description": (
            "Calcula o desvio da carteira em relação aos alvos (por classe e por ativo) "
            "usando snapshot coerente: RV e Tesouro com preço ao vivo, RF privada pelo valor do extrato. "
            "Retorna desvio em p.p. e R$, flag dentro/fora da banda 5/25, fração ao-vivo vs. extrato, "
            "as_of mais antigo e data da última atualização das posições. "
            "Chame antes de responder 'devo rebalancear?' — nunca estime de cabeça."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "noticias",
        "description": (
            "Busca manchetes recentes sobre um ticker ou tema financeiro via RSS. "
            "Use para perguntas como 'o que está acontecendo com PETR4?' ou 'últimas notícias sobre Selic'. "
            "Cache de 4h. Retorna até 8 manchetes com título, fonte e data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker_ou_tema": {
                    "type": "string",
                    "description": "Ticker B3 (ex: PETR4, KNCR11) ou tema livre (ex: 'Selic', 'inflação', 'mercado').",
                }
            },
            "required": ["ticker_ou_tema"],
        },
    },
    {
        "name": "importar_extrato",
        "description": (
            "Parseia o texto copiado do extrato PDF da conta de investimento do BTG "
            "(seções: Ações, ETF, Fundos Listados, Tesouro Direto). "
            "Retorna PREVIEW com as posições extraídas — NÃO salva nada. "
            "Após apresentar o preview ao usuário e receber 'sim' explícito, "
            "chame gravar_posicoes para gravar. NUNCA grave sem confirmação."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "texto": {
                    "type": "string",
                    "description": (
                        "Texto completo copiado do extrato PDF do BTG "
                        "(selecionar tudo Ctrl+A e copiar Ctrl+C no leitor de PDF)."
                    ),
                }
            },
            "required": ["texto"],
        },
    },
    {
        "name": "gravar_posicoes",
        "description": (
            "Salva as posições do preview no banco de dados. "
            "SOMENTE chame após o usuário confirmar explicitamente com 'sim' ou equivalente. "
            "Nunca chame no mesmo turno que importar_extrato — a confirmação é um turno separado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "posicoes": {
                    "type": "array",
                    "description": "Lista de posições exatamente como retornado por importar_extrato.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ticker":        {"type": "string"},
                            "nome":          {"type": "string"},
                            "classe":        {"type": "string"},
                            "quantidade":    {"type": "number"},
                            "preco_medio":   {"type": "number"},
                            "valor_mercado": {"type": "number"},
                            "as_of":         {"type": "string"},
                        },
                        "required": ["nome", "classe", "quantidade", "valor_mercado"],
                    },
                }
            },
            "required": ["posicoes"],
        },
    },
]
