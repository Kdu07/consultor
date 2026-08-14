"""
Valoração de posições sem cotação ao vivo.

Fonte única de verdade para o "valor offline" de uma posição — usado por
dashboard, snapshot mensal e cálculo de desvio. Evita que um holding real
seja contado como R$ 0,00 quando não há cotação ao vivo nem valor_mercado.

Cadeia de fallback:
  1. valor_mercado (saldo do extrato) — melhor fonte offline
  2. quantidade × preco_medio (proxy pelo custo de aquisição)
  3. 0.0 (sem nenhum dado de valor)
"""
from ..models.posicao import Posicao


def valor_offline(p: Posicao) -> tuple[float, bool]:
    """
    Retorna (valor, usou_preco_medio) para uma posição sem cotação ao vivo.

    `usou_preco_medio` é True quando o valor veio do proxy quantidade × preço
    médio — permite ao chamador sinalizar que o número é aproximado.
    """
    if p.valor_mercado is not None:
        return p.valor_mercado, False
    if p.preco_medio is not None:
        return p.quantidade * p.preco_medio, True
    return 0.0, False
