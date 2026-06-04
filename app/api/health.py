import time
import logging
import httpx
from fastapi import APIRouter
from sqlmodel import Session, text
from ..database import engine
from ..config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


async def _check_bcb() -> dict:
    """Testa a API pública do BCB (série Selic = 11)."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/1?formato=json"
            )
            resp.raise_for_status()
            data = resp.json()
            return {"ok": True, "valor": data[0]["valor"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _check_yfinance() -> dict:
    try:
        import yfinance as yf
        ticker = yf.Ticker("PETR4.SA")
        info = ticker.fast_info
        price = info.last_price
        if price and price > 0:
            return {"ok": True, "price": round(price, 2)}
        return {"ok": False, "error": "preço inválido retornado"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _check_db() -> dict:
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1"))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/health")
async def health():
    settings = get_settings()
    t0 = time.perf_counter()

    db = _check_db()
    bcb = await _check_bcb()
    yf_check = await _check_yfinance()

    elapsed = round(time.perf_counter() - t0, 2)
    all_ok = db["ok"] and bcb["ok"] and yf_check["ok"]

    result = {
        "status": "ok" if all_ok else "degraded",
        "elapsed_s": elapsed,
        "model": settings.anthropic_model,
        "price_provider": settings.price_provider,
        "checks": {
            "db": db,
            "bcb": bcb,
            "yfinance": yf_check,
        },
    }
    logger.info("health-check: %s", result)
    return result
