"""
API de snapshots mensais da carteira (SnapshotMensal).
POST /snapshots  — tira a fotografia atual.
GET  /snapshots  — lista histórico.
"""
import json
import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import Session, select

from ..database import engine
from ..models.posicao import Posicao
from ..models.snapshot_mensal import SnapshotMensal
from ..models.quote_cache import QuoteCache
from ..tools.valuation import valor_offline
from ..config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/snapshots", tags=["snapshots"])


class SnapshotOut(BaseModel):
    id: int
    data_referencia: date
    valor_total: float
    posicoes_count: int
    criado_em: datetime


@router.post("", response_model=SnapshotOut, status_code=201)
def criar_snapshot():
    """
    Tira uma fotografia da carteira com o melhor valor disponível:
    - preço ao vivo do cache (se não expirado) para RV/Tesouro
    - valor_mercado armazenado para RF/fundos
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    today = date.today()
    from datetime import timedelta
    ttl_cutoff = now - timedelta(seconds=settings.quote_cache_ttl_seconds)

    with Session(engine) as session:
        posicoes = session.exec(select(Posicao).where(Posicao.ativo == True)).all()

        if not posicoes:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Carteira vazia — nada a tirar snapshot.")

        # Monta mapa de preços do cache
        precos_cache: dict[str, float] = {}
        for p in posicoes:
            if p.ticker:
                row = session.exec(
                    select(QuoteCache)
                    .where(QuoteCache.ticker == p.ticker.upper())
                    .where(QuoteCache.fetched_at >= ttl_cutoff)
                    .order_by(QuoteCache.fetched_at.desc())
                ).first()
                if row:
                    precos_cache[p.ticker.upper()] = row.price

        # Calcula valor de cada posição
        snapshot_posicoes = []
        total = 0.0

        for p in posicoes:
            ticker = (p.ticker or "").upper()
            cached_price = precos_cache.get(ticker)

            if cached_price:
                valor = p.quantidade * cached_price
                source = "cache_ao_vivo"
            else:
                valor, usou_preco_medio = valor_offline(p)
                source = "preco_medio" if usou_preco_medio else (p.source or "extrato")

            total += valor
            snapshot_posicoes.append({
                "ticker": p.ticker,
                "nome": p.nome,
                "classe": p.classe.value,
                "quantidade": p.quantidade,
                "valor": round(valor, 2),
                "source": source,
                "as_of": p.as_of.isoformat() if p.as_of else None,
            })

        payload = {
            "data": today.isoformat(),
            "valor_total": round(total, 2),
            "posicoes": snapshot_posicoes,
        }

        snap = SnapshotMensal(
            data_referencia=today,
            valor_total=round(total, 2),
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        session.add(snap)
        session.commit()
        session.refresh(snap)

    logger.info(
        "snapshot criado: id=%d data=%s total=R$%.2f posicoes=%d",
        snap.id, today, total, len(posicoes),
    )
    return SnapshotOut(
        id=snap.id,
        data_referencia=snap.data_referencia,
        valor_total=snap.valor_total,
        posicoes_count=len(posicoes),
        criado_em=snap.criado_em,
    )


@router.get("", response_model=list[SnapshotOut])
def listar_snapshots():
    """Lista todos os snapshots em ordem cronológica decrescente."""
    with Session(engine) as session:
        snaps = session.exec(
            select(SnapshotMensal).order_by(SnapshotMensal.data_referencia.desc())
        ).all()

    # Conta posições em cada snapshot a partir do payload JSON
    result = []
    for s in snaps:
        try:
            payload = json.loads(s.payload_json)
            count = len(payload.get("posicoes", []))
        except Exception:
            count = 0
        result.append(SnapshotOut(
            id=s.id,
            data_referencia=s.data_referencia,
            valor_total=s.valor_total,
            posicoes_count=count,
            criado_em=s.criado_em,
        ))
    return result
