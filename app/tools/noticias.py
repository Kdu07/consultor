"""
Tool noticias — manchetes recentes via RSS (Google News + InfoMoney).

Fonte primária: Google News RSS (por ticker/tema, hl=pt-BR).
Fonte secundária: InfoMoney Mercados RSS (geral, filtrado por relevância).
Cache em memória: TTL de 4h (notícia não muda tão rápido quanto preço).

Nunca lança exceção — falha retorna {"error": ...}.
"""
from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote_plus

import httpx

from .schemas import tool_error

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[list[dict], datetime]] = {}  # key → (items, fetched_at)
_CACHE_TTL = timedelta(hours=4)

# ceid=BR:pt-419 é o código correto para português do Brasil no Google News
_GOOGLE_NEWS_URL = (
    "https://news.google.com/rss/search"
    "?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
)
# Fallback: Valor Econômico (InfoMoney não resolve em alguns ambientes)
_VALOR_URL = "https://valor.globo.com/rss/home/"

_TICKER_RE = re.compile(r"^[A-Z]{4,6}\d{0,2}$")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; consultor-app/0.1)"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cache_key(query: str) -> str:
    return hashlib.md5(query.lower().strip().encode()).hexdigest()


def _from_cache(key: str) -> Optional[list[dict]]:
    entry = _CACHE.get(key)
    if entry and datetime.now(timezone.utc) - entry[1] < _CACHE_TTL:
        return entry[0]
    return None


def _to_cache(key: str, items: list[dict]) -> None:
    _CACHE[key] = (items, datetime.now(timezone.utc))


def _build_query(ticker_ou_tema: str) -> str:
    """Monta a query de busca: ticker → 'PETR4 ações'; tema → usa como está."""
    t = ticker_ou_tema.strip().upper()
    if _TICKER_RE.match(t):
        # Ticker B3: busca o ticker + "ações" para contexto brasileiro
        return f"{t} ações"
    # Tema livre: usa como está
    return ticker_ou_tema.strip()


def _parse_rss(xml_text: str, filter_query: Optional[str] = None) -> list[dict]:
    """
    Parseia RSS 2.0 genérico.
    Se filter_query fornecida, filtra itens que contêm o termo no título.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("noticias: erro ao parsear RSS XML: %s", e)
        return []

    items: list[dict] = []
    filter_lower = filter_query.lower() if filter_query else None

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        if filter_lower and filter_lower not in title.lower():
            # Filtra por relevância quando a fonte é geral
            desc = (item.findtext("description") or "").lower()
            if filter_lower not in desc:
                continue

        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()

        # Google News inclui <source> dentro de <item>
        source_el = item.find("source")
        fonte = source_el.text.strip() if source_el is not None and source_el.text else ""

        items.append({
            "titulo": title,
            "fonte": fonte or "—",
            "data": pub_date[:25] if pub_date else "",
            "link": link,
        })

    return items[:8]  # máximo 8 por fonte


async def _fetch(url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(
            timeout=10.0, headers=_HEADERS, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        logger.warning("noticias: falha ao buscar %s — %s", url[:80], e)
        return None


# ---------------------------------------------------------------------------
# Tool principal
# ---------------------------------------------------------------------------

async def tool_noticias(ticker_ou_tema: str) -> dict:
    """
    Retorna manchetes recentes para o ticker ou tema fornecido.
    Cache de 4h. Nunca lança exceção.
    """
    if not ticker_ou_tema or not ticker_ou_tema.strip():
        return tool_error("Informe um ticker (ex: PETR4) ou tema (ex: Selic, inflação).")

    query = _build_query(ticker_ou_tema)
    key = _cache_key(query)

    cached = _from_cache(key)
    if cached:
        logger.info("noticias: cache hit para '%s' (%d itens)", query, len(cached))
        return {
            "query": query,
            "manchetes": cached,
            "total": len(cached),
            "source": "RSS (cache)",
            "is_cached": True,
        }

    import asyncio
    google_url = _GOOGLE_NEWS_URL.format(query=quote_plus(query))
    valor_url = _VALOR_URL

    # Busca ambas as fontes em paralelo
    google_xml, valor_xml = await asyncio.gather(
        _fetch(google_url),
        _fetch(valor_url),
        return_exceptions=False,
    )

    items: list[dict] = []

    # Google News (primário — já filtrado pela query)
    if google_xml:
        items.extend(_parse_rss(google_xml))

    # Valor Econômico (secundário — filtra por relevância)
    if valor_xml and len(items) < 4:
        filter_term = ticker_ou_tema.strip().upper() if _TICKER_RE.match(
            ticker_ou_tema.strip().upper()
        ) else ticker_ou_tema.strip()
        extra = _parse_rss(valor_xml, filter_query=filter_term)
        titulos_existentes = {i["titulo"] for i in items}
        for item in extra:
            if item["titulo"] not in titulos_existentes:
                items.append(item)

    if not items:
        return tool_error(
            f"Nenhuma manchete encontrada para '{ticker_ou_tema}'. "
            "Verifique o ticker/tema ou tente novamente em instantes."
        )

    items = items[:8]
    _to_cache(key, items)

    logger.info("noticias: %d manchetes para '%s'", len(items), query)
    return {
        "query": query,
        "manchetes": items,
        "total": len(items),
        "source": "Google News RSS / Valor Economico RSS",
        "is_cached": False,
        "nota": "Manchetes são indicativas. Verifique as fontes antes de tomar decisões.",
    }
