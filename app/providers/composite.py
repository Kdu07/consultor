"""
CompositeProvider — tenta providers na ordem configurada (PLANO §6.3).
Primeiro com dado válido vence. Todos falharam → None → agente diz "não tenho esse dado".
"""
import logging
from typing import Optional

from .base import PriceProvider, Quote

logger = logging.getLogger(__name__)


class CompositeProvider:
    def __init__(self, providers: list):
        self._providers = providers

    def quote(self, ticker: str) -> Optional[Quote]:
        for p in self._providers:
            result = p.quote(ticker)
            if result is not None:
                return result
        logger.warning("CompositeProvider: todos os providers falharam para %s", ticker)
        return None

    def enrich(self, ticker: str) -> Optional[Quote]:
        for p in self._providers:
            result = p.enrich(ticker)
            if result is not None:
                return result
        logger.warning("CompositeProvider.enrich: todos os providers falharam para %s", ticker)
        return None


def build_rv_provider(price_provider: str = "yfinance", brapi_token: str = "") -> CompositeProvider:
    """
    Constrói o CompositeProvider de renda variável conforme configuração.

    price_provider="yfinance" → [YFinance]           (modo validação/bootstrap)
    price_provider="brapi"    → [Brapi, YFinance]    (modo produção planejado)
    """
    from .yfinance_provider import YFinanceProvider
    from .brapi_provider import BrapiProvider

    yf = YFinanceProvider()

    if price_provider == "brapi" and brapi_token:
        brapi = BrapiProvider(token=brapi_token)
        logger.info("CompositeProvider RV: brapi (primário) → yfinance (fallback)")
        return CompositeProvider([brapi, yf])

    logger.info("CompositeProvider RV: yfinance (modo validação)")
    return CompositeProvider([yf])
