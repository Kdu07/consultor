"""
API de snapshots mensais da carteira (SnapshotMensal) — LEGADO, só leitura.

GET /snapshots — lista os snapshots antigos.

O snapshot manual (POST /snapshots, botão de câmera) foi aposentado em 10/2026
(docs/PLANO_HISTORICO.md, decisão 2 do dono): ele gravava a data de hoje com cotação ao vivo,
sem deduplicar, e se misturava aos fechamentos do extrato. As séries do Histórico saem dos
extratos arquivados (ExtratoImportado); os snapshots antigos ficam no banco, fora de série.
"""
import json
import logging
from datetime import date, datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import Session, select

from ..database import engine
from ..models.snapshot_mensal import SnapshotMensal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/snapshots", tags=["snapshots"])


class SnapshotOut(BaseModel):
    id: int
    data_referencia: date
    valor_total: float
    posicoes_count: int
    criado_em: datetime


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
