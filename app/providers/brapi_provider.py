"""
BrapiProvider — primário de produção planejado (PLANO §6.2).
Ativo quando BRAPI_TOKEN estiver preenchido e price_provider="brapi" no .env.
Stub pronto; implementação completa entra ao contratar o plano Startup da brapi.dev.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from .base import Quote

logger = logging.getLogger(__name__)

_BASE_URL = "https://brapi.dev/api"


class BrapiProvider:
    """
    Fonte oficial (B3/CVM/BCB via brapi.dev).
    Requer BRAPI_TOKEN no .env.
    Tickers B3 sem sufixo: PETR4 (não PETR4.SA).
    """

    source = "brapi"

    def __init__(self, token: str):
        self._token = token

    def quote(self, ticker: str) -> Optional[Quote]:
        t = ticker.upper().replace(".SA", "")
        try:
            with httpx.Client(timeout=8.0) as client:
                resp = client.get(
                    f"{_BASE_URL}/quote/{t}",
                    params={"token": self._token},
                )
                resp.raise_for_status()
                data = resp.json()
                result = data.get("results", [{}])[0]
                price = result.get("regularMarketPrice")
                if not price:
                    logger.warning("brapi: sem preço para %s", t)
                    return None
                q = Quote(
                    ticker=ticker.upper(),
                    price=round(float(price), 2),
                    source=self.source,
                    as_of=datetime.now(timezone.utc),
                    variacao_pct=result.get("regularMarketChangePercent"),
                    nome=result.get("longName") or result.get("shortName"),
                )
                logger.info("brapi: %s = R$ %.2f", q.ticker, q.price)
                return q
        except Exception as e:
            logger.warning("brapi: falha ao buscar %s — %s", t, e)
            return None

    def enrich(self, ticker: str) -> Optional[Quote]:
        # brapi devolve variacao_pct e nome já no quote; setor/P/L via endpoint separado
        return self.quote(ticker)
