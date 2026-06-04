from typing import Optional
from datetime import date, datetime
from sqlmodel import SQLModel, Field


class SnapshotMensal(SQLModel, table=True):
    """Fotografia mensal da carteira para histórico de análise."""
    id: Optional[int] = Field(default=None, primary_key=True)
    data_referencia: date = Field(index=True)
    valor_total: float
    payload_json: str  # JSON com todas as posições e preços do momento
    criado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
