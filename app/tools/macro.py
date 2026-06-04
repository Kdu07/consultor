"""
Tool contexto_macro — dados macro do Brasil via API pública BCB/SGS.

Séries usadas:
  432  Meta Selic (% a.a.) — alvo definido pelo Copom
  433  IPCA variação mensal (% a.m.)
    1  Taxa de câmbio USD/BRL (compra, fim de período)

Contrato: nunca lança exceção. Falha parcial → campo com {"error": ...}.
"""
import logging
from datetime import timezone
import httpx
from .schemas import tool_error

logger = logging.getLogger(__name__)

_BCB_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados/ultimos/1?formato=json"

_SERIES = {
    "selic_meta":  432,
    "ipca_mensal": 433,
    "usd_brl":       1,
}


async def _fetch_serie(client: httpx.AsyncClient, nome: str, serie: int) -> dict:
    try:
        resp = await client.get(_BCB_URL.format(serie=serie), timeout=8.0)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return tool_error(f"BCB série {serie} retornou lista vazia")
        item = data[0]
        return {
            "valor": item["valor"],
            "data_referencia": item["data"],
            "source": "BCB",
            "serie": serie,
        }
    except Exception as e:
        logger.warning("BCB série %d (%s): %s", serie, nome, e)
        return tool_error(f"BCB série {serie} indisponível: {e}")


async def tool_contexto_macro() -> dict:
    """
    Retorna Meta Selic, IPCA mensal e câmbio USD/BRL.
    Nunca lança exceção — campos com erro recebem {"error": ...}.
    """
    import asyncio

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[
            _fetch_serie(client, nome, serie)
            for nome, serie in _SERIES.items()
        ])

    selic, ipca, usd = results

    macro = {
        "selic_meta_aa": selic,
        "ipca_mensal": ipca,
        "usd_brl": usd,
        "source": "BCB/SGS",
        "nota": (
            "selic_meta_aa = Meta Selic em % a.a. definida pelo Copom. "
            "ipca_mensal = variacao do IPCA no mes de referencia (% a.m.). "
            "usd_brl = cotacao de compra do dolar (R$/USD)."
        ),
    }

    logger.info(
        "contexto_macro: Selic=%s%% a.a. | IPCA=%s%% a.m. | USD/BRL=%s",
        selic.get("valor", "?"),
        ipca.get("valor", "?"),
        usd.get("valor", "?"),
    )
    return macro
