"""
YFinanceProvider — validação/bootstrap e fallback (PLANO §6.1).
Normaliza tickers B3: PETR4 → PETR4.SA
Nunca lança exceção para o chamador.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf

from .base import Quote

logger = logging.getLogger(__name__)


def _normalize(ticker: str) -> str:
    """Adiciona sufixo .SA para tickers da B3 que ainda não o têm."""
    t = ticker.upper().strip()
    if not t.endswith(".SA") and not t.endswith("=X") and not t.endswith("=F"):
        return t + ".SA"
    return t


class YFinanceProvider:
    """
    Fonte não-oficial (raspa Yahoo Finance).
    Boa o bastante para validar; frágil demais para ser produção.
    Usada como fallback quando brapi falha.
    """

    source = "yfinance"

    def quote(self, ticker: str) -> Optional[Quote]:
        normalized = _normalize(ticker)
        try:
            info = yf.Ticker(normalized).fast_info
            price = info.last_price
            if not price or price <= 0:
                logger.warning("yfinance: preço inválido para %s (%.2f)", normalized, price or 0)
                return None
            q = Quote(
                ticker=ticker.upper(),
                price=round(float(price), 2),
                source=self.source,
                as_of=datetime.now(timezone.utc),
            )
            logger.info(
                "yfinance: %s = R$ %.2f (source=%s, as_of=%s)",
                q.ticker, q.price, q.source, q.as_of.strftime("%Y-%m-%d %H:%M"),
            )
            return q
        except Exception as e:
            logger.warning("yfinance: falha ao buscar %s — %s", normalized, e)
            return None

    def enrich(self, ticker: str) -> Optional[Quote]:
        normalized = _normalize(ticker)
        try:
            t = yf.Ticker(normalized)
            fi = t.fast_info
            price = fi.last_price
            if not price or price <= 0:
                return None

            info = t.info  # chamada mais pesada — traz setor, nome, P/L
            pl = info.get("trailingPE") or info.get("forwardPE")
            setor = info.get("sector") or info.get("industryDisp")
            nome = info.get("longName") or info.get("shortName")
            prev_close = fi.previous_close or 0
            variacao = ((price - prev_close) / prev_close * 100) if prev_close else None

            return Quote(
                ticker=ticker.upper(),
                price=round(float(price), 2),
                source=self.source,
                as_of=datetime.now(timezone.utc),
                variacao_pct=round(variacao, 2) if variacao is not None else None,
                pl=round(float(pl), 2) if pl else None,
                setor=setor,
                nome=nome,
            )
        except Exception as e:
            logger.warning("yfinance.enrich: falha para %s — %s", normalized, e)
            return None
