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
            "Lê o extrato XLSX da conta de investimento do BTG que o usuário enviou pela "
            "interface (ações, ETFs, fundos listados, Tesouro Direto, renda fixa privada "
            "e saldo em conta corrente). Não recebe argumentos — o arquivo é enviado pela UI. "
            "Retorna PREVIEW com as posições, os proventos do mês, o comparativo com o mês "
            "anterior e a conferência de totais contra o Sumário do extrato — NÃO salva nada. "
            "Se a conferência de totais falhar ou houver 'linhas_ignoradas', DIGA isso ao "
            "usuário antes de propor a gravação. "
            "Após apresentar o preview e receber 'sim' explícito, chame gravar_posicoes. "
            "NUNCA grave sem confirmação. Se nenhum extrato foi enviado, a tool avisa — "
            "peça ao usuário para usar o botão 'Importar extrato BTG' na interface."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "atualizar_estrategia",
        "description": (
            "Persiste mudanças na tese de investimento e/ou nos planos futuros. "
            "SOMENTE chame após o usuário confirmar explicitamente com 'sim' ou equivalente — "
            "nunca no mesmo turno em que você propôs a mudança. "
            "Aceita qualquer combinação de: 'tese' (string), 'planos_adicionar' (lista), "
            "'planos_atualizar' (lista com 'id'), 'planos_remover' (lista de ids). "
            "Retorna {ok, version_nova, resumo} em sucesso."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tese": {
                    "type": "string",
                    "description": "Nova tese narrativa de investimento (substitui a atual).",
                },
                "planos_adicionar": {
                    "type": "array",
                    "description": "Planos futuros a adicionar.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "descricao": {"type": "string"},
                            "gatilho": {"type": "string"},
                            "horizonte": {"type": "string"},
                        },
                        "required": ["descricao"],
                    },
                },
                "planos_atualizar": {
                    "type": "array",
                    "description": "Planos existentes a atualizar (requer 'id').",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "descricao": {"type": "string"},
                            "gatilho": {"type": "string"},
                            "horizonte": {"type": "string"},
                            "status": {"type": "string", "enum": ["ativo", "cumprido", "cancelado"]},
                        },
                        "required": ["id"],
                    },
                },
                "planos_remover": {
                    "type": "array",
                    "description": "IDs de planos a cancelar.",
                    "items": {"type": "integer"},
                },
            },
            "required": [],
        },
    },
    {
        "name": "proposta_rebalanceamento",
        "description": (
            "Simula operações hipotéticas de compra/venda sobre o snapshot atual da carteira "
            "e calcula como ficaria a alocação vs. alvos (what-if de pré-trade). "
            "Não altera o banco — análise pura. "
            "Retorna por_classe e por_ativo com percentuais hipotéticos, delta vs. atual, "
            "desvio vs. alvo e flag fora_da_banda_hip. "
            "Inclui fracao_liquida_pct (ACAO+ETF+FII+BDR+CAIXA+TESOURO / total) para checar a trava de liquidez. "
            "Use quando o usuário perguntar 'se eu comprar X / vender Y, como fica minha carteira?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operacoes": {
                    "type": "array",
                    "description": "Lista de operações hipotéticas a simular.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "acao": {
                                "type": "string",
                                "enum": ["comprar", "vender"],
                                "description": "'comprar' ou 'vender'",
                            },
                            "ticker": {
                                "type": "string",
                                "description": "Ticker B3 (ex: PETR4). Opcional se nome informado.",
                            },
                            "nome": {
                                "type": "string",
                                "description": "Nome do ativo (para RF sem ticker).",
                            },
                            "classe": {
                                "type": "string",
                                "description": "Classe do ativo (ACAO, FII, ETF, BDR, RF, TESOURO, FUNDO, CAIXA).",
                            },
                            "quantidade": {
                                "type": "number",
                                "description": "Quantidade de cotas/ações a comprar ou vender.",
                            },
                            "preco": {
                                "type": "number",
                                "description": "Preço unitário hipotético (R$) para a operação.",
                            },
                        },
                        "required": ["acao", "quantidade", "preco"],
                    },
                }
            },
            "required": ["operacoes"],
        },
    },
    {
        "name": "sugerir_rebalanceamento",
        "description": (
            "Gera sugestões consultivas de rebalanceamento da carteira. "
            "Internamente chama calcular_desvio e filtra apenas os itens fora da banda 5/25 "
            "e acima do piso de irrelevância. "
            "Retorna sugestoes_por_classe e sugestoes_por_ativo com ação (REDUZIR/AUMENTAR), "
            "valor_a_mover (R$), percentuais e razão. "
            "status='dentro_da_banda' → carteira OK; 'rebalanceamento_sugerido' → há ajustes a avaliar. "
            "Use quando o usuário pedir sugestões de rebalanceamento ou revisão mensal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "gravar_posicoes",
        "description": (
            "Salva no banco as posições do extrato que o usuário enviou pela UI. "
            "SOMENTE chame após o usuário confirmar explicitamente com 'sim' ou equivalente. "
            "Nunca chame no mesmo turno que importar_extrato — a confirmação é um turno separado. "
            "Não repita as posições no argumento: a tool lê o preview do extrato direto do "
            "servidor, com os valores exatos. Chame sem argumentos. "
            "O extrato é a carteira COMPLETA na data de referência: posições que não aparecem "
            "nele saem da carteira e voltam em 'posicoes_desativadas' — sempre relate essa "
            "lista ao usuário, pode ser venda/resgate ou ativo fora do BTG. "
            "'posicoes_reativadas' traz o caminho inverso: papel que tinha saído e voltou."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "posicoes": {
                    "type": "array",
                    "description": (
                        "Opcional e normalmente desnecessário. Só use para gravação manual, "
                        "quando não há extrato enviado pela UI. Havendo extrato em staging, "
                        "ele prevalece sobre esta lista."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "ticker":          {"type": "string"},
                            "nome":            {"type": "string"},
                            "classe":          {"type": "string"},
                            "quantidade":      {"type": "number"},
                            "preco_medio":     {"type": "number"},
                            "valor_mercado":   {"type": "number"},
                            "as_of":           {"type": "string"},
                            "vencimento":      {"type": "string", "description": "Renda fixa: vencimento ISO (YYYY-MM-DD)."},
                            "taxa_contratada": {"type": "string", "description": "Renda fixa: taxa do extrato (ex.: 'IPCA + 7,62%')."},
                            "custo_total":     {"type": "number", "description": "Renda fixa: valor total de aquisição."},
                        },
                        "required": ["nome", "classe", "quantidade", "valor_mercado"],
                    },
                }
            },
            "required": [],
        },
    },
]
