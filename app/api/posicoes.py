"""
API de posições — edição manual da carteira (PLANO §7.1, Fase 1).

Inclui renda fixa via valor do extrato (sem ticker; source="extrato").
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlmodel import Session, select

from ..database import get_session
from ..models.posicao import ClasseAtivo, Posicao

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/posicoes", tags=["posicoes"])


# ---------------------------------------------------------------------------
# Schemas de request/response
# ---------------------------------------------------------------------------

class PosicaoIn(BaseModel):
    nome: str
    classe: ClasseAtivo
    quantidade: float = 1.0
    ticker: Optional[str] = None
    preco_medio: Optional[float] = None
    # Para RF sem cotação pública (CDB, LCI, LCA, fundos):
    # passe valor_mercado + source="extrato" + as_of=data do extrato
    valor_mercado: Optional[float] = None
    source: str = "extrato"  # extrato | brapi | yfinance | tesouro (default extrato para RF manual)
    as_of: Optional[datetime] = None
    notas: Optional[str] = None

    @field_validator("ticker")
    @classmethod
    def upper_ticker(cls, v: Optional[str]) -> Optional[str]:
        return v.strip().upper() if v else None

    @field_validator("nome")
    @classmethod
    def clean_nome(cls, v: str) -> str:
        return v.strip()


class PosicaoOut(BaseModel):
    id: int
    nome: str
    ticker: Optional[str]
    classe: str
    quantidade: float
    preco_medio: Optional[float]
    valor_mercado: Optional[float]
    source: str
    as_of: Optional[datetime]
    notas: Optional[str]
    atualizado_em: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[PosicaoOut])
def listar_posicoes(session: Session = Depends(get_session)):
    """Lista todas as posições ativas."""
    posicoes = session.exec(select(Posicao).where(Posicao.ativo == True)).all()
    return [_to_out(p) for p in posicoes]


@router.post("", response_model=PosicaoOut, status_code=201)
def criar_ou_atualizar_posicao(
    body: PosicaoIn,
    session: Session = Depends(get_session),
):
    """
    Cria ou atualiza uma posição.
    Upsert por ticker (RV) ou por nome (RF sem ticker).
    """
    now = datetime.now(timezone.utc)

    # Tenta encontrar posição existente
    existing = None
    if body.ticker:
        existing = session.exec(
            select(Posicao)
            .where(Posicao.ticker == body.ticker)
            .where(Posicao.ativo == True)
        ).first()
    else:
        existing = session.exec(
            select(Posicao)
            .where(Posicao.nome == body.nome)
            .where(Posicao.ativo == True)
        ).first()

    if existing:
        # Atualiza
        existing.nome = body.nome
        existing.classe = body.classe
        existing.quantidade = body.quantidade
        existing.preco_medio = body.preco_medio
        existing.valor_mercado = body.valor_mercado
        existing.source = body.source
        existing.as_of = body.as_of
        existing.notas = body.notas
        existing.atualizado_em = now
        session.add(existing)
        session.commit()
        session.refresh(existing)
        logger.info("posicao atualizada: id=%d nome='%s'", existing.id, existing.nome)
        return _to_out(existing)

    # Cria nova
    nova = Posicao(
        nome=body.nome,
        ticker=body.ticker,
        classe=body.classe,
        quantidade=body.quantidade,
        preco_medio=body.preco_medio,
        valor_mercado=body.valor_mercado,
        source=body.source,
        as_of=body.as_of,
        notas=body.notas,
        atualizado_em=now,
    )
    session.add(nova)
    session.commit()
    session.refresh(nova)
    logger.info("posicao criada: id=%d nome='%s' ticker=%s", nova.id, nova.nome, nova.ticker)
    return _to_out(nova)


@router.delete("/{posicao_id}", status_code=204)
def desativar_posicao(
    posicao_id: int,
    session: Session = Depends(get_session),
):
    """Desativa (soft-delete) uma posição."""
    pos = session.get(Posicao, posicao_id)
    if not pos or not pos.ativo:
        raise HTTPException(status_code=404, detail="Posição não encontrada.")
    pos.ativo = False
    pos.atualizado_em = datetime.now(timezone.utc)
    session.add(pos)
    session.commit()
    logger.info("posicao desativada: id=%d", posicao_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_out(p: Posicao) -> PosicaoOut:
    return PosicaoOut(
        id=p.id,
        nome=p.nome,
        ticker=p.ticker,
        classe=p.classe.value,
        quantidade=p.quantidade,
        preco_medio=p.preco_medio,
        valor_mercado=p.valor_mercado,
        source=p.source,
        as_of=p.as_of,
        notas=p.notas,
        atualizado_em=p.atualizado_em,
    )
