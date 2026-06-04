"""
Tool dados_ativo — cotação enriquecida de um ativo com cache SQLite (TTL 15 min).

Roteamento:
  ticker começa com "tesouro" (case-insensitive) → TesouroProvider
  caso contrário                                  → CompositeProvider (brapi → yfinance)

Contrato: nunca lança exceção. Falha → {"error": ...}.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlmodel import Session, select

from ..config import get_settings
from ..database import engine
from ..models.quote_cache import QuoteCache
from ..providers.composite import build_rv_provider
from ..providers.tesouro_provider import TesouroProvider
from .schemas import tool_error

logger = logging.getLogger(__name__)

# Singleton do TesouroProvider (mantém cache interno de títulos)
_tesouro_provider = TesouroProvider()


def _is_tesouro(ticker: str) -> bool:
    return ticker.upper().startswith("TESOURO")


def _quote_from_cache(ticker: str, ttl_seconds: int) -> Optional[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)
    with Session(engine) as session:
        row = session.exec(
            select(QuoteCache)
            .where(QuoteCache.ticker == ticker.upper())
            .where(QuoteCache.fetched_at >= cutoff)
            .order_by(QuoteCache.fetched_at.desc())
        ).first()
        if row:
            return {
                "ticker": row.ticker,
                "price": row.price,
                "source": row.source,
                "as_of": row.fetched_at.isoformat(),
                "is_cached": True,
            }
    return None


def _save_to_cache(ticker: str, price: float, source: str, as_of: datetime) -> None:
    with Session(engine) as session:
        # Apaga entradas antigas do mesmo ticker
        old = session.exec(select(QuoteCache).where(QuoteCache.ticker == ticker.upper())).all()
        for o in old:
            session.delete(o)
        entry = QuoteCache(ticker=ticker.upper(), price=price, source=source, fetched_at=as_of)
        session.add(entry)
        session.commit()


def _fetch_quote(ticker: str) -> Optional[dict]:
    """Busca cotação no provider (sync). Retorna dict ou None."""
    settings = get_settings()

    if _is_tesouro(ticker):
        quote = _tesouro_provider.enrich(ticker)
    else:
        provider = build_rv_provider(settings.price_provider, settings.brapi_token)
        quote = provider.enrich(ticker)

    if quote is None:
        return None

    _save_to_cache(quote.ticker, quote.price, quote.source, quote.as_of)

    result: dict = {
        "ticker": quote.ticker,
        "price": quote.price,
        "source": quote.source,
        "as_of": quote.as_of.isoformat(),
        "is_cached": False,
    }
    if quote.variacao_pct is not None:
        result["variacao_pct"] = quote.variacao_pct
    if quote.pl is not None:
        result["pl"] = quote.pl
    if quote.setor:
        result["setor"] = quote.setor
    if quote.nome:
        result["nome"] = quote.nome
    return result


async def tool_dados_ativo(ticker: str) -> dict:
    """
    Retorna cotação enriquecida. Checa cache antes de chamar o provider.
    Nunca lança exceção.
    """
    settings = get_settings()
    ticker = ticker.strip()

    try:
        cached = _quote_from_cache(ticker, settings.quote_cache_ttl_seconds)
        if cached:
            logger.info("dados_ativo: %s (cache, source=%s)", ticker, cached["source"])
            return cached

        # Providers são síncronos — roda em thread para não bloquear o event loop
        result = await asyncio.to_thread(_fetch_quote, ticker)

        if result is None:
            return tool_error(
                f"Sem cotação disponível para '{ticker}'. "
                "Verifique o ticker ou tente novamente mais tarde."
            )

        logger.info(
            "dados_ativo: %s = R$ %.2f (source=%s, as_of=%s)",
            result["ticker"], result["price"], result["source"], result["as_of"][:16],
        )
        return result

    except Exception as e:
        logger.error("dados_ativo: erro inesperado para '%s': %s", ticker, e)
        return tool_error(f"Erro interno ao buscar '{ticker}': {e}")
